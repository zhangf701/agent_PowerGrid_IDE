"""网关的路径、超时与**子进程环境**解析。

本机默认 `python` 是 3.9，低于项目要求的 3.10，因此一律使用 PowerMCP 的 venv 解释器。
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    """网关配置无法解析。"""


#: ★ 必须**显式**传给 MCP server 子进程的环境变量。
#:
#: ⚠️ MCP SDK **只继承一份白名单**（`mcp.client.stdio.DEFAULT_INHERITED_ENV_VARS`，
#:    Windows 上仅 APPDATA/HOMEDRIVE/HOMEPATH/LOCALAPPDATA/PATH/PATHEXT/
#:    PROCESSOR_ARCHITECTURE/SYSTEMDRIVE/SYSTEMROOT/TEMP/USERNAME/USERPROFILE），
#:    其余变量**一律不传** —— 父进程设了也没用。
#:
#: 实测（2026-09-25，`.superpowers/sdd/m7-env-passthrough.py`）：
#: 父进程设 `POWERIO_MCP_ALLOWED_ROOTS` 与 `HIGHS_LIB_DIR` 后，
#: 二者**都不在** `get_default_environment()` 里。后果：
#:   - **路径围笼形同虚设**：server 只认默认根（`powerio.mcp.sandbox` 导入时的 cwd，
#:     即 `cfg.powermcp_root`）→ 网关**读不到算例目录**；
#:   - **surge 的 DC OPF 永远拿不到 `HIGHS_LIB_DIR`**（不是"仅在 shell 会话内有效"，
#:     而是经网关调用时**从不生效**）。
SERVER_ENV_PASSTHROUGH: tuple[str, ...] = (
    "POWERIO_MCP_ALLOWED_ROOTS",    # 路径围笼（主变量）
    "POWERIO_MCP_ROOT",             # 兼容拼写（legacy）
    "POWERIO_MCP_ALLOWED_ROOT",     # 兼容拼写（legacy）
    "HIGHS_LIB_DIR",                # surge 的 DC OPF 求解器
    # ⚠️ **刻意不**透传 `POWERMCP_HOME`：会话级命名空间（§11.2 措施 1）是**显式**
    #   传给子进程的（`proxy.session_server_env`），不依赖继承。若把它加进透传，
    #   "无会话"时子进程也会开始认操作员的 `POWERMCP_HOME` —— 那是**改变引擎产物
    #   落点**的行为变更，与本次目标无关，不该顺手做掉。
)

#: 操作员追加透传的变量名（逗号或 `os.pathsep` 分隔）。
#: 逃生口：避免将来出现"某个引擎需要某个变量但透传清单里没有"时只能改代码。
ENV_EXTRA_SERVER_ENV = "POWERMCP_GATEWAY_EXTRA_SERVER_ENV"


def server_env(env: Mapping[str, str] | None = None,
               overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """构造要传给 MCP server 子进程的环境变量。

    ★ **只包含「已设置且非空」的项**：传空串会把"未设置"变成"设为空"，
      而 `powerio.mcp.sandbox` 对两者的处理**不同** —— 空串会被当作"未配置"，
      从而落到 `POWERIO_MCP_ROOT` 等 legacy 变量（`os.environ.get(name)` 为假值）。
      保持"不传"，语义才与上游一致。

    Args:
        overrides: **会话级覆盖**（§11.2 措施 1）。在透传结果之上叠加，故能覆盖
            操作员的全局设定 —— 这正是"给每个会话一个独立的 `POWERMCP_HOME`"的落点。
            ⚠️ 覆盖项**不做"非空"过滤**：调用方明确要求的值就该生效（这是显式意图，
            与上面那条"别把未设置变成空"的规则针对的是**继承**语义，不是覆盖语义）。
    """
    e = os.environ if env is None else env
    names = list(SERVER_ENV_PASSTHROUGH)
    raw_extra = e.get(ENV_EXTRA_SERVER_ENV, "")
    names += [
        n.strip()
        for n in raw_extra.replace(",", os.pathsep).split(os.pathsep)
        if n.strip()
    ]
    out = {n: e[n] for n in names if e.get(n)}
    if overrides:
        out.update({k: v for k, v in overrides.items() if v})
    return out


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
