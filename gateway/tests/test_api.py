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


# ---------------------------------------------------------------- 技能文档（09-28 裁决）


async def test_skill_doc_endpoint_serves_full_markdown(app):
    """★ 回归（2026-09-28 张老师裁决）：技能手册只有摘要不够，必须能取文档原文。

    `GET /skills/{id}/doc` 默认返回 `SKILL.md` 原文（text/markdown）；
    id 取自真实 /skills 响应（仓库自带 PowerSkills，不在场则跳过）。
    """
    from powermcp_gateway.config import GatewayConfig
    from powermcp_gateway.skills import skills_root

    if not skills_root(GatewayConfig.discover()).is_dir():
        pytest.skip("PowerSkills 不在场")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        listing = (await c.get("/skills")).json()
        skill_id = listing["skills"][0]["id"]

        r = await c.get(f"/skills/{skill_id}/doc")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/markdown")
        assert len(r.text) > len(
            next(s for s in listing["skills"] if s["id"] == skill_id)["description"]
        ), "原文必须比摘要长 —— 否则又只是摘要"

        j = await c.get(f"/skills/{skill_id}/doc", params={"format": "json"})
        assert j.status_code == 200
        body = j.json()
        assert body["id"] == skill_id
        assert body["path"].endswith("SKILL.md")
        assert body["content"] == r.text

        bad = await c.get(f"/skills/{skill_id}/doc", params={"format": "xml"})
        assert bad.status_code == 400

        missing = await c.get("/skills/不存在的技能/doc")
        assert missing.status_code == 404
