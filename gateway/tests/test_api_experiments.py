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
async def case_id(app, tmp_path):
    f = tmp_path / "data" / "case39.m"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"MPC\n")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/cases", json={"path": str(f), "label": "IEEE 39"})
        assert r.status_code == 201, r.text
        return r.json()["case"]["id"]


async def _req(app, method: str, path: str, **kw):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.request(method, path, **kw)


def _payload(cid: str, **kw) -> dict:
    body = {
        "case_ids": [cid],
        "factors": [{"name": "load_level", "values": [1.0, 1.1]}],
        "step": {
            "server": "surge",
            "tool": "run_ac_power_flow",
            "args_template": {"file_path": "{case_path}", "scale": "{load_level}"},
        },
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
    assert all(isinstance(c["args"]["scale"], float) for c in cells)
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


async def test_bad_definition_is_400_with_actionable_detail(app, case_id):
    r = await _req(app, "POST", "/experiments",
                   json={"case_ids": [case_id],
                         "step": {"server": "gurobi", "tool": "t"}})
    assert r.status_code == 400
    assert "gurobi" in r.json()["detail"]


async def test_unrenderable_template_is_400_before_persisting(app, case_id):
    r = await _req(app, "POST", "/experiments", json=_payload(
        case_id,
        step={"server": "surge", "tool": "t", "args_template": {"x": "{nope}"}},
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
