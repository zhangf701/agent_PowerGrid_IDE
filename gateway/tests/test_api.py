import pytest
from httpx import ASGITransport, AsyncClient

from powermcp_gateway.api import create_app


@pytest.fixture
def app():
    return create_app()


async def test_health(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # ★ 审计持久化降级的观测面（C-2）：不是全等断言 —— /health 允许附加诊断字段，
    #   否则每加一个观测面都要改一次测试（那会把"响应体形状"变成事实上的契约）。
    assert "audit" in body
    assert "append_failures" in body["audit"]


async def test_servers_lists_open_source_nine(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/servers")
    assert r.status_code == 200
    servers = r.json()["servers"]
    assert "pandapower" in servers
    assert all(s == s.lower() for s in servers)
    # 商业引擎必须不在其中（方案 v3 已移除）
    for closed in ("powerworld", "psse", "pslf", "powerfactory", "pscad", "ltspice", "plexosdb"):
        assert closed not in servers
