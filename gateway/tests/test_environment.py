"""`environment.py` 的测试。

★ 最关键的一条是 `test_api_key_never_leaks` —— 环境报告会暴露给前端，
  密钥一旦回显就是**凭据外泄**。该断言用 `json.dumps` 全文搜索，
  而不是只查某个字段（防止将来新增字段时绕过）。
"""

from __future__ import annotations

import json
import os

import pytest

from powermcp_gateway.config import GatewayConfig
from powermcp_gateway.environment import (
    ALLOWED_SOLVERS,
    ENV_MODULES_ROOT,
    EXCLUDED_SOLVERS,
    build_report,
    modules_root,
    safe_endpoint,
)
from powermcp_gateway.llm import ENV_API_KEY, ENV_BASE_URL, ENV_MODEL, ENV_TIMEOUT_S

_SECRET = "sk-DO-NOT-LEAK-9f3a7c"


@pytest.fixture
def cfg():
    return GatewayConfig.discover()


@pytest.fixture
def llm_env(monkeypatch):
    monkeypatch.setenv(ENV_BASE_URL, "https://user:pass@api.example.com/v1?key=x")
    monkeypatch.setenv(ENV_API_KEY, _SECRET)
    monkeypatch.setenv(ENV_MODEL, "test-model")
    monkeypatch.delenv(ENV_TIMEOUT_S, raising=False)


# ---------------------------------------------------------------- 凭据安全


def test_api_key_never_leaks(cfg, llm_env):
    """★ 密钥绝不得出现在报告里 —— 全文搜索，而非只查某个字段。"""
    dumped = json.dumps(build_report(cfg), ensure_ascii=False)
    assert _SECRET not in dumped
    assert "user:pass" not in dumped, "URL userinfo 也必须剥离"


def test_safe_endpoint_strips_path_query_and_userinfo():
    assert safe_endpoint("https://user:pass@api.example.com/v1?key=SECRET") == "https://api.example.com"
    assert safe_endpoint("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434"
    assert safe_endpoint("https://api.example.com") == "https://api.example.com"


@pytest.mark.parametrize("bad", ["", "not-a-url", "/just/a/path", "://missing-scheme"])
def test_safe_endpoint_tolerates_garbage(bad):
    assert safe_endpoint(bad) == "<无法解析>"


# ---------------------------------------------------------------- LLM 段


def test_llm_section_reports_not_configured_with_required_env(cfg, monkeypatch):
    for k in (ENV_BASE_URL, ENV_API_KEY, ENV_MODEL):
        monkeypatch.delenv(k, raising=False)
    sec = build_report(cfg)["llm"]
    assert sec["configured"] is False
    assert set(sec["required_env"]) == {ENV_BASE_URL, ENV_API_KEY, ENV_MODEL}


def test_llm_section_reports_configured_without_key_value(cfg, llm_env):
    sec = build_report(cfg)["llm"]
    assert sec["configured"] is True
    assert sec["model"] == "test-model"
    assert sec["endpoint"] == "https://api.example.com"
    assert sec["api_key_set"] is True
    assert "api_key" not in sec, "字段名本身就会诱导前端去取它"


def test_llm_section_marks_empty_key_as_not_set(cfg, llm_env, monkeypatch):
    """本地 vLLM / Ollama 常不校验 key —— 空串是合法配置，但必须如实报「未设置」。"""
    monkeypatch.setenv(ENV_API_KEY, "")
    sec = build_report(cfg)["llm"]
    assert sec["configured"] is True
    assert sec["api_key_set"] is False


# ---------------------------------------------------------------- 路径围笼


def test_paths_unset_reports_not_set(cfg, monkeypatch):
    monkeypatch.delenv("POWERIO_MCP_ALLOWED_ROOTS", raising=False)
    sec = build_report(cfg)["paths"]
    assert sec["set"] is False and sec["roots"] == []


def test_paths_parses_multiple_roots(cfg, monkeypatch, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", f"{a}{os.pathsep}{b}")
    sec = build_report(cfg)["paths"]
    assert sec["set"] is True
    assert sec["roots"] == [str(a), str(b)]


# ---------------------------------------------------------------- 求解器


def test_solvers_exclude_gurobi_and_report_highs(cfg, monkeypatch):
    monkeypatch.delenv("HIGHS_LIB_DIR", raising=False)
    sec = build_report(cfg)["solvers"]
    assert sec["allowed"] == list(ALLOWED_SOLVERS)
    assert sec["excluded"] == list(EXCLUDED_SOLVERS)
    assert "gurobi" in sec["excluded"]
    assert sec["highs_lib_dir_set"] is False

    monkeypatch.setenv("HIGHS_LIB_DIR", "C:/highs/lib")
    assert build_report(cfg)["solvers"]["highs_lib_dir_set"] is True


# ---------------------------------------------------------------- 模块目录


def test_modules_root_env_override(tmp_path, monkeypatch, cfg):
    monkeypatch.setenv(ENV_MODULES_ROOT, str(tmp_path))
    assert modules_root(cfg) == tmp_path


def test_modules_section_lists_module_yaml(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_MODULES_ROOT, str(tmp_path))
    (tmp_path / "n1-ranking").mkdir()
    (tmp_path / "n1-ranking" / "module.yaml").write_text("id: n1-ranking\n", encoding="utf-8")
    (tmp_path / "空目录").mkdir()

    sec = build_report(cfg)["modules"]
    assert sec["root_exists"] is True
    assert sec["modules"] == ["n1-ranking"]


def test_modules_section_when_absent(cfg, tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_MODULES_ROOT, str(tmp_path / "不存在"))
    sec = build_report(cfg)["modules"]
    assert sec["root_exists"] is False and sec["modules"] == []


# ---------------------------------------------------------------- 整体形状


def test_report_shape_and_contracts(cfg, llm_env):
    r = build_report(cfg)
    assert set(r) == {
        "gateway", "powermcp", "paths", "solvers", "llm",
        "contracts", "skills", "modules", "notes",
    }
    assert r["gateway"]["python_ok"] is True
    assert r["powermcp"]["root_ok"] is True
    # 契约 3 不进注册表（事件驱动），契约 8 属 T1 未实现
    assert [c["contract"] for c in r["contracts"]["registered"]] == [1, 2, 4, 5, 6, 7]
    assert r["notes"], "必须带上「本报告不拉起 server」等边界说明"


def test_environment_module_does_not_depend_on_inventory_build():
    """★ 环境报告必须**廉价** —— 它不得依赖 `build_inventory`（那会真实拉起 server）。

    静态断言：该函数不得出现在模块命名空间里。若将来有人为了"顺便报一下挂载状态"
    把它 import 进来，这条测试会提醒他这会破坏「打开界面即秒回」。
    """
    import powermcp_gateway.environment as env_mod

    assert not hasattr(env_mod, "build_inventory")
