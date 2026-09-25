"""`GET /modules` 与**内核自证条件**的测试。

★★ 本文件最重要的部分是 `test_kernel_still_works_without_modules` 一族：
   内核**不依赖任何模块** —— 模块根不存在 / 为空 / 含失败模块 / 全部禁用时，
   其他端点必须**全部正常**。若禁用模块内核就不可用，说明内核被领域知识污染了。
   这是把「内核稳定」从口号变成**可检验判据**的地方。
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import powermcp_gateway.api as api_mod
from powermcp_gateway.api import create_app
from powermcp_gateway.config import ConfigError, GatewayConfig
from powermcp_gateway.modules import ENV_MODULES_ROOT, scaffold_module

_MINIMAL = "id: {mid}\nname: {mid}\nversion: 0.1.0\nkind: research\nmaturity: L0\n"

#: 与模块无关的端点（内核本体）—— 自证条件要在它们全部上成立
_KERNEL_ENDPOINTS = ("/health", "/servers", "/environment", "/skills", "/cases")


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


async def _get(app, path: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path)


def _write_module(root, mid: str, body: str) -> None:
    p = root / mid / "module.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------- 路由


async def test_route_registered(app):
    assert "/modules" in {getattr(r, "path", "") for r in app.routes}


# ---------------------------------------------------------------- 正常路径


async def test_empty_root_is_200(app, modules_env):
    modules_env.mkdir(parents=True, exist_ok=True)
    r = await _get(app, "/modules")
    assert r.status_code == 200
    body = r.json()
    assert body["root_exists"] is True
    assert body["summary"]["total"] == 0
    assert body["modules"] == [] and body["failures"] == []


async def test_lists_modules_and_effective_set(app, modules_env):
    modules_env.mkdir(parents=True, exist_ok=True)
    _write_module(modules_env, "n1-ranking",
                  _MINIMAL.format(mid="n1-ranking")
                  + "tools: [surge.run_n1_branch_contingency]\n"
                    "skills: [contingency-mitigation]\n")
    body = (await _get(app, "/modules")).json()
    assert body["summary"]["total"] == 1
    assert body["summary"]["enabled"] == 1
    assert body["modules"][0]["id"] == "n1-ranking"
    assert body["effective"]["tools"] == ["surge.run_n1_branch_contingency"]


async def test_reports_failures_without_failing_the_request(app, modules_env):
    """★ fail-loud：失败**被报出来**，但请求仍 200 —— 失败不是服务端故障。"""
    modules_env.mkdir(parents=True, exist_ok=True)
    _write_module(modules_env, "good", _MINIMAL.format(mid="good"))
    _write_module(modules_env, "bad", "id: bad\nkind: 不存在\n")

    body = (await _get(app, "/modules")).json()
    assert body["summary"]["total"] == 1 and body["summary"]["failed"] == 1
    assert [f["module_id"] for f in body["failures"]] == ["bad"]
    assert "kind" in body["failures"][0]["error"]


async def test_scaffolded_module_shows_up(app, modules_env):
    """脚手架产物必须能通过端到端链路（round-trip）。"""
    modules_env.mkdir(parents=True, exist_ok=True)
    scaffold_module(modules_env, "demo-case", name="演示选题")
    body = (await _get(app, "/modules")).json()
    assert [m["id"] for m in body["modules"]] == ["demo-case"]
    assert body["failures"] == []


async def test_modules_endpoint_agrees_with_environment(app, modules_env):
    """★ 单一真源：`/modules` 与 `/environment` 的模块口径必须一致。"""
    modules_env.mkdir(parents=True, exist_ok=True)
    _write_module(modules_env, "a", _MINIMAL.format(mid="a"))
    _write_module(modules_env, "bad", "id: bad\nkind: 坏\n")

    mods = (await _get(app, "/modules")).json()
    env = (await _get(app, "/environment")).json()
    assert env["modules"]["modules"] == [m["id"] for m in mods["modules"]]
    assert env["modules"]["failed"] == [f["module_id"] for f in mods["failures"]]


async def test_unknown_skill_is_warned_not_failed(app, modules_env):
    """外部系统的名字（skill id）只**警告** —— 不替上游断言。"""
    modules_env.mkdir(parents=True, exist_ok=True)
    _write_module(modules_env, "a", _MINIMAL.format(mid="a")
                  + "skills: [这个技能不存在]\n")
    body = (await _get(app, "/modules")).json()
    assert body["failures"] == []
    assert any("这个技能不存在" in n for n in body["notes"])


async def test_is_503_when_config_unresolvable(app, monkeypatch):
    def boom():
        raise ConfigError("未找到 PowerMCP 仓库根")

    monkeypatch.setattr(api_mod, "_cfg", boom)
    assert (await _get(app, "/modules")).status_code == 503


# ---------------------------------------------------------------- ★★ 内核自证条件


def _module_root_states(tmp_path):
    """四种「模块不可用」的状态 —— 内核都必须在其中照常工作。"""
    missing = tmp_path / "根本不存在"
    empty = tmp_path / "空"
    broken = tmp_path / "全坏"
    disabled = tmp_path / "全禁用"

    empty.mkdir(parents=True, exist_ok=True)
    _write_module(broken, "b1", "id: b1\nkind: 坏\n")
    _write_module(broken, "b2", "id: 与目录名不符\n")
    _write_module(disabled, "d1", _MINIMAL.format(mid="d1") + "enabled: false\n")
    _write_module(disabled, "d2", _MINIMAL.format(mid="d2") + "enabled: false\n")

    return [
        ("模块根不存在", missing),
        ("模块根为空", empty),
        ("所有模块装配失败", broken),
        ("所有模块被禁用", disabled),
    ]


@pytest.mark.parametrize("label", ["模块根不存在", "模块根为空",
                                   "所有模块装配失败", "所有模块被禁用"])
async def test_kernel_still_works_without_modules(cfg, tmp_path, monkeypatch, label):
    """★★ **自证条件**：禁用全部模块后内核仍可用。

    内核被领域知识污染的最直接症状就是"模块没了内核就不转了"。
    这条测试对四种模块不可用状态逐一验证内核端点全部 200。
    """
    root = dict(_module_root_states(tmp_path))[label]
    monkeypatch.setenv(ENV_MODULES_ROOT, str(root))
    app = create_app(cfg=cfg)

    for path in _KERNEL_ENDPOINTS:
        r = await _get(app, path)
        assert r.status_code == 200, f"{label} 下 {path} 返回 {r.status_code}: {r.text[:200]}"

    # /modules 自身也必须 200（如实报告"没有可用模块"，而不是报错）
    mods = await _get(app, "/modules")
    assert mods.status_code == 200
    assert mods.json()["summary"]["enabled"] == 0


async def test_kernel_endpoints_do_not_reference_module_ids(cfg, tmp_path, monkeypatch):
    """内核端点的响应里**不应出现模块概念** —— 出现即说明内核开始知道领域知识了。"""
    root = tmp_path / "modules"
    root.mkdir(parents=True, exist_ok=True)
    _write_module(root, "some-research-topic", _MINIMAL.format(mid="some-research-topic"))
    monkeypatch.setenv(ENV_MODULES_ROOT, str(root))
    app = create_app(cfg=cfg)

    for path in ("/health", "/servers", "/skills", "/cases"):
        text = (await _get(app, path)).text
        assert "some-research-topic" not in text, f"{path} 泄漏了模块概念"


async def test_broken_module_does_not_break_other_modules(cfg, tmp_path, monkeypatch):
    root = tmp_path / "modules"
    root.mkdir(parents=True, exist_ok=True)
    _write_module(root, "good", _MINIMAL.format(mid="good"))
    _write_module(root, "bad", "id: bad\nkind: 坏\n")
    monkeypatch.setenv(ENV_MODULES_ROOT, str(root))
    app = create_app(cfg=cfg)

    body = (await _get(app, "/modules")).json()
    assert [m["id"] for m in body["modules"]] == ["good"]
    assert body["summary"] == {
        "total": 1, "enabled": 1, "disabled": 0, "failed": 1,
        "by_maturity": {"L0": 1}, "by_kind": {"research": 1},
    }
