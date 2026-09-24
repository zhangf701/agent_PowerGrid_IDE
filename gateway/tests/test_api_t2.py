import pytest
from httpx import ASGITransport, AsyncClient

from powermcp_gateway.api import create_app


@pytest.fixture
def app():
    return create_app()


async def test_create_session(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/sessions", json={"servers": ["pandapower", "pypsa"]})
    assert r.status_code == 200
    body = r.json()
    assert body["id"]
    assert body["servers"] == ["pandapower", "pypsa"]


async def test_create_session_rejects_unknown_server(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/sessions", json={"servers": ["powerworld"]})
    assert r.status_code == 400        # 商业引擎已被方案 v3 移除


async def test_session_events_returns_streaming_response(app):
    """★ `ASGITransport` **无法**测无限流式响应 —— 实测会挂死。

    它会等 ASGI 应用整体结束，而 SSE 永不结束，所以
    `async with c.stream(...)` **连响应头都拿不到**。故直接调用端点函数检查返回对象。

    验证「路由已注册 + 返回 `StreamingResponse` + `media_type` 为 `text/event-stream`」。
    真实 HTTP 下的响应头与断开清理留给 Task 7 的端到端验收；流的序列化由
    `test_events.py` 的 `format_sse` 单测覆盖。
    """
    from fastapi.responses import StreamingResponse
    from starlette.requests import Request

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pypsa"]})).json()["id"]

    route = next(r for r in app.routes
                 if getattr(r, "path", None) == "/sessions/{sid}/events")
    request = Request({"type": "http", "method": "GET", "path": "/x",
                       "headers": [], "query_string": b""})
    resp = await route.endpoint(sid, request)

    assert isinstance(resp, StreamingResponse)
    assert resp.media_type == "text/event-stream"


async def test_unknown_session_events_404(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/sessions/nope/events")
    assert r.status_code == 404


async def test_call_with_valid_args_streams_tool_call_event(app, monkeypatch):
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway import api as api_mod

    async def fake_dispatch(cfg, server, tool, args):
        return {"status": "success", "content": []}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pandapower"]})).json()["id"]

    outcome = await api_mod.call_with_contracts(
        sid, "pandapower", "run_power_flow", {"net": "x"},
        get_schema=lambda s, t: {"properties": {"net": {"type": "string"}}},
    )
    assert outcome.ok is True
    assert "tool_call" in [e.kind for e in api_mod._STORE.bus(sid).events()]


async def test_contract_violation_is_reported_as_finding(app, monkeypatch):
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway import api as api_mod

    async def fake_dispatch(cfg, server, tool, args):
        return {}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pandapower"]})).json()["id"]

    outcome = await api_mod.call_with_contracts(
        sid, "pandapower", "run_power_flow",
        {"nets": "x"},                                   # ← 拼错的参数名
        get_schema=lambda s, t: {"properties": {"net": {"type": "string"}},
                                 "required": ["net"]},
    )

    assert outcome.ok is False
    viol = [e for e in api_mod._STORE.bus(sid).events() if e.kind == "contract_violation"]
    assert viol
    assert viol[0].payload["contract"] == 3


async def test_audit_file_records_the_violation(tmp_path, monkeypatch):
    """★ 契约 3 的违规必须落进 NDJSON 审计 —— 只有事件不落盘等于没法事后追。

    注入 tmp_path 的 AuditLog，避免测试往真实 ~/.powermcp/audit 里写文件。
    """
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway import api as api_mod
    from powermcp_gateway.audit import AuditLog

    async def fake_dispatch(cfg, server, tool, args):
        return {}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)
    scratch = AuditLog(tmp_path)
    monkeypatch.setattr(api_mod, "_AUDIT", scratch)

    app = api_mod.create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pandapower"]})).json()["id"]

    await api_mod.call_with_contracts(
        sid, "pandapower", "run_power_flow", {"nets": "x"},
        get_schema=lambda s, t: {"properties": {"net": {"type": "string"}}},
    )
    scratch.flush()

    kinds = [e.kind for e in scratch.replay(sid)]
    assert "contract_violation" in kinds
    assert scratch.path_for(sid).is_file()


async def test_shutdown_flushes_audit(tmp_path, monkeypatch):
    """★ 关闭时**必须** flush 审计 —— 否则缓冲区里的证据事件直接丢失。

    `AuditLog` 是批量写入（每 32 条 flush 一次）。网关没有 shutdown 钩子时，
    进程退出会让缓冲区内容丢失 —— 实测单条违规后审计文件仍是 **0 字节**。

    直接进出 lifespan，不用 `TestClient` —— 后者会在测试输出里引入
    starlette 内部的 `DeprecationWarning`，污染输出。
    """
    from powermcp_gateway import api as api_mod
    from powermcp_gateway.audit import AuditLog
    from powermcp_gateway.session import Channel, Event

    scratch = AuditLog(tmp_path)
    monkeypatch.setattr(api_mod, "_AUDIT", scratch)

    app = api_mod.create_app()

    scratch.append("s1", Event(seq=1, channel=Channel.EVIDENCE, kind="k",
                               payload={}, at="2026-09-24T00:00:00Z"))
    assert scratch.path_for("s1").stat().st_size == 0, "未 flush 前不应落盘"

    async with api_mod._lifespan(app):      # 进入 / 退出 lifespan
        pass

    assert scratch.path_for("s1").stat().st_size > 0, "shutdown 未 flush 审计"