"""实验矩阵**定义层**的单元测试（`experiments.py`，P2-①a）。

★ 三条最要紧的不变式（都是本项目反复付过学费的）：
  1. **未知占位符不得静默留下** —— 留在 args 里会变成"跑成功但没生效"的假结果；
  2. **整串占位符保类型** —— 否则数值参数被渲染成字符串，契约 3 会以"类型不符"拒发；
  3. **格子是现算的，不是快照** —— 改了模板/算例，同一格必须算出新的 `cache_key`。
"""

from __future__ import annotations

import json

import pytest

from powermcp_gateway.experiments import (
    BUILTIN_PLACEHOLDERS,
    MAX_CELLS,
    Experiment,
    ExperimentCaseStateError,
    ExperimentError,
    ExperimentIndexError,
    ExperimentStore,
    Factor,
    ResultsStore,
    Step,
    StepOutcome,
    build_results_report,
    cell_cache_key,
    derive_experiment_id,
    execute_cells,
    expand,
    experiments_root,
    export_table,
    extract_metrics,
    grid_size,
    render_args,
    status_counts,
    unreferenced_factors,
)


def _steps(*, server="surge", tool="run_ac_power_flow",
           args_template=None) -> tuple[Step, ...]:
    return (Step(server=server, tool=tool,
                 args_template=args_template if args_template is not None
                 else {"file_path": "{case_path}"}),)


def _exp(**kw) -> Experiment:
    base = dict(
        id="e1", label="t", created_at="now",
        case_ids=("c1",), factors=(),
        steps=_steps(),
    )
    base.update(kw)
    return Experiment(**base)


# ---------------------------------------------------------------- 模板渲染


def test_whole_placeholder_keeps_type():
    """`"{x}"` → 1.1（float），**不是** "1.1"。"""
    out = render_args({"scale": "{x}"}, {"x": 1.1}, case_path="p", case_id="c")
    assert out["scale"] == 1.1 and isinstance(out["scale"], float)


def test_whole_placeholder_keeps_bool_and_int():
    out = render_args({"a": "{x}", "b": "{y}"}, {"x": True, "y": 3},
                      case_path="p", case_id="c")
    assert out["a"] is True and out["b"] == 3 and isinstance(out["b"], int)


def test_interpolated_placeholder_is_string():
    out = render_args({"name": "case-{n}"}, {"n": 7}, case_path="p", case_id="c")
    assert out["name"] == "case-7"


def test_builtin_placeholders_available():
    out = render_args({"p": "{case_path}", "i": "{case_id}"}, {},
                      case_path="/tmp/a.m", case_id="c9")
    assert out == {"p": "/tmp/a.m", "i": "c9"}


def test_unknown_placeholder_raises_not_silent():
    """★ 未知占位符必须报错 —— 静默留下 `{nope}` 会产出"跑成功但没生效"的结果。"""
    with pytest.raises(ExperimentError) as ei:
        render_args({"x": "{nope}"}, {}, case_path="p", case_id="c")
    assert "nope" in str(ei.value)


def test_unknown_placeholder_in_interpolation_raises():
    with pytest.raises(ExperimentError) as ei:
        render_args({"x": "a-{nope}-b"}, {}, case_path="p", case_id="c")
    assert "nope" in str(ei.value)


def test_malformed_placeholder_raises():
    with pytest.raises(ExperimentError):
        render_args({"x": "{unclosed"}, {}, case_path="p", case_id="c")


def test_nested_containers_are_rendered():
    out = render_args({"a": {"b": ["{n}", 1]}}, {"n": 2}, case_path="p", case_id="c")
    assert out == {"a": {"b": [2, 1]}}


# ---------------------------------------------------------------- cache_key


def _one_step(tool: str = "t", args: dict | None = None) -> tuple[dict, ...]:
    return ({"server": "x", "tool": tool, "args": args if args is not None else {"a": 1}},)


def test_cache_key_ignores_arg_key_order():
    a = cell_cache_key(case_sha256="s", steps=_one_step(args={"a": 1, "b": 2}))
    b = cell_cache_key(case_sha256="s", steps=_one_step(args={"b": 2, "a": 1}))
    assert a == b


def test_cache_key_changes_with_case_and_args():
    k0 = cell_cache_key(case_sha256="s1", steps=_one_step())
    k1 = cell_cache_key(case_sha256="s2", steps=_one_step())
    k2 = cell_cache_key(case_sha256="s1", steps=_one_step(args={"a": 2}))
    assert len({k0, k1, k2}) == 3


def test_cache_key_is_order_sensitive_over_steps():
    """★ 步骤**顺序**参与身份：`[load, run]` ≠ `[run, load]`（后者根本跑不通）。"""
    load = {"server": "surge", "tool": "load_network", "args": {"file_path": "p"}}
    run = {"server": "surge", "tool": "run_n1_branch_contingency", "args": {}}
    assert cell_cache_key(case_sha256="s", steps=(load, run)) != \
        cell_cache_key(case_sha256="s", steps=(run, load))


# ---------------------------------------------------------------- 网格展开


def test_expand_order_is_case_outer_then_factor_order():
    exp = _exp(
        case_ids=("c1", "c2"),
        factors=(Factor("lv", ("a", "b")), Factor("fs", ("x", "y"))),
        steps=(Step(server="surge", tool="t",
                    args_template={"lv": "{lv}", "fs": "{fs}"}),),
    )
    cells = expand(exp, sha_by_case={"c1": "s1", "c2": "s2"},
                   path_by_case={"c1": "p1", "c2": "p2"})
    assert [(c.case_id, c.bindings["lv"], c.bindings["fs"]) for c in cells] == [
        ("c1", "a", "x"), ("c1", "a", "y"), ("c1", "b", "x"), ("c1", "b", "y"),
        ("c2", "a", "x"), ("c2", "a", "y"), ("c2", "b", "x"), ("c2", "b", "y"),
    ]
    assert [c.index for c in cells] == list(range(8))
    assert all(c.status == "pending" for c in cells)


def test_expand_renders_every_step_in_order():
    """★ 一格渲染出**全部步骤**，且顺序与声明一致（有状态序列的表达力所在）。"""
    exp = _exp(steps=(
        Step(server="surge", tool="load_network",
             args_template={"file_path": "{case_path}"}),
        Step(server="surge", tool="run_n1_branch_contingency",
             args_template={"monitored_branches": []}),
    ))
    cells = expand(exp, sha_by_case={"c1": "abc"}, path_by_case={"c1": "/tmp/a.m"})
    assert [s["tool"] for s in cells[0].steps] == [
        "load_network", "run_n1_branch_contingency",
    ]
    assert cells[0].steps[0]["args"] == {"file_path": "/tmp/a.m"}
    assert cells[0].steps[1]["args"] == {"monitored_branches": []}


def test_expand_carries_case_sha_and_unique_keys():
    cells = expand(_exp(case_ids=("c1",)), sha_by_case={"c1": "abc"},
                   path_by_case={"c1": "p"})
    assert cells[0].case_sha256 == "abc"
    assert cells[0].cache_key == cell_cache_key(
        case_sha256="abc",
        steps=({"server": "surge", "tool": "run_ac_power_flow",
                "args": {"file_path": "p"}},),
    )


def test_grid_size_counts_cases_times_factors():
    exp = _exp(case_ids=("c1", "c2"),
               factors=(Factor("lv", ("a", "b", "c")), Factor("fs", ("x", "y"))))
    assert grid_size(exp) == 2 * 3 * 2


def test_unreferenced_factors_detected():
    """★ 未被模板引用的因子会产出**内容相同的重复格**（cache_key 相同）—— 必须报出。"""
    exp = _exp(
        factors=(Factor("lv", (1.0, 1.1)), Factor("fs", ("a",))),
        steps=(Step("surge", "t", {"x": "{lv}"}),),
    )
    assert unreferenced_factors(exp) == ("fs",)


def test_unreferenced_factors_none_when_all_used():
    exp = _exp(
        factors=(Factor("lv", (1.0,)), Factor("fs", ("a",))),
        steps=(Step("surge", "t", {"a": "{lv}", "b": ["{fs}"]}),),
    )
    assert unreferenced_factors(exp) == ()


# ---------------------------------------------------------------- 请求解析


def _parse(payload, **kw):
    from powermcp_gateway.experiments import parse_experiment_request
    return parse_experiment_request(payload, known_servers=("surge", "pandapower"), **kw)


def test_parse_rejects_non_object():
    exp, err = _parse([1, 2])
    assert exp is None and "JSON 对象" in err


def test_parse_requires_case_ids():
    exp, err = _parse({"steps": [{"server": "surge", "tool": "t"}]})
    assert exp is None and "case_ids" in err


def test_parse_accepts_single_case_id():
    exp, err = _parse({"case_id": "c1", "steps": [{"server": "surge", "tool": "t"}]})
    assert err is None and exp.case_ids == ("c1",)


def test_parse_rejects_unknown_server_with_actionable_list():
    exp, err = _parse({"case_ids": ["c1"], "steps": [{"server": "gurobi", "tool": "t"}]})
    assert exp is None and "gurobi" in err and "surge" in err


def test_parse_rejects_factor_named_like_builtin():
    for name in BUILTIN_PLACEHOLDERS:
        exp, err = _parse({
            "case_ids": ["c1"],
            "factors": [{"name": name, "values": [1]}],
            "steps": [{"server": "surge", "tool": "t"}],
        })
        assert exp is None and name in err, f"{name} 应被拒（会静默覆盖内置值）"


def test_parse_rejects_bad_factor_name_and_container_values():
    exp, err = _parse({
        "case_ids": ["c1"],
        "factors": [{"name": "9lv", "values": [1]}],
        "steps": [{"server": "surge", "tool": "t"}],
    })
    assert exp is None and "标识符" in err

    exp, err = _parse({
        "case_ids": ["c1"],
        "factors": [{"name": "lv", "values": [{"a": 1}]}],
        "steps": [{"server": "surge", "tool": "t"}],
    })
    assert exp is None and "标量" in err


def test_parse_rejects_duplicate_factor_values():
    exp, err = _parse({
        "case_ids": ["c1"],
        "factors": [{"name": "lv", "values": [1, 1]}],
        "steps": [{"server": "surge", "tool": "t"}],
    })
    assert exp is None and "重复" in err


def test_parse_rejects_oversized_grid_and_reports_size():
    exp, err = _parse({
        "case_ids": ["c1"],
        "factors": [{"name": "lv", "values": list(range(MAX_CELLS + 1))}],
        "steps": [{"server": "surge", "tool": "t"}],
    })
    assert exp is None and str(MAX_CELLS + 1) in err


def test_parse_rejects_unrenderable_template_before_registering():
    """★ 模板错误必须在**登记时**暴露，而不是留到执行期让每格各报一次。"""
    exp, err = _parse({
        "case_ids": ["c1"],
        "steps": [{"server": "surge", "tool": "t",
                   "args_template": {"x": "{missing}"}}],
    })
    assert exp is None and "missing" in err


def test_parse_rejects_missing_steps():
    exp, err = _parse({"case_ids": ["c1"]})
    assert exp is None and "steps" in err


def test_parse_rejects_empty_steps():
    exp, err = _parse({"case_ids": ["c1"], "steps": []})
    assert exp is None and "非空" in err


def test_parse_rejects_cross_server_steps():
    """★ 全部步骤必须同 server —— 一次实验只在一个 server 会话内执行。

    跨 server 的步骤需要多个会话，且上一步的引擎状态对另一个 server 没有意义。
    """
    exp, err = _parse({
        "case_ids": ["c1"],
        "steps": [
            {"server": "surge", "tool": "load_network"},
            {"server": "pandapower", "tool": "run_power_flow"},
        ],
    })
    assert exp is None and "同一个 server" in err
    assert "surge" in err and "pandapower" in err


def test_parse_accepts_multi_step_same_server():
    exp, err = _parse({
        "case_ids": ["c1"],
        "steps": [
            {"server": "surge", "tool": "load_network",
             "args_template": {"file_path": "{case_path}"}},
            {"server": "SURGE", "tool": "run_n1_branch_contingency"},
        ],
    })
    assert err is None
    assert [s.tool for s in exp.steps] == ["load_network", "run_n1_branch_contingency"]
    assert all(s.server == "surge" for s in exp.steps)  # 大小写归一
    assert exp.server == "surge"


def test_parse_unregistered_case_is_400_not_409(store_and_cfg):
    store, cfg = store_and_cfg
    exp, err = _parse({"case_ids": ["nope"], "steps": [{"server": "surge", "tool": "t"}]},
                      store=store["exp_store"], cfg=cfg)
    assert exp is None and err is not None and "/cases" in err


def test_parse_case_outside_roots_raises_409_class(store_and_cfg):
    """算例存在但不在围笼内 = **可修复的状态问题** → 抛 409 型异常，不是 400 文案。"""
    store, cfg = store_and_cfg
    from powermcp_gateway.cases import CaseStore, cases_root
    case_store = CaseStore(cases_root(cfg))
    case, _ = case_store.register(store["file"])
    with pytest.raises(ExperimentCaseStateError) as ei:
        _parse({"case_ids": [case.id], "steps": [{"server": "surge", "tool": "t"}]},
               store=store["exp_store"], cfg=cfg)
    assert "ALLOWED_ROOTS" in str(ei.value)


# ---------------------------------------------------------------- 存储


def test_store_create_list_get(tmp_path):
    st = ExperimentStore(tmp_path / "exp")
    exp = _exp(id="a")
    st.create(exp)
    assert [e.id for e in st.list()] == ["a"]
    assert st.get("a").steps[0].tool == "run_ac_power_flow"


def test_store_duplicate_id_rejected(tmp_path):
    st = ExperimentStore(tmp_path / "exp")
    st.create(_exp(id="a"))
    with pytest.raises(ExperimentError):
        st.create(_exp(id="a"))


def test_store_corrupt_index_is_loud(tmp_path):
    """★ 索引损坏必须响亮 —— 静默当成空库会让用户以为实验全丢了。"""
    root = tmp_path / "exp"
    root.mkdir()
    (root / "experiments.json").write_text("{not json", encoding="utf-8")
    st = ExperimentStore(root)
    with pytest.raises(ExperimentIndexError):
        st.list()


def test_derive_id_is_stable_and_content_addressed():
    a = derive_experiment_id(_exp(id=""))
    b = derive_experiment_id(_exp(id=""))
    c = derive_experiment_id(_exp(id="", steps=_steps(tool="other")))
    assert a == b and a != c


def test_experiments_root_default_is_not_upstream_dir(monkeypatch):
    monkeypatch.delenv("POWERMCP_GATEWAY_EXPERIMENTS_ROOT", raising=False)
    root = experiments_root(None)
    assert root.name == "experiments"
    assert ".powermcp_gateway" in root.parts     # 网关自有目录
    assert ".powermcp" not in root.parts         # 上游目录，不得写入


# ---------------------------------------------------------------- 执行（P2-①b）


def _session_counter():
    """确定性的会话工厂（返回 s0 / s1 / ...），便于断言「一格一个会话」。"""
    made: list[str] = []

    def new_session() -> str:
        s = f"s{len(made)}"
        made.append(s)
        return s

    return new_session, made


async def test_execute_cells_serial_and_one_session_per_cell():
    """★ 一格一个会话：会话是引擎状态的边界，跨格复用会让结果张冠李戴。"""
    exp = _exp(case_ids=("c1", "c2"), steps=(Step("surge", "t"),))
    cells = expand(exp, sha_by_case={"c1": "a", "c2": "b"},
                   path_by_case={"c1": "p1", "c2": "p2"})
    order: list[str] = []

    async def run_step(sid, server, tool, args):
        order.append(sid)
        return StepOutcome(ok=True)

    new_session, made = _session_counter()
    recs = await execute_cells(cells, new_session=new_session, run_step=run_step)

    assert [r["status"] for r in recs] == ["ok", "ok"]
    assert made == ["s0", "s1"]           # 两格 → 两个会话
    assert order == ["s0", "s1"]          # 串行，且各用自己的会话


async def test_execute_cells_failure_stops_cell_but_not_others():
    """★ 某步失败 → 本格后续步不跑（后续步依赖前序状态），但其他格照跑。"""
    exp = _exp(case_ids=("c1", "c2"), steps=(
        Step("surge", "load_network"),
        Step("surge", "run_n1_branch_contingency"),
    ))
    cells = expand(exp, sha_by_case={"c1": "a", "c2": "b"},
                   path_by_case={"c1": "p1", "c2": "p2"})
    seen: list[tuple[str, str]] = []

    async def run_step(sid, server, tool, args):
        seen.append((sid, tool))
        if sid == "s0":
            return StepOutcome(ok=False, error="引擎拒绝了该算例")
        return StepOutcome(ok=True)

    new_session, _ = _session_counter()
    recs = await execute_cells(cells, new_session=new_session, run_step=run_step)

    assert recs[0]["status"] == "failed"
    assert len(recs[0]["steps"]) == 1                       # 第二步没跑
    assert ("s0", "run_n1_branch_contingency") not in seen
    assert recs[1]["status"] == "ok"                        # 其他格不受影响
    assert len(recs[1]["steps"]) == 2


async def test_execute_cells_remounted_is_failure():
    """★ remounted=True 一律判失败 —— 重连意味着 server 进程死过、会话状态已丢。"""
    exp = _exp(steps=(Step("surge", "t"),))
    cells = expand(exp, sha_by_case={"c1": "a"}, path_by_case={"c1": "p"})

    async def run_step(sid, server, tool, args):
        return StepOutcome(ok=True, remounted=True)

    new_session, _ = _session_counter()
    recs = await execute_cells(cells, new_session=new_session, run_step=run_step)
    assert recs[0]["status"] == "failed"
    assert recs[0]["steps"][0]["ok"] is True                # 调用本身成功了……
    assert "remounted" in recs[0]["steps"][0]["error"]      # ……但状态不可担保


async def test_execute_cells_records_bind_cache_key_and_case():
    exp = _exp(case_ids=("c1",))
    cells = expand(exp, sha_by_case={"c1": "abc"}, path_by_case={"c1": "p"})

    async def run_step(sid, server, tool, args):
        return StepOutcome(ok=True, result_excerpt={"inner": {"n": 1}})

    new_session, _ = _session_counter()
    recs = await execute_cells(cells, new_session=new_session, run_step=run_step)
    assert recs[0]["cache_key"] == cells[0].cache_key
    assert recs[0]["case_id"] == "c1"
    assert recs[0]["case_sha256"] == "abc"
    assert recs[0]["steps"][0]["result_excerpt"] == {"inner": {"n": 1}}
    assert recs[0]["ran_at"]


def test_status_counts_empty_is_empty_dict():
    """空集 ≠ 全部正常 —— 返回 `{}` 而不是 `{ok: 0}`。"""
    assert status_counts(()) == {}
    assert status_counts(({"status": "ok"}, {"status": "failed"}, {"status": "ok"})) == {
        "ok": 2, "failed": 1,
    }


# ---------------------------------------------------------------- 结果库


def test_results_store_merges_by_cache_key(tmp_path):
    st = ResultsStore(tmp_path / "e1")
    st.merge(({"cache_key": "k1", "status": "ok"},))
    assert st.get("k1")["status"] == "ok"
    st.merge(({"cache_key": "k2", "status": "failed"},))
    assert set(st.all()) == {"k1", "k2"}
    st.merge(({"cache_key": "k1", "status": "failed"},))     # 覆盖同一 key
    assert st.get("k1")["status"] == "failed"


def test_results_store_corrupt_is_loud(tmp_path):
    root = tmp_path / "e1"
    root.mkdir()
    (root / "results.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ExperimentIndexError):
        ResultsStore(root).all()


def test_results_store_ignores_records_without_cache_key(tmp_path):
    st = ResultsStore(tmp_path / "e1")
    st.merge(({"status": "ok"},))                            # 无 cache_key → 不入库
    assert st.all() == {}


# ---------------------------------------------------------------- 结果表 / 导出（P2-①c）


def _report_with_one_run():
    exp = _exp(case_ids=("c1", "c2"))
    cells = expand(exp, sha_by_case={"c1": "a", "c2": "b"},
                   path_by_case={"c1": "p1", "c2": "p2"})
    stored = {
        cells[0].cache_key: {
            "status": "ok", "ran_at": "2026-09-27T00:00:00Z", "case_id": "c1",
            "steps": [{"index": 0, "tool": "t", "ok": True, "result_excerpt": {
                "inner": {"status": "success",
                          "results": {"n_contingencies": 46, "violations": [{}, {}]}},
            }}],
        },
    }
    return build_results_report(exp, cells, stored), cells


def test_extract_metrics_flattens_scalars_and_list_lengths():
    m = extract_metrics({"inner": {"status": "success", "results": {
        "n_contingencies": 46, "violations": [{}, {}], "solve_time_secs": 0.5,
    }}})
    assert m["metric.status"] == "success"
    assert m["metric.results.n_contingencies"] == 46
    assert m["metric.results.violations.count"] == 2   # 列表长度是真实可核对的量
    assert m["metric.results.solve_time_secs"] == 0.5


def test_extract_metrics_refuses_truncated_and_unserializable():
    """★ 摘要被截断时**宁可空**，也不给半截指标。"""
    assert extract_metrics({"__truncated__": True, "bytes": 99}) == {}
    assert extract_metrics({"__unserializable__": True}) == {}


def test_extract_metrics_caps_key_count():
    m = extract_metrics({"inner": {f"k{i}": i for i in range(200)}}, max_keys=10)
    assert len(m) == 10


def test_extract_metrics_skips_overlong_strings():
    m = extract_metrics({"inner": {"msg": "x" * 200, "ok": "short"}})
    assert "metric.msg" not in m and m["metric.ok"] == "short"


def test_results_report_marks_never_run_and_flags_orphaned():
    report, cells = _report_with_one_run()
    assert [r["status"] for r in report["rows"]] == ["ok", "never_run"]
    assert report["summary"]["by_status"] == {"ok": 1, "never_run": 1}
    assert report["summary"]["orphaned"] == 0
    assert {c["key"] for c in report["columns"]} >= {"index", "case_id", "status", "ran_at",
                                                     "metric.results.n_contingencies"}

    # 旧 key（不对应任何当前格子）→ 进入 orphaned，不冒充当前条件
    exp = _exp(case_ids=("c1", "c2"))
    stored = {"stale-key": {"status": "ok", "steps": []}}
    rep2 = build_results_report(exp, cells, stored)
    assert rep2["orphaned_keys"] == ["stale-key"]
    assert rep2["summary"]["orphaned"] == 1
    assert any("orphaned" in n for n in rep2["notes"])


def test_results_columns_have_no_duplicate_keys():
    """★ 真实网关 e2e 暴露的缺陷：引擎内层 JSON 顶层就有 `status`（值 `"success"`），
    与结果表的保留列 `status`（格子执行状态）**撞名** —— 实测列定义里出现两个 `status`，
    按 key 取值的消费者必然取错一个。指标统一加 `metric.` 前缀后不可能再撞。
    """
    report, _ = _report_with_one_run()
    keys = [c["key"] for c in report["columns"]]
    assert len(keys) == len(set(keys)), f"列 key 重复：{keys}"
    assert "metric.status" in keys            # 引擎内层的 status 仍保留（但要能区分）
    assert keys.count("status") == 1          # 保留列只有一格 status


def test_results_report_is_columns_union_sorted():
    report, _ = _report_with_one_run()
    metric_cols = [c["key"] for c in report["columns"]
                   if c["key"].startswith("metric.")]
    assert metric_cols == sorted(metric_cols)


def test_export_csv_has_header_rows_and_factor_columns():
    report, _ = _report_with_one_run()
    text = export_table(report, "csv")
    lines = text.strip().split("\n")
    assert lines[0].startswith("index,case_id,status,ran_at,cache_key")
    assert "metric.results.n_contingencies" in lines[0]
    assert len(lines) == 3                       # 表头 + 2 格


def test_export_markdown_is_a_table():
    report, _ = _report_with_one_run()
    text = export_table(report, "md")
    lines = text.strip().split("\n")
    assert lines[0].startswith("| index | case_id |")
    assert set(lines[1].replace("|", "").replace(" ", "")) == {"-"}
    assert len(lines) == 4                       # 表头 + 分隔行 + 2 格


def test_export_rejects_unknown_format():
    report, _ = _report_with_one_run()
    with pytest.raises(ExperimentError) as ei:
        export_table(report, "pdf")
    assert "pdf" in str(ei.value)


# ---------------------------------------------------------------- fixture


@pytest.fixture
def store_and_cfg(tmp_path, monkeypatch):
    """一个**不在**路径围笼内的已登记算例 + 实验库（用于验证 409 分支）。

    ★ 刻意**不设** `POWERIO_MCP_ALLOWED_ROOTS`：tmp_path 天然不在围笼内，
      正好覆盖「算例存在但 server 读不到」这一可修复状态。
    """
    from powermcp_gateway.config import GatewayConfig

    monkeypatch.setenv("POWERMCP_GATEWAY_CASES_ROOT", str(tmp_path / "cases"))
    monkeypatch.setenv("POWERMCP_GATEWAY_EXPERIMENTS_ROOT", str(tmp_path / "exp"))
    monkeypatch.delenv("POWERIO_MCP_ALLOWED_ROOTS", raising=False)

    f = tmp_path / "data" / "case39.m"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"MPC\n")

    cfg = GatewayConfig.discover()
    return {
        "file": f,
        "exp_store": ExperimentStore(experiments_root(cfg)),
        "cfg": cfg,
    }, cfg
