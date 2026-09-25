"""环境变量透传的测试（`config.server_env` 与 `proxy._server_params`）。

★ 这一组测试存在的理由本身就是一个**实测缺陷**：
  MCP SDK 只继承白名单环境变量，`POWERIO_MCP_ALLOWED_ROOTS` 与 `HIGHS_LIB_DIR`
  都不在其中 —— 不显式传就等于"父进程设了也不生效"。
  `test_passthrough_vars_are_really_needed` 把这条**理由**也钉住：
  若哪天 SDK 把它们加进白名单，那条断言会提醒我们"这个修复已不再必要"。
"""

from __future__ import annotations

import os

import pytest
from mcp.client.stdio import DEFAULT_INHERITED_ENV_VARS

from powermcp_gateway.config import (
    ENV_EXTRA_SERVER_ENV,
    SERVER_ENV_PASSTHROUGH,
    GatewayConfig,
    server_env,
)
from powermcp_gateway.proxy import _server_params


def _clean(monkeypatch, *keep: tuple[str, str]):
    """清掉全部透传变量，只保留显式给定的。"""
    for name in (*SERVER_ENV_PASSTHROUGH, ENV_EXTRA_SERVER_ENV):
        monkeypatch.delenv(name, raising=False)
    for k, v in keep:
        monkeypatch.setenv(k, v)


# ---------------------------------------------------------------- 理由本身


def test_passthrough_vars_are_really_needed():
    """★ 把修复的**理由**钉住：这些变量确实不在 SDK 白名单里。

    若哪天 MCP SDK 把它们加进 `DEFAULT_INHERITED_ENV_VARS`，本条会失败 ——
    那不是代码回归，而是**提示"显式透传已不再必要，可重新评估"**。
    """
    overlap = set(SERVER_ENV_PASSTHROUGH) & set(DEFAULT_INHERITED_ENV_VARS)
    assert overlap == set(), (
        f"{overlap} 已被 SDK 白名单继承 —— 显式透传对它们已多余，请重新评估本清单"
    )


def test_allowed_roots_var_is_in_passthrough():
    assert "POWERIO_MCP_ALLOWED_ROOTS" in SERVER_ENV_PASSTHROUGH
    assert "HIGHS_LIB_DIR" in SERVER_ENV_PASSTHROUGH


# ---------------------------------------------------------------- server_env


def test_unset_vars_are_omitted(monkeypatch):
    _clean(monkeypatch)
    assert server_env() == {}


def test_set_vars_are_passed(monkeypatch):
    _clean(monkeypatch, ("POWERIO_MCP_ALLOWED_ROOTS", "D:/GridData"),
           ("HIGHS_LIB_DIR", "C:/highs"))
    assert server_env() == {
        "POWERIO_MCP_ALLOWED_ROOTS": "D:/GridData",
        "HIGHS_LIB_DIR": "C:/highs",
    }


def test_empty_string_is_not_passed(monkeypatch):
    """★ 空串会被上游当作「未配置」而落到 legacy 变量 —— 必须保持"不传"。"""
    _clean(monkeypatch, ("POWERIO_MCP_ALLOWED_ROOTS", ""))
    assert "POWERIO_MCP_ALLOWED_ROOTS" not in server_env()


def test_legacy_spellings_are_passed_through(monkeypatch):
    _clean(monkeypatch, ("POWERIO_MCP_ROOT", "D:/GridData"))
    assert server_env()["POWERIO_MCP_ROOT"] == "D:/GridData"


def test_extra_env_var_accepts_comma_separated(monkeypatch):
    _clean(monkeypatch, (ENV_EXTRA_SERVER_ENV, "MY_A, MY_B"))
    monkeypatch.setenv("MY_A", "1")
    monkeypatch.setenv("MY_B", "2")
    assert server_env() == {"MY_A": "1", "MY_B": "2"}


def test_extra_env_var_accepts_pathsep_separated(monkeypatch):
    _clean(monkeypatch, (ENV_EXTRA_SERVER_ENV, f"MY_A{os.pathsep}MY_B"))
    monkeypatch.setenv("MY_B", "2")
    assert server_env() == {"MY_B": "2"}


def test_extra_env_var_ignores_blanks(monkeypatch):
    _clean(monkeypatch, (ENV_EXTRA_SERVER_ENV, " , ,MY_A, "))
    monkeypatch.setenv("MY_A", "1")
    assert server_env() == {"MY_A": "1"}


def test_explicit_mapping_param_is_used(monkeypatch):
    _clean(monkeypatch)
    assert server_env({"POWERIO_MCP_ALLOWED_ROOTS": "X"}) == {
        "POWERIO_MCP_ALLOWED_ROOTS": "X"
    }


# ---------------------------------------------------------------- _server_params


def test_server_params_carry_env_command_and_cwd(monkeypatch):
    _clean(monkeypatch, ("POWERIO_MCP_ALLOWED_ROOTS", "D:/GridData"))
    cfg = GatewayConfig.discover()
    p = _server_params(cfg, "surge")

    assert p.command == str(cfg.python)
    assert p.args == ["-m", "powermcp.cli", "run", "surge"]
    assert p.cwd == str(cfg.powermcp_root)
    assert p.env is not None and p.env["POWERIO_MCP_ALLOWED_ROOTS"] == "D:/GridData"


def test_server_params_env_is_none_when_nothing_to_pass(monkeypatch):
    """没有要透传的项时给空 dict（而非 None）—— 语义更明确，且便于断言。"""
    _clean(monkeypatch)
    assert _server_params(GatewayConfig.discover(), "pypsa").env == {}


@pytest.mark.parametrize("server", ["surge", "pandapower", "powerio"])
def test_server_params_per_server_name(monkeypatch, server):
    _clean(monkeypatch)
    assert _server_params(GatewayConfig.discover(), server).args[-1] == server
