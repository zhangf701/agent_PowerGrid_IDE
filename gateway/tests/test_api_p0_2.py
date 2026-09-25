"""P0-2a 两个只读端点的测试：`GET /environment` 与 `GET /skills`。

★ 与既有端点的一致性：配置失败 → 503（不是 500）；两者都**不需要会话**。
★ `GET /skills` 在 PowerSkills 不在场时必须返回 200 + 空清单，**不是 500** ——
  两个仓库可以分开 clone，缺一个不是服务端故障。
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

import powermcp_gateway.api as api_mod
from powermcp_gateway.api import create_app
from powermcp_gateway.config import ConfigError, GatewayConfig
from powermcp_gateway.llm import ENV_API_KEY, ENV_BASE_URL, ENV_MODEL
from powermcp_gateway.skills import ENV_SKILLS_ROOT

_SECRET = "sk-DO-NOT-LEAK-77aa11"


@pytest.fixture
def app():
    return create_app(cfg=GatewayConfig.discover())


async def _get(app, path: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path)


async def test_both_endpoints_are_registered(app):
    paths = {getattr(r, "path", "") for r in app.routes}
    assert {"/environment", "/skills"} <= paths


# ---------------------------------------------------------------- /environment


async def test_environment_ok_without_session(app):
    r = await _get(app, "/environment")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "gateway", "powermcp", "paths", "solvers", "server_env", "llm",
        "contracts", "skills", "modules", "notes",
    }
    assert body["powermcp"]["root_ok"] is True


async def test_environment_states_the_boundary_with_contracts_t0(app):
    """必须写明「挂载状态见 /contracts/t0」—— 否则前端会以为环境报告漏了 server 状态。"""
    body = (await _get(app, "/environment")).json()
    assert any("/contracts/t0" in n for n in body["notes"])


async def test_environment_never_leaks_api_key(app, monkeypatch):
    monkeypatch.setenv(ENV_BASE_URL, "https://user:pass@api.example.com/v1")
    monkeypatch.setenv(ENV_API_KEY, _SECRET)
    monkeypatch.setenv(ENV_MODEL, "m")
    r = await _get(app, "/environment")
    assert r.status_code == 200
    assert _SECRET not in r.text
    assert "user:pass" not in r.text
    assert r.json()["llm"]["api_key_set"] is True


async def test_environment_is_503_when_config_unresolvable(app, monkeypatch):
    def boom():
        raise ConfigError("未找到 PowerMCP 仓库根")

    monkeypatch.setattr(api_mod, "_cfg", boom)
    r = await _get(app, "/environment")
    assert r.status_code == 503
    assert "PowerMCP" in r.json()["detail"]


# ---------------------------------------------------------------- /skills


async def test_skills_lists_real_powerskills(app):
    r = await _get(app, "/skills")
    assert r.status_code == 200
    body = r.json()
    assert body["root_exists"] is True
    assert body["summary"]["total"] == 22
    assert body["summary"]["by_kind"] == {"tool": 11, "engineering": 10, "meta": 1}
    ids = {s["id"] for s in body["skills"]}
    assert {"surge", "pandapower", "thermal-overload-mitigation", "skill-creator"} <= ids


async def test_skills_carries_escalation_triggers(app):
    """escalation triggers 是「研究方法」最直接的载体 —— 必须随索引一起给出。"""
    body = (await _get(app, "/skills")).json()
    pandapower = next(s for s in body["skills"] if s["id"] == "pandapower")
    targets = {t["escalate_to"] for t in pandapower["escalation"]}
    assert "thermal-overload-mitigation" in targets
    assert all(t["observation"] for t in pandapower["escalation"])


async def test_skills_health_is_unknown_by_design(app):
    """★ 不得让用户以为 21 个技能都可靠 —— 整体健康度必须如实标 unknown。"""
    health = (await _get(app, "/skills")).json()["health"]
    assert health["level"] == "unknown"
    assert set(health["signals"]) == {
        "escalation_missing", "dangling_escalation", "orphan_playbooks",
    }
    assert health["source"], "unknown 必须给出成因说明"


async def test_skills_missing_root_is_200_not_500(app, monkeypatch, tmp_path):
    """PowerSkills 可以不在场（两仓库可分开 clone）—— 缺目录不是服务端故障。"""
    monkeypatch.setenv(ENV_SKILLS_ROOT, str(tmp_path / "不存在"))
    r = await _get(app, "/skills")
    assert r.status_code == 200
    body = r.json()
    assert body["root_exists"] is False
    assert body["summary"]["total"] == 0
    assert body["skills"] == []


async def test_skills_is_503_when_config_unresolvable(app, monkeypatch):
    def boom():
        raise ConfigError("配置无法解析")

    monkeypatch.setattr(api_mod, "_cfg", boom)
    r = await _get(app, "/skills")
    assert r.status_code == 503


# ---------------------------------------------------------------- 不变量


async def test_both_endpoints_do_not_build_inventory(app, monkeypatch):
    """★ 两个端点都必须**廉价**：它们不得触碰会拉起 server 的清单构建。"""
    import powermcp_gateway.inventory as inv_mod

    real = inv_mod.build_inventory

    async def spy(*a, **kw):
        raise AssertionError("P0-2a 端点不得构建工具清单（会真实拉起 server）")

    monkeypatch.setattr(inv_mod, "build_inventory", spy)
    assert (await _get(app, "/environment")).status_code == 200
    assert (await _get(app, "/skills")).status_code == 200
    monkeypatch.setattr(inv_mod, "build_inventory", real)


async def test_environment_and_skills_agree_on_skill_count(app):
    """两个端点都报技能数 —— 必须一致（单一真源，避免两处各算一遍算出不同结果）。"""
    env = (await _get(app, "/environment")).json()
    sk = (await _get(app, "/skills")).json()
    assert env["skills"]["total"] == sk["summary"]["total"]
    assert env["skills"]["by_kind"] == sk["summary"]["by_kind"]
    assert json.dumps(env["skills"]["root"]) == json.dumps(sk["root"])
