"""`POST /checks/run` 端点测试（G-4 最小闭环：checks 从"声明了"变成"能跑"）。

★ 错误映射沿用项目惯例：400 请求体非法 / 404 模块不存在或装配失败 /
  409 模块已禁用 / 503 配置失败 —— **不靠匹配错误文本**区分。
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from powermcp_gateway.api import create_app
from powermcp_gateway.config import GatewayConfig
from powermcp_gateway.modules import ENV_MODULES_ROOT

_OK_CHECK = (
    'RULE_ID = "demo-rule"\n'
    'SEVERITY = "warning"\n'
    "def check(ctx):\n"
    "    return [f\"第 {i} 行有问题\" for i, r in enumerate(ctx.rows) if r.get('bad')]\n"
)

_MANIFEST = """\
id: demo
name: 演示模块
version: 0.1.0
kind: research
maturity: L1
enabled: {enabled}
result_tables:
  - id: rt1
    columns: ./schema/cols.json
checks:
  - id: c_ok
    file: ./checks/ok_check.py
    result_table: rt1
"""


@pytest.fixture
def cfg():
    return GatewayConfig.discover()


@pytest.fixture
def modules_env(tmp_path, monkeypatch):
    root = tmp_path / "modules"
    monkeypatch.setenv(ENV_MODULES_ROOT, str(root))
    return root


@pytest.fixture
def app(cfg, modules_env):
    return create_app(cfg=cfg)


def _write_module(root, *, enabled: bool = True) -> None:
    d = root / "demo"
    (d / "schema").mkdir(parents=True)
    (d / "schema" / "cols.json").write_text("[]", encoding="utf-8")
    (d / "checks").mkdir(parents=True)
    (d / "checks" / "ok_check.py").write_text(_OK_CHECK, encoding="utf-8")
    (d / "module.yaml").write_text(
        _MANIFEST.format(enabled=str(enabled).lower()), encoding="utf-8",
    )


async def _post(app, payload):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.post("/checks/run", json=payload)


async def test_route_registered(app):
    assert "/checks/run" in {getattr(r, "path", "") for r in app.routes}


async def test_happy_path_returns_findings(app, modules_env):
    _write_module(modules_env)
    r = await _post(app, {"module_id": "demo",
                          "rows": {"rt1": [{"bad": True}, {"bad": False}]}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["by_severity"]["warning"] == 1
    assert body["results"][0]["findings"][0]["rule_id"] == "demo-rule"
    assert body["results"][0]["findings"][0]["result_table"] == "rt1"


async def test_400_when_module_id_missing(app):
    r = await _post(app, {"rows": {}})
    assert r.status_code == 400
    assert "module_id" in r.json()["detail"]


async def test_400_when_rows_shape_is_wrong(app):
    r = await _post(app, {"module_id": "demo", "rows": {"rt1": "不是数组"}})
    assert r.status_code == 400
    assert "rows" in r.json()["detail"]


async def test_400_when_case_is_not_object(app):
    r = await _post(app, {"module_id": "demo", "rows": {}, "case": 42})
    assert r.status_code == 400


async def test_404_unknown_module(app, modules_env):
    r = await _post(app, {"module_id": "ghost", "rows": {}})
    assert r.status_code == 404


async def test_409_disabled_module(app, modules_env):
    _write_module(modules_env, enabled=False)
    r = await _post(app, {"module_id": "demo", "rows": {"rt1": []}})
    assert r.status_code == 409
    assert "禁用" in r.json()["detail"]


async def test_case_reaches_the_check_ctx(app, modules_env):
    """`case` / `case_id` 原样进 ctx —— check 能做算例级判定（契约里有就真给）。"""
    d = modules_env / "demo"
    (d / "schema").mkdir(parents=True)
    (d / "schema" / "cols.json").write_text("[]", encoding="utf-8")
    (d / "checks").mkdir(parents=True)
    (d / "checks" / "ok_check.py").write_text(
        'RULE_ID = "case-aware"\nSEVERITY = "info"\n'
        "def check(ctx):\n"
        "    if ctx.case_id is None:\n"
        "        return []\n"
        "    return [{'message': f\"算例 {ctx.case_id} 共 {len(ctx.case.get('buses', []))} 母线\"}]\n",
        encoding="utf-8",
    )
    (d / "module.yaml").write_text(_MANIFEST.format(enabled="true"), encoding="utf-8")

    r = await _post(app, {"module_id": "demo", "rows": {"rt1": []},
                          "case": {"buses": [1, 2, 3]}, "case_id": "case39"})
    assert r.status_code == 200, r.text
    findings = r.json()["results"][0]["findings"]
    assert findings and "case39" in findings[0]["message"] and "3" in findings[0]["message"]
