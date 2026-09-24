from pathlib import Path

import pytest

from powermcp_gateway.config import ConfigError, GatewayConfig


def test_discover_finds_repo_and_interpreter():
    cfg = GatewayConfig.discover()
    assert cfg.powermcp_root.is_dir()
    assert (cfg.powermcp_root / "powermcp" / "registry.py").is_file()
    assert cfg.python.is_file()
    assert cfg.python.name == "python.exe"


def test_discover_from_explicit_root(tmp_path: Path):
    # 路径分隔符跨平台：Windows 上异常消息里是 powermcp\registry.py
    with pytest.raises(ConfigError, match=r"powermcp[\\/]registry\.py"):
        GatewayConfig.discover(root=tmp_path)


def test_discover_reports_missing_venv(tmp_path: Path):
    # 造一个只有 registry.py、没有 .venv 的假仓库根
    (tmp_path / "powermcp").mkdir()
    (tmp_path / "powermcp" / "registry.py").write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match=".venv"):
        GatewayConfig.discover(root=tmp_path)
