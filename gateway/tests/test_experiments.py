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
    cell_cache_key,
    derive_experiment_id,
    expand,
    experiments_root,
    grid_size,
    render_args,
)


def _exp(**kw) -> Experiment:
    base = dict(
        id="e1", label="t", created_at="now",
        case_ids=("c1",), factors=(),
        server="surge", tool="run_ac_power_flow",
        args_template={"file_path": "{case_path}"},
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


def test_cache_key_ignores_key_order():
    a = cell_cache_key(case_sha256="s", server="x", tool="t", args={"a": 1, "b": 2})
    b = cell_cache_key(case_sha256="s", server="x", tool="t", args={"b": 2, "a": 1})
    assert a == b


def test_cache_key_changes_with_case_and_args():
    base = dict(server="x", tool="t", args={"a": 1})
    k0 = cell_cache_key(case_sha256="s1", **base)
    k1 = cell_cache_key(case_sha256="s2", **base)
    k2 = cell_cache_key(case_sha256="s1", server="x", tool="t", args={"a": 2})
    assert len({k0, k1, k2}) == 3


# ---------------------------------------------------------------- 网格展开


def test_expand_order_is_case_outer_then_factor_order():
    exp = _exp(
        case_ids=("c1", "c2"),
        factors=(Factor("lv", ("a", "b")), Factor("fs", ("x", "y"))),
        args_template={"lv": "{lv}", "fs": "{fs}"},
    )
    cells = expand(exp, sha_by_case={"c1": "s1", "c2": "s2"},
                   path_by_case={"c1": "p1", "c2": "p2"})
    assert [(c.case_id, c.bindings["lv"], c.bindings["fs"]) for c in cells] == [
        ("c1", "a", "x"), ("c1", "a", "y"), ("c1", "b", "x"), ("c1", "b", "y"),
        ("c2", "a", "x"), ("c2", "a", "y"), ("c2", "b", "x"), ("c2", "b", "y"),
    ]
    assert [c.index for c in cells] == list(range(8))
    assert all(c.status == "pending" for c in cells)


def test_expand_carries_case_sha_and_unique_keys():
    cells = expand(_exp(case_ids=("c1",)), sha_by_case={"c1": "abc"},
                   path_by_case={"c1": "p"})
    assert cells[0].case_sha256 == "abc"
    assert cells[0].cache_key == cell_cache_key(
        case_sha256="abc", server="surge", tool="run_ac_power_flow",
        args={"file_path": "p"},
    )


def test_grid_size_counts_cases_times_factors():
    exp = _exp(case_ids=("c1", "c2"),
               factors=(Factor("lv", ("a", "b", "c")), Factor("fs", ("x", "y"))))
    assert grid_size(exp) == 2 * 3 * 2


# ---------------------------------------------------------------- 请求解析


def _parse(payload, **kw):
    from powermcp_gateway.experiments import parse_experiment_request
    return parse_experiment_request(payload, known_servers=("surge", "pandapower"), **kw)


def test_parse_rejects_non_object():
    exp, err = _parse([1, 2])
    assert exp is None and "JSON 对象" in err


def test_parse_requires_case_ids():
    exp, err = _parse({"step": {"server": "surge", "tool": "t"}})
    assert exp is None and "case_ids" in err


def test_parse_accepts_single_case_id():
    exp, err = _parse({"case_id": "c1", "step": {"server": "surge", "tool": "t"}})
    assert err is None and exp.case_ids == ("c1",)


def test_parse_rejects_unknown_server_with_actionable_list():
    exp, err = _parse({"case_ids": ["c1"], "step": {"server": "gurobi", "tool": "t"}})
    assert exp is None and "gurobi" in err and "surge" in err


def test_parse_rejects_factor_named_like_builtin():
    for name in BUILTIN_PLACEHOLDERS:
        exp, err = _parse({
            "case_ids": ["c1"],
            "factors": [{"name": name, "values": [1]}],
            "step": {"server": "surge", "tool": "t"},
        })
        assert exp is None and name in err, f"{name} 应被拒（会静默覆盖内置值）"


def test_parse_rejects_bad_factor_name_and_container_values():
    exp, err = _parse({
        "case_ids": ["c1"],
        "factors": [{"name": "9lv", "values": [1]}],
        "step": {"server": "surge", "tool": "t"},
    })
    assert exp is None and "标识符" in err

    exp, err = _parse({
        "case_ids": ["c1"],
        "factors": [{"name": "lv", "values": [{"a": 1}]}],
        "step": {"server": "surge", "tool": "t"},
    })
    assert exp is None and "标量" in err


def test_parse_rejects_duplicate_factor_values():
    exp, err = _parse({
        "case_ids": ["c1"],
        "factors": [{"name": "lv", "values": [1, 1]}],
        "step": {"server": "surge", "tool": "t"},
    })
    assert exp is None and "重复" in err


def test_parse_rejects_oversized_grid_and_reports_size():
    exp, err = _parse({
        "case_ids": ["c1"],
        "factors": [{"name": "lv", "values": list(range(MAX_CELLS + 1))}],
        "step": {"server": "surge", "tool": "t"},
    })
    assert exp is None and str(MAX_CELLS + 1) in err


def test_parse_rejects_unrenderable_template_before_registering():
    """★ 模板错误必须在**登记时**暴露，而不是留到执行期让每格各报一次。"""
    exp, err = _parse({
        "case_ids": ["c1"],
        "step": {"server": "surge", "tool": "t",
                 "args_template": {"x": "{missing}"}},
    })
    assert exp is None and "missing" in err


def test_parse_unregistered_case_is_400_not_409(store_and_cfg):
    store, cfg = store_and_cfg
    exp, err = _parse({"case_ids": ["nope"], "step": {"server": "surge", "tool": "t"}},
                      store=store["exp_store"], cfg=cfg)
    assert exp is None and err is not None and "/cases" in err


def test_parse_case_outside_roots_raises_409_class(store_and_cfg):
    """算例存在但不在围笼内 = **可修复的状态问题** → 抛 409 型异常，不是 400 文案。"""
    store, cfg = store_and_cfg
    from powermcp_gateway.cases import CaseStore, cases_root
    case_store = CaseStore(cases_root(cfg))
    case, _ = case_store.register(store["file"])
    with pytest.raises(ExperimentCaseStateError) as ei:
        _parse({"case_ids": [case.id], "step": {"server": "surge", "tool": "t"}},
               store=store["exp_store"], cfg=cfg)
    assert "ALLOWED_ROOTS" in str(ei.value)


# ---------------------------------------------------------------- 存储


def test_store_create_list_get(tmp_path):
    st = ExperimentStore(tmp_path / "exp")
    exp = _exp(id="a")
    st.create(exp)
    assert [e.id for e in st.list()] == ["a"]
    assert st.get("a").tool == "run_ac_power_flow"


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
    c = derive_experiment_id(_exp(id="", tool="other"))
    assert a == b and a != c


def test_experiments_root_default_is_not_upstream_dir(monkeypatch):
    monkeypatch.delenv("POWERMCP_GATEWAY_EXPERIMENTS_ROOT", raising=False)
    root = experiments_root(None)
    assert root.name == "experiments"
    assert ".powermcp_gateway" in root.parts     # 网关自有目录
    assert ".powermcp" not in root.parts         # 上游目录，不得写入


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
