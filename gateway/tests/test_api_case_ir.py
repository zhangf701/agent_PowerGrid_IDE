"""算例解析端点（`/cases/{id}/parse` · `/ir` · `/diagnostics`）的测试。

★ 单元层：monkeypatch `build_inventory` 与 `proxy._dispatch` —— **不拉起任何 server**。
★ 集成层（`-m integration` 才跑）：真实拉起 powerio，验证「parse → IR → diagnostics」往返。
  默认套件用 `-m "not integration"` 排除，故不会拖慢日常回归。
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

import powermcp_gateway.api as api_mod
import powermcp_gateway.case_ir as case_ir_mod
import powermcp_gateway.proxy as proxy_mod
from powermcp_gateway.api import create_app
from powermcp_gateway.config import ConfigError, GatewayConfig
from powermcp_gateway.inventory import ServerFailure, ToolInventory, ToolRecord

IR_TEXT = '{"schema": "pio-ir", "version": 2, "selection": {}}'

_PARSE_SCHEMA = {
    "type": "object",
    "properties": {"path": {"type": "string"}, "content": {"type": "string"},
                   "format": {"type": "string"}},
}
_DIAG_SCHEMA = {
    "type": "object",
    "properties": {"powerio_ir": {"type": "string"}},
    "required": ["powerio_ir"],
}


@pytest.fixture
def cfg():
    return GatewayConfig.discover()


@pytest.fixture
def cases_env(tmp_path, monkeypatch):
    root = tmp_path / "cases"
    monkeypatch.setenv("POWERMCP_GATEWAY_CASES_ROOT", str(root))
    return root


@pytest.fixture
def case_file(tmp_path):
    p = tmp_path / "data" / "case39.m"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"MPC\n")
    return p


@pytest.fixture
def app(cfg, cases_env):
    return create_app(cfg=cfg)


def _patch_dispatch(monkeypatch, handler):
    monkeypatch.setattr(proxy_mod, "_dispatch", handler)


def _ok_parse(ir_text: str = IR_TEXT):
    async def handler(cfg, server, tool, args):
        payload = {"value_type": "powerio.BalancedNetwork", "powerio_ir": ir_text}
        return {"is_error": False,
                "content": [{"type": "text", "text": json.dumps(payload)}]}
    return handler


def _ok_diag():
    async def handler(cfg, server, tool, args):
        payload = {"diagnostics": [{"severity": "info", "code": "X"}],
                   "summary": {"buses": 39}, "value_type": "powerio.BalancedNetwork"}
        return {"is_error": False,
                "content": [{"type": "text", "text": json.dumps(payload)}]}
    return handler


async def _req(app, method, path, **kw):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.request(method, path, **kw)


async def _register(app, case_file, **extra):
    body = {"path": str(case_file), **extra}
    r = await _req(app, "POST", "/cases", json=body)
    assert r.status_code == 201, r.text
    return r.json()["case"]["id"]


def _patch_all(monkeypatch, tools=None, dispatch=None):
    """同时打两处 `build_inventory`。

    ⚠️ **必须打在使用它的模块命名空间里**：`case_ir` 是 `from .inventory import build_inventory`，
      所以只打 `api_mod.build_inventory` **不会**影响 `case_ir._call_powerio` ——
      结果是"单元测试"其实在**真实拉起 powerio**（实测：全套从 1s 变成 36s，且依赖环境）。
    """
    async def fake_inv(cfg, servers):
        return ToolInventory(
            tools=tuple(ToolRecord("powerio", n, f"{n} 描述", s, None)
                        for n, s in (tools or [("parse", _PARSE_SCHEMA),
                                               ("diagnostics", _DIAG_SCHEMA)])),
            failures=(), requested=tuple(servers),
        )

    monkeypatch.setattr(api_mod, "build_inventory", fake_inv)
    monkeypatch.setattr(case_ir_mod, "build_inventory", fake_inv)
    _patch_dispatch(monkeypatch, dispatch or _ok_parse())


# ---------------------------------------------------------------- 路由


async def test_routes_registered(app):
    paths = {getattr(r, "path", "") for r in app.routes}
    assert {"/cases/{cid}/parse", "/cases/{cid}/ir", "/cases/{cid}/diagnostics"} <= paths


# ---------------------------------------------------------------- 前置条件


async def test_parse_unknown_case_is_404(app, monkeypatch):
    _patch_all(monkeypatch)
    assert (await _req(app, "POST", "/cases/nope/parse")).status_code == 404


async def test_parse_missing_file_is_409(app, case_file, monkeypatch):
    _patch_all(monkeypatch)
    cid = await _register(app, case_file)
    case_file.unlink()
    r = await _req(app, "POST", f"/cases/{cid}/parse")
    assert r.status_code == 409
    assert "不存在" in r.json()["detail"]


async def test_parse_outside_allowed_roots_is_409_with_actionable_hint(
        app, case_file, monkeypatch):
    """★ 前置条件必须给出**可执行指引**，而不是让 server 报看不懂的沙箱错误。"""
    _patch_all(monkeypatch)
    monkeypatch.delenv("POWERIO_MCP_ALLOWED_ROOTS", raising=False)
    cid = await _register(app, case_file)

    r = await _req(app, "POST", f"/cases/{cid}/parse")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "POWERIO_MCP_ALLOWED_ROOTS" in detail
    assert str(case_file.parent) in detail, "必须指出该把哪个目录加进去"


# ---------------------------------------------------------------- parse


async def test_parse_succeeds_and_writes_artifact(app, cfg, cases_env, case_file, monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(case_file.parent))
    cid = await _register(app, case_file)

    r = await _req(app, "POST", f"/cases/{cid}/parse")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["value_type"] == "powerio.BalancedNetwork"
    assert body["has_ir"] is True
    assert body["tool"] == "powerio.parse"
    assert body["ir_bytes"] == len(IR_TEXT.encode("utf-8"))

    assert "ir" not in body, "parse 响应不得内联 IR（约 60KB）—— 应走 GET /ir"
    assert (cases_env / cid / "parse.json").is_file()


async def test_parse_reports_502_when_powerio_errors(app, case_file, monkeypatch):
    """★ 引擎失败必须**原样上报**，不得被后续的字段校验掩盖成另一个错误。

    （若把 `if not outcome.ok: raise` 去掉，`is_error=True` 的正文会被当成正常返回继续解析，
      最后以「缺少 powerio_ir」报出来 —— 上报的是**错的原因**。故此处用**合法 JSON** 的
      错误正文，让两条路径的错误信息可区分。）
    """
    async def failing(cfg, server, tool, args):
        return {"is_error": True,
                "content": [{"type": "text",
                             "text": json.dumps({"error": "PathNotAllowed"})}]}

    _patch_all(monkeypatch, dispatch=failing)
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(case_file.parent))
    cid = await _register(app, case_file)

    r = await _req(app, "POST", f"/cases/{cid}/parse")
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "PathNotAllowed" in detail
    assert "powerio_ir" not in detail, "引擎失败被字段校验掩盖了 —— 上报的原因不对"


async def test_parse_reports_502_when_powerio_not_mounted(app, case_file, monkeypatch):
    async def empty_inv(cfg, servers):
        return ToolInventory(tools=(), failures=(ServerFailure("powerio", "握手超时"),),
                             requested=tuple(servers))

    monkeypatch.setattr(case_ir_mod, "build_inventory", empty_inv)
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(case_file.parent))
    cid = await _register(app, case_file)

    r = await _req(app, "POST", f"/cases/{cid}/parse")
    assert r.status_code == 502
    assert "未拉起" in r.json()["detail"] or "不存在" in r.json()["detail"]
    assert "握手超时" in r.json()["detail"], "应带上上游失败原因，便于诊断"


async def test_parse_reports_502_when_powerio_ir_missing(app, case_file, monkeypatch):
    """★ 双层编码是 PowerIO 的**实际形态**；缺了 `powerio_ir` 说明上游变了 —— 必须响亮。"""
    async def no_ir(cfg, server, tool, args):
        return {"is_error": False,
                "content": [{"type": "text", "text": json.dumps({"value_type": "x"})}]}

    _patch_all(monkeypatch, dispatch=no_ir)
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(case_file.parent))
    cid = await _register(app, case_file)

    r = await _req(app, "POST", f"/cases/{cid}/parse")
    assert r.status_code == 502
    assert "powerio_ir" in r.json()["detail"]


async def test_parse_reports_502_on_non_json_output(app, case_file, monkeypatch):
    async def garbage(cfg, server, tool, args):
        return {"is_error": False, "content": [{"type": "text", "text": "不是 JSON"}]}

    _patch_all(monkeypatch, dispatch=garbage)
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(case_file.parent))
    cid = await _register(app, case_file)

    r = await _req(app, "POST", f"/cases/{cid}/parse")
    assert r.status_code == 502
    assert "不是合法 JSON" in r.json()["detail"]


async def test_parse_reports_502_when_output_is_not_an_object(app, case_file, monkeypatch):
    """★ 与上一条是**两条不同的守卫**：这里是**合法 JSON 但不是对象**（如 `[1, 2]`）。

    两者都必须 502 —— 否则一个数组会被当成"解析成功"继续往下走，
    最后以莫名其妙的字段缺失报错（甚至 AttributeError）。
    """
    async def array_output(cfg, server, tool, args):
        return {"is_error": False, "content": [{"type": "text", "text": "[1, 2]"}]}

    _patch_all(monkeypatch, dispatch=array_output)
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(case_file.parent))
    cid = await _register(app, case_file)

    r = await _req(app, "POST", f"/cases/{cid}/parse")
    assert r.status_code == 502
    assert "不是 JSON 对象" in r.json()["detail"]


# ---------------------------------------------------------------- GET /ir


async def test_ir_404_for_unknown_case(app, monkeypatch):
    _patch_all(monkeypatch)
    assert (await _req(app, "GET", "/cases/nope/ir")).status_code == 404


async def test_ir_409_before_parse(app, case_file, monkeypatch):
    _patch_all(monkeypatch)
    cid = await _register(app, case_file)
    r = await _req(app, "GET", f"/cases/{cid}/ir")
    assert r.status_code == 409
    assert "尚未解析" in r.json()["detail"]


async def test_ir_returns_parsed_object(app, case_file, monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(case_file.parent))
    cid = await _register(app, case_file)
    await _req(app, "POST", f"/cases/{cid}/parse")

    body = (await _req(app, "GET", f"/cases/{cid}/ir")).json()
    assert body["ir_parsed"] is True
    assert body["ir"]["schema"] == "pio-ir"
    assert body["value_type"] == "powerio.BalancedNetwork"


async def test_ir_falls_back_to_raw_when_unparsable(app, case_file, monkeypatch):
    """解析不了就**原样给**并标 `ir_parsed=false` —— 不假装成功。"""
    _patch_all(monkeypatch, dispatch=_ok_parse(ir_text="不是 JSON 的 IR"))
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(case_file.parent))
    cid = await _register(app, case_file)
    await _req(app, "POST", f"/cases/{cid}/parse")

    body = (await _req(app, "GET", f"/cases/{cid}/ir")).json()
    assert body["ir_parsed"] is False
    assert body["ir"] == "不是 JSON 的 IR"


# ---------------------------------------------------------------- diagnostics


async def test_diagnostics_409_before_parse(app, case_file, monkeypatch):
    _patch_all(monkeypatch)
    cid = await _register(app, case_file)
    r = await _req(app, "GET", f"/cases/{cid}/diagnostics")
    assert r.status_code == 409


async def test_diagnostics_returns_result(app, case_file, monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(case_file.parent))
    cid = await _register(app, case_file)
    await _req(app, "POST", f"/cases/{cid}/parse")

    calls: list[dict] = []

    async def diag(cfg, server, tool, args):
        calls.append(args)
        return await _ok_diag()(cfg, server, tool, args)

    _patch_dispatch(monkeypatch, diag)

    body = (await _req(app, "GET", f"/cases/{cid}/diagnostics")).json()
    assert body["stale"] is False
    assert body["result"]["summary"] == {"buses": 39}
    assert calls[0]["powerio_ir"] == IR_TEXT, "必须把产物里的 IR **原样**传回去"


async def test_diagnostics_flags_stale_when_source_changed(app, case_file, monkeypatch):
    """★ 陈旧必须**现算**：产物记的是解析时的哈希，源文件改了就该报。"""
    _patch_all(monkeypatch)
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(case_file.parent))
    cid = await _register(app, case_file)
    await _req(app, "POST", f"/cases/{cid}/parse")

    case_file.write_bytes(b"MPC CHANGED\n")
    _patch_dispatch(monkeypatch, _ok_diag())

    body = (await _req(app, "GET", f"/cases/{cid}/diagnostics")).json()
    assert body["stale"] is True


async def test_diagnostics_502_when_engine_fails(app, case_file, monkeypatch):
    _patch_all(monkeypatch)
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(case_file.parent))
    cid = await _register(app, case_file)
    await _req(app, "POST", f"/cases/{cid}/parse")

    async def failing(cfg, server, tool, args):
        return {"is_error": True,
                "content": [{"type": "text", "text": json.dumps({"error": "solver diverged"})}]}

    _patch_dispatch(monkeypatch, failing)
    r = await _req(app, "GET", f"/cases/{cid}/diagnostics")
    assert r.status_code == 502
    assert "solver diverged" in r.json()["detail"]


# ---------------------------------------------------------------- 配置失败


async def test_parse_is_503_when_config_unresolvable(app, monkeypatch):
    def boom():
        raise ConfigError("未找到 PowerMCP 仓库根")

    monkeypatch.setattr(api_mod, "_cfg", boom)
    assert (await _req(app, "POST", "/cases/x/parse")).status_code == 503
    assert (await _req(app, "GET", "/cases/x/ir")).status_code == 503
    assert (await _req(app, "GET", "/cases/x/diagnostics")).status_code == 503


# ---------------------------------------------------------------- 集成（真实拉起 server）


@pytest.mark.integration
async def test_live_parse_roundtrip(cfg, tmp_path, monkeypatch):
    """真实拉起 powerio：parse → IR → diagnostics 往返。

    只有 `-m integration` 才跑。需要 `examples/data/case39.m` 在场。
    """
    case_src = cfg.powermcp_root.parent / "examples" / "data" / "case39.m"
    if not case_src.is_file():
        pytest.skip(f"算例不在场：{case_src}")

    monkeypatch.setenv("POWERMCP_GATEWAY_CASES_ROOT", str(tmp_path / "cases"))
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(case_src.parent))
    live = create_app(cfg=cfg)

    cid = await _register(live, case_src)
    r = await _req(live, "POST", f"/cases/{cid}/parse")
    assert r.status_code == 200, r.text
    assert r.json()["value_type"] == "powerio.BalancedNetwork"

    ir_body = (await _req(live, "GET", f"/cases/{cid}/ir")).json()
    assert ir_body["ir_parsed"] is True
    assert ir_body["ir"]["schema"] == "pio-ir"

    d = await _req(live, "GET", f"/cases/{cid}/diagnostics")
    assert d.status_code == 200, d.text
    assert d.json()["stale"] is False
    assert "diagnostics" in d.json()["result"]
