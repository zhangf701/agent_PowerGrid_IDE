"""网关的路径与超时解析。

本机默认 `python` 是 3.9，低于项目要求的 3.10，因此一律使用 PowerMCP 的 venv 解释器。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    """网关配置无法解析。"""


def _default_root() -> Path:
    """默认指向 PowerMCP 仓库根。

    路径推演：gateway/src/powermcp_gateway/config.py
      parents[0]=powermcp_gateway  [1]=src  [2]=gateway  [3]=<项目根>
    而 PowerMCP 仓库在 <项目根>/PowerMCP 下，故需再拼一层。
    """
    return Path(__file__).resolve().parents[3] / "PowerMCP"


@dataclass(frozen=True)
class GatewayConfig:
    powermcp_root: Path
    python: Path
    server_timeout_s: float = 90.0

    @classmethod
    def discover(cls, root: Path | None = None) -> "GatewayConfig":
        root = Path(root) if root is not None else _default_root()

        registry = root / "powermcp" / "registry.py"
        if not registry.is_file():
            raise ConfigError(
                f"未找到 {root / 'powermcp' / 'registry.py'} —— "
                f"root 应指向 PowerMCP 仓库根，实际为 {root}"
            )

        python = root / ".venv" / "Scripts" / "python.exe"
        if not python.is_file():
            raise ConfigError(
                f"未找到解释器 {python} —— "
                f"请先在 {root} 下建好 .venv（本机默认 python 是 3.9，不可用）"
            )

        if sys.version_info < (3, 10):
            raise ConfigError(
                f"网关自身运行在 Python {sys.version_info[:2]} 上，低于要求的 3.10"
            )

        return cls(powermcp_root=root, python=python)
