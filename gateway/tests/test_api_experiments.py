"""实验矩阵端点（`/experiments`）的测试（P2-①a）。

★ 错误映射：定义非法 400 · 算例状态不允许 409 · 未知实验 id 404 · 索引损坏 500 · 配置失败 503。
★ 最要紧的一条：**本步不执行** —— 端点返回的是「要跑什么」，全部格子为 `pending`，
   不得出现任何"已成功/已完成"的假状态（UI 规范 P5：未知态必须可见，禁止静默 fail-open）。
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from powermcp_gateway.api import create_app
from powermcp_gateway.config import GatewayConfig


@pytest.fixture
def cfg():
    return GatewayConfig.discover()


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """**把 tmp_path 放进路径围笼** —— 否则算例会被判为 server 不可读（409）。

    ★ 与 `test_experiments.py` 的 fixture 相反：那边要覆盖 409，这边要覆盖正常路径。
    """
    monkeypatch.setenv("POWERMCP_GATEWAY_CASES_ROOT", str(tmp_path / "cases"))
    monkeypatch.setenv("POWERMCP_GATEWAY_EXPERIMENTS_ROOT", str(tmp_path / "exp"))
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(tmp_path))
    return tmp_path


@pytest.fixture
def app(cfg, roots):
    return create_app(cfg=cfg)


@pytest.fixture
def case_id(cfg, roots, tmp_path):
    """登记一个算例。

    ⚠️ **不走 HTTP**（原先经 `POST /cases`）：那会调 `create_app()`，
       而 `create_app` 会把全局 `_POOL` 重置为 `None` —— 于是 `pool_app`
       刚装好的会话池会被这个 fixture 悄悄抹掉，多步实验测试全部假失败。
       直接经 `CaseStore` 登记，与 `_POOL` 完全解耦。
    """
    from powermcp_gateway.cases import CaseStore, cases_root

    f = tmp_path / "data" / "case39.m"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"MPC\n")
    case, _ = CaseStore(cases_root(cfg)).register(f, label="IEEE 39")
    return case.id


async def _req(app, method: str, path: str, **kw):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.request(method, path, **kw)


def _payload(cid: str, **kw) -> dict:
    body = {
        "case_ids": [cid],
        "factors": [{"name": "load_level", "values": [1.0, 1.1]}],
        "steps": [
            {"server": "surge", "tool": "run_ac_power_flow",
             "args_template": {"file_path": "{case_path}", "scale": "{load_level}"}},
        ],
    }
    body.update(kw)
    return body


async def test_routes_registered(app):
    paths = {getattr(r, "path", "") for r in app.routes}
    assert {"/experiments", "/experiments/{eid}"} <= paths


async def test_list_empty(app):
    r = await _req(app, "GET", "/experiments")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["total"] == 0
    assert body["index_exists"] is False


async def test_create_returns_201_with_expanded_cells(app, case_id):
    r = await _req(app, "POST", "/experiments", json=_payload(case_id))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created"] is True
    assert body["summary"]["cells"] == 2
    cells = body["cells"]
    assert [c["bindings"]["load_level"] for c in cells] == [1.0, 1.1]
    # 整串占位符保类型：scale 必须是 float 而不是 "1.0"
    assert all(isinstance(c["steps"][0]["args"]["scale"], float) for c in cells)
    assert all(c["status"] == "pending" for c in cells)
    assert len({c["cache_key"] for c in cells}) == 2


async def test_same_definition_returns_200_not_201(app, case_id):
    await _req(app, "POST", "/experiments", json=_payload(case_id))
    r = await _req(app, "POST", "/experiments", json=_payload(case_id))
    assert r.status_code == 200
    assert r.json()["created"] is False
    assert (await _req(app, "GET", "/experiments")).json()["summary"]["total"] == 1


async def test_get_by_id(app, case_id):
    created = (await _req(app, "POST", "/experiments", json=_payload(case_id))).json()
    eid = created["experiment"]["id"]
    r = await _req(app, "GET", f"/experiments/{eid}")
    assert r.status_code == 200
    body = r.json()
    assert body["experiment"]["id"] == eid
    assert body["summary"]["cells"] == 2
    assert body["summary"]["by_status"] == {"pending": 2}
    assert body["notes"]


async def test_unknown_id_is_404(app):
    r = await _req(app, "GET", "/experiments/nope")
    assert r.status_code == 404


async def test_delete_experiment_removes_definition_and_results(app, case_id, roots):
    created = (await _req(app, "POST", "/experiments", json=_payload(case_id))).json()
    eid = created["experiment"]["id"]
    result_dir = roots / "exp" / eid
    result_dir.mkdir(parents=True)
    (result_dir / "results.json").write_text("{}", encoding="utf-8")

    r = await _req(app, "DELETE", f"/experiments/{eid}")
    assert r.status_code == 200
    assert r.json() == {"deleted": True, "experiment_id": eid}
    assert (await _req(app, "GET", "/experiments")).json()["summary"]["total"] == 0
    assert not result_dir.exists()
    assert (await _req(app, "GET", f"/experiments/{eid}")).status_code == 404


async def test_delete_unknown_experiment_is_404(app):
    r = await _req(app, "DELETE", "/experiments/nope")
    assert r.status_code == 404


async def test_bad_definition_is_400_with_actionable_detail(app, case_id):
    r = await _req(app, "POST", "/experiments",
                   json={"case_ids": [case_id],
                         "steps": [{"server": "gurobi", "tool": "t"}]})
    assert r.status_code == 400
    assert "gurobi" in r.json()["detail"]


async def test_cross_server_steps_is_400(app, case_id):
    """★ 跨 server 的步骤必须在**登记期**被拒（一次实验只在一个 server 会话内跑）。"""
    r = await _req(app, "POST", "/experiments", json=_payload(
        case_id,
        steps=[{"server": "surge", "tool": "load_network"},
               {"server": "pandapower", "tool": "run_power_flow"}],
    ))
    assert r.status_code == 400
    assert "同一个 server" in r.json()["detail"]
    assert (await _req(app, "GET", "/experiments")).json()["summary"]["total"] == 0


async def test_multi_step_cell_carries_rendered_sequence(app, case_id):
    """★ 有状态序列的表达力：一格渲染出**全部步骤**且顺序正确。"""
    r = await _req(app, "POST", "/experiments", json=_payload(
        case_id,
        factors=[],
        steps=[
            {"server": "surge", "tool": "load_network",
             "args_template": {"file_path": "{case_path}"}},
            {"server": "surge", "tool": "run_n1_branch_contingency"},
        ],
    ))
    assert r.status_code == 201, r.text
    cells = r.json()["cells"]
    assert len(cells) == 1
    assert [s["tool"] for s in cells[0]["steps"]] == [
        "load_network", "run_n1_branch_contingency",
    ]
    assert cells[0]["steps"][0]["args"]["file_path"].endswith("case39.m")


async def test_unrenderable_template_is_400_before_persisting(app, case_id):
    r = await _req(app, "POST", "/experiments", json=_payload(
        case_id,
        steps=[{"server": "surge", "tool": "t", "args_template": {"x": "{nope}"}}],
    ))
    assert r.status_code == 400 and "nope" in r.json()["detail"]
    assert (await _req(app, "GET", "/experiments")).json()["summary"]["total"] == 0


async def test_case_outside_roots_is_409(app, tmp_path, case_id, monkeypatch):
    """算例存在但不在围笼内 → 409（可修复），**不是** 400。"""
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(tmp_path / "elsewhere"))
    r = await _req(app, "POST", "/experiments", json=_payload(case_id))
    assert r.status_code == 409
    assert "ALLOWED_ROOTS" in r.json()["detail"]


async def test_grid_over_limit_is_400(app, case_id):
    r = await _req(app, "POST", "/experiments", json=_payload(
        case_id,
        factors=[{"name": "lv", "values": list(range(2001))}],
    ))
    assert r.status_code == 400
    assert "2001" in r.json()["detail"]


async def test_corrupt_index_is_500(app, tmp_path):
    root = tmp_path / "exp"
    root.mkdir(parents=True, exist_ok=True)
    (root / "experiments.json").write_text("{bad", encoding="utf-8")
    r = await _req(app, "GET", "/experiments")
    assert r.status_code == 500


async def test_config_failure_is_503(monkeypatch, tmp_path):
    """配置失败必须显式映射 503，而不是退化成一个通用 500。"""
    import powermcp_gateway.api as api_mod

    def boom():
        raise RuntimeError("配置不可用")

    monkeypatch.setattr(api_mod, "_cfg", boom)
    app = api_mod.create_app()
    r = await _req(app, "GET", "/experiments")
    assert r.status_code == 503


async def test_cells_are_recomputed_not_snapshotted(app, case_id, tmp_path):
    """★ 改了算例文件 → 同一格必须算出**新的** cache_key（旧结果即为陈旧）。"""
    created = (await _req(app, "POST", "/experiments", json=_payload(case_id))).json()
    first = created["cells"][0]["cache_key"]

    f = tmp_path / "data" / "case39.m"
    f.write_bytes(b"MPC\nchanged\n")

    eid = created["experiment"]["id"]
    after = (await _req(app, "GET", f"/experiments/{eid}")).json()
    assert after["cells"][0]["cache_key"] != first
    assert after["cells"][0]["case_sha256"] != created["cells"][0]["case_sha256"]


async def test_unused_factor_warns_about_duplicate_cells(app, case_id):
    """★ 真实网关 e2e 暴露的陷阱：因子没被模板引用 ⇒ 各格 cache_key 相同（重复格）。

    不报的话，"2 格都成功"看起来正常，实际只有一种实验条件被跑过。
    """
    r = await _req(app, "POST", "/experiments", json=_payload(
        case_id,
        factors=[{"name": "lv", "values": [1.0, 1.1]}],
        steps=[{"server": "surge", "tool": "t"}],       # 模板里没有 {lv}
    ))
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["cells"]) == 2
    assert len({c["cache_key"] for c in body["cells"]}) == 1     # 正是要警告的情形
    assert any("未被任何步骤" in n for n in body["notes"])


async def test_used_factor_has_no_duplicate_warning(app, case_id):
    r = await _req(app, "POST", "/experiments", json=_payload(
        case_id,
        factors=[{"name": "lv", "values": [1.0, 1.1]}],
        steps=[{"server": "surge", "tool": "t", "args_template": {"scale": "{lv}"}}],
    ))
    assert r.status_code == 201
    body = r.json()
    assert len({c["cache_key"] for c in body["cells"]}) == 2
    assert not any("未被任何步骤" in n for n in body["notes"])


# ---------------------------------------------------------------- 执行（P2-①b）


_TWO_STEPS = [
    {"server": "surge", "tool": "load_network",
     "args_template": {"file_path": "{case_path}"}},
    {"server": "surge", "tool": "run_n1_branch_contingency"},
]


@pytest.fixture
def stubs(monkeypatch):
    """打桩「工具清单」与「工具调用」—— 不真实拉起 server。返回调用记录。"""
    import powermcp_gateway.api as api_mod
    from powermcp_gateway.inventory import ToolInventory, ToolRecord
    from powermcp_gateway.proxy import CallOutcome

    def rec(name: str, schema: dict) -> ToolRecord:
        return ToolRecord(server="surge", name=name, description=None,
                          input_schema=schema, output_schema=None)

    async def fake_inventory(c, servers, timeout_s=None, *, sid=None, pool=None):
        return ToolInventory(
            tools=(
                rec("load_network", {"type": "object",
                                     "properties": {"file_path": {"type": "string"}}}),
                rec("run_n1_branch_contingency", {"type": "object", "properties": {}}),
            ),
            failures=(), requested=tuple(servers),
        )

    calls: list[tuple] = []

    async def fake_call(sid, server, tool, args, *, get_schema):
        calls.append((sid, server, tool, args))
        return CallOutcome(
            ok=True, server=server, tool=tool,
            result={"is_error": False, "content": [
                {"type": "text", "text": json.dumps({"status": "success", "n_contingencies": 3})},
            ]},
        )

    monkeypatch.setattr(api_mod, "build_inventory", fake_inventory)
    monkeypatch.setattr(api_mod, "call_with_contracts", fake_call)
    return calls


@pytest.fixture
def pool_app(cfg, roots, stubs):
    """会话池**已开启**的 app（多步实验的前提）。"""
    import powermcp_gateway.api as api_mod

    prev = api_mod._POOL
    try:
        yield api_mod.create_app(cfg=cfg, pool=object()), stubs
    finally:
        api_mod._POOL = prev


async def _create(app, case_id, *, steps, factors=None, **kw):
    r = await _req(app, "POST", "/experiments",
                   json=_payload(case_id, factors=factors if factors is not None else [],
                                 steps=steps, **kw))
    assert r.status_code == 201, r.text
    return r.json()["experiment"]["id"]


async def test_run_route_registered(app):
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/experiments/{eid}/run" in paths


async def test_run_multi_step_ok_and_same_session_within_cell(pool_app, case_id):
    app, calls = pool_app
    eid = await _create(app, case_id, steps=_TWO_STEPS)

    r = await _req(app, "POST", f"/experiments/{eid}/run")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["ok"] == 1 and body["summary"]["failed"] == 0
    cell = body["cells"][0]
    assert cell["status"] == "ok"
    assert [s["tool"] for s in cell["steps"]] == [
        "load_network", "run_n1_branch_contingency",
    ]
    # ★ 两步落在**同一会话**（有状态序列的前提）
    assert calls[0][0] == calls[1][0]
    # 模板渲染成真实绝对路径
    assert calls[0][3]["file_path"].endswith("case39.m")
    # 结果摘要随记录落盘（供 ①c 结果表用）
    assert cell["steps"][1]["result_excerpt"]["inner"]["n_contingencies"] == 3


async def test_run_uses_distinct_session_per_cell(pool_app, case_id):
    """★ 一格一个会话 —— 跨格复用会让某格跑在上一格残留的网络上（结果张冠李戴）。"""
    app, calls = pool_app
    eid = await _create(app, case_id, steps=[_TWO_STEPS[0]],
                        factors=[{"name": "lv", "values": [1.0, 1.1]}])   # 2 格

    r = await _req(app, "POST", f"/experiments/{eid}/run")
    assert r.status_code == 200
    assert r.json()["summary"]["cells"] == 2
    sids = [c[0] for c in calls]
    assert len(sids) == 2
    assert len(set(sids)) == 2                     # 两格 → 两个会话


async def test_run_persists_results_by_cache_key(pool_app, case_id, tmp_path):
    app, _ = pool_app
    eid = await _create(app, case_id, steps=_TWO_STEPS)
    created = (await _req(app, "GET", f"/experiments/{eid}")).json()
    key = created["cells"][0]["cache_key"]

    await _req(app, "POST", f"/experiments/{eid}/run")

    import json as _json
    results = _json.loads((tmp_path / "exp" / eid / "results.json").read_text(encoding="utf-8"))
    assert results[key]["status"] == "ok"


async def test_run_multi_step_without_pool_is_503(app, case_id, stubs):
    """★ 多步实验**没有会话池**时必须显式 503 —— 绝不静默降级成"每步各起一个进程"。

    那会产出"跑成功但没加载网络"的假结果（本项目最防的形态）。
    """
    eid = await _create(app, case_id, steps=_TWO_STEPS)
    r = await _req(app, "POST", f"/experiments/{eid}/run")
    assert r.status_code == 503
    assert "SESSION_POOL" in r.json()["detail"]
    assert stubs == []                       # 一步都没发出去


async def test_run_single_step_without_pool_is_ok(app, case_id, stubs):
    """单步不需要引擎状态，故**不要求**会话池。"""
    eid = await _create(app, case_id, steps=[_TWO_STEPS[0]])
    r = await _req(app, "POST", f"/experiments/{eid}/run")
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["ok"] == 1


async def test_run_legacy_experiment_without_steps_is_409(pool_app, case_id, tmp_path):
    """★ 空步骤序列必须**拒跑** —— 否则 `execute_cells` 的步骤循环不跑，格子会得到
    `status="ok"` 且 0 步，即「跑了 0 步却说成功」的**假绿灯**。

    场景：①a 时期的旧格式记录（只有 `server`/`tool`/`args_template`，没有 `steps`）。
    """
    import json as _json

    app, _ = pool_app
    idx = tmp_path / "exp" / "experiments.json"
    idx.parent.mkdir(parents=True, exist_ok=True)
    idx.write_text(_json.dumps([{
        "id": "legacy000001", "label": "旧格式实验", "created_at": "t",
        "case_ids": [case_id], "factors": [],
        "server": "surge", "tool": "run_ac_power_flow",
        "args_template": {"file_path": "{case_path}"},
    }]), encoding="utf-8")

    r = await _req(app, "POST", "/experiments/legacy000001/run")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "没有步骤" in detail and "steps" in detail


async def test_run_unknown_experiment_is_404(pool_app):
    app, _ = pool_app
    r = await _req(app, "POST", "/experiments/nope/run")
    assert r.status_code == 404


async def test_run_while_running_is_409(pool_app, case_id):
    """★ 同一实验不并发执行（结果按 cache_key 落盘，并发会互相覆盖）。"""
    import powermcp_gateway.api as api_mod

    app, _ = pool_app
    eid = await _create(app, case_id, steps=[_TWO_STEPS[0]])
    api_mod._RUNNING.add(eid)
    try:
        r = await _req(app, "POST", f"/experiments/{eid}/run")
        assert r.status_code == 409
        assert "正在执行" in r.json()["detail"]
    finally:
        api_mod._RUNNING.discard(eid)


async def test_concurrent_runs_one_wins_one_409(pool_app, case_id, monkeypatch):
    """★ §11.2 实测的竞态：`_RUNNING` 占位必须在**首个 await 之前**。

    原先的顺序是「检查 → await 取清单 → add」—— 两个并发请求会**都通过检查**
    （此时谁都还没 add），防护形同虚设。本测试用**真并发**钉住它。
    """
    import asyncio

    import powermcp_gateway.api as api_mod
    from powermcp_gateway.proxy import CallOutcome

    app, _ = pool_app
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_call(sid, server, tool, args, *, get_schema):
        started.set()
        await release.wait()
        return CallOutcome(ok=True, server=server, tool=tool, result={"content": []})

    monkeypatch.setattr(api_mod, "call_with_contracts", slow_call)
    eid = await _create(app, case_id, steps=[_TWO_STEPS[0]])

    async def one() -> int:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            return (await c.post(f"/experiments/{eid}/run")).status_code

    first = asyncio.create_task(one())
    await asyncio.wait_for(started.wait(), timeout=5)   # 第一个已进入执行
    second = asyncio.create_task(one())
    await asyncio.sleep(0.2)                            # 让第二个去撞占位
    release.set()
    codes = sorted([await first, await second])
    assert codes == [200, 409], f"并发 run 未被拒绝（防护失效）：{codes}"


async def test_health_exposes_lease_stats(app):
    """★ 并发隔离必须**可观测**（§11.2）：没有这个面，"有没有在排队"只能靠猜。"""
    r = await _req(app, "GET", "/health")
    assert r.status_code == 200
    leases = r.json()["leases"]
    assert leases["scope"] == "process-local"
    assert {"acquired", "waited", "timed_out", "contended_keys"} <= set(leases)
    assert leases["active"] == 0


async def test_run_failed_step_is_visible_per_cell(pool_app, case_id, monkeypatch):
    """★ UI 规范 §4.7.5：失败必须**逐格可见**，不得只给总进度条。"""
    import powermcp_gateway.api as api_mod
    from powermcp_gateway.proxy import CallOutcome

    app, _ = pool_app

    async def failing_call(sid, server, tool, args, *, get_schema):
        if tool == "run_n1_branch_contingency":
            return CallOutcome(ok=False, server=server, tool=tool,
                               error="引擎：solver diverged")
        return CallOutcome(ok=True, server=server, tool=tool, result={"content": []})

    monkeypatch.setattr(api_mod, "call_with_contracts", failing_call)
    eid = await _create(app, case_id, steps=_TWO_STEPS)

    body = (await _req(app, "POST", f"/experiments/{eid}/run")).json()
    assert body["summary"]["failed"] == 1
    cell = body["cells"][0]
    assert cell["status"] == "failed"
    assert cell["steps"][1]["ok"] is False
    assert "solver diverged" in cell["steps"][1]["error"]


# ---------------------------------------------------------------- 结果表 / 导出（P2-①c）


async def test_results_and_export_routes_registered(app):
    paths = {getattr(r, "path", "") for r in app.routes}
    assert {"/experiments/{eid}/results", "/experiments/{eid}/export"} <= paths


async def test_results_before_run_is_never_run(app, case_id):
    """未执行过的格子必须是 `never_run` —— 不得冒充 `pending`/`ok`。"""
    eid = await _create(app, case_id, steps=[_TWO_STEPS[0]])
    body = (await _req(app, "GET", f"/experiments/{eid}/results")).json()
    assert [r["status"] for r in body["rows"]] == ["never_run"]
    assert body["summary"]["by_status"] == {"never_run": 1}
    assert body["summary"]["orphaned"] == 0


async def test_results_after_run_carries_metrics(pool_app, case_id):
    app, _ = pool_app
    eid = await _create(app, case_id, steps=_TWO_STEPS)
    await _req(app, "POST", f"/experiments/{eid}/run")

    body = (await _req(app, "GET", f"/experiments/{eid}/results")).json()
    assert body["rows"][0]["status"] == "ok"
    # 打桩结果 {"status":"success","n_contingencies":3} → 扁平化后可直接比较
    assert body["rows"][0]["metrics"]["metric.n_contingencies"] == 3
    assert {c["key"] for c in body["columns"]} >= {
        "index", "case_id", "status", "metric.n_contingencies",
    }


async def test_results_unknown_is_404(pool_app):
    app, _ = pool_app
    assert (await _req(app, "GET", "/experiments/nope/results")).status_code == 404


async def test_export_csv_and_markdown(pool_app, case_id):
    app, _ = pool_app
    eid = await _create(app, case_id, steps=_TWO_STEPS)
    await _req(app, "POST", f"/experiments/{eid}/run")

    csv_r = await _req(app, "GET", f"/experiments/{eid}/export?format=csv")
    assert csv_r.status_code == 200, csv_r.text
    assert csv_r.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv_r.headers["content-disposition"]
    assert csv_r.text.splitlines()[0].startswith("index,case_id,status,ran_at,cache_key")
    assert len(csv_r.text.strip().splitlines()) == 2          # 表头 + 1 格

    md_r = await _req(app, "GET", f"/experiments/{eid}/export?format=md")
    assert md_r.status_code == 200
    assert md_r.headers["content-type"].startswith("text/markdown")
    assert md_r.text.startswith("| index | case_id |")


async def test_export_default_format_is_csv(pool_app, case_id):
    app, _ = pool_app
    eid = await _create(app, case_id, steps=[_TWO_STEPS[0]])
    r = await _req(app, "GET", f"/experiments/{eid}/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")


async def test_export_unknown_format_is_400(pool_app, case_id):
    app, _ = pool_app
    eid = await _create(app, case_id, steps=[_TWO_STEPS[0]])
    r = await _req(app, "GET", f"/experiments/{eid}/export?format=pdf")
    assert r.status_code == 400
    assert "pdf" in r.json()["detail"]
