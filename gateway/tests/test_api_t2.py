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
