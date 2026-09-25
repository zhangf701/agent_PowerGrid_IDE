"""环境就绪报告 —— `GET /environment`。

★ 设计边界（**刻意**）：本模块只做**廉价检查**，**不拉起任何 MCP server**。
  `build_inventory` 会真实启动每个 server 进程（秒级/个），把它塞进环境报告会让
  「打开界面」变成一次秒级等待。**server 挂载状态与依赖缺失由 `GET /contracts/t0`
  给出**（那里本来就要建清单，且有 T0Cache）—— 本模块在响应里显式写明这一分工，
  避免前端以为是漏了。

★ 安全约束：**绝不回显 `api_key`**，连 `base_url` 也只报 `scheme://host`
  （URL 的 path / query / userinfo 都可能夹带凭据）。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .config import GatewayConfig
from .contracts import REGISTRY
from .llm import ENV_API_KEY, ENV_BASE_URL, ENV_MODEL, ENV_TIMEOUT_S, LlmConfig, LlmConfigError
from .skills import build_report as skills_report

logger = logging.getLogger(__name__)

#: 覆盖模块根目录（默认取 PowerMCP 的兄弟目录）
ENV_MODULES_ROOT = "POWERMCP_MODULES_ROOT"

#: 路径围笼环境变量（PowerIO 沙箱用）
ENV_ALLOWED_ROOTS = "POWERIO_MCP_ALLOWED_ROOTS"

#: surge 的 DC OPF 需要它 —— 且**当前未持久化**（只在 shell 会话内有效）
ENV_HIGHS_LIB_DIR = "HIGHS_LIB_DIR"

#: 允许的求解器白名单（方案 v4 §九：为避免许可依赖，只允许开源求解器）
ALLOWED_SOLVERS: tuple[str, ...] = ("highs", "cbc", "glpk", "ipopt")

#: **显式排除**：`registry.py` 中 PyPSA / Egret / GenX 的 `external_solvers` 均含 Gurobi，
#: 须在网关侧过滤（方案 v4 §九）。
EXCLUDED_SOLVERS: tuple[str, ...] = ("gurobi",)

#: 网关自身要求的最低 Python（见 config.GatewayConfig.discover 的同款检查）
MIN_PYTHON: tuple[int, int] = (3, 10)

_NOTES: tuple[str, ...] = (
    "本报告只做廉价检查，**不拉起任何 MCP server** —— "
    "server 挂载状态、依赖缺失（missing / 需配置路径）与工具面计数见 `GET /contracts/t0`。",
    "「装得上 ≠ 跑得动」必须显式区分：依赖满足、进程能起来，不等于该引擎的**求解**可用"
    "（如 HOPE / GenX 需本地 Julia，Egret 的 Ipopt 实测不可用）。",
    "`HIGHS_LIB_DIR` 目前**未持久化**，只在设置它的那个 shell 会话内有效 —— "
    "进程从别处启动时 surge 的 DC OPF 会不可用。",
)


def modules_root(cfg: GatewayConfig) -> Path:
    """定位选题模块根目录（默认 `PowerMCP` 的兄弟目录 `modules/`）。"""
    override = os.environ.get(ENV_MODULES_ROOT)
    if override:
        return Path(override)
    return cfg.powermcp_root.parent / "modules"


def safe_endpoint(base_url: str) -> str:
    """把 `base_url` 收敛成 `scheme://host` —— **绝不外泄 path / query / userinfo**。

    凭据常出现在这些位置（`https://user:pass@host/v1?key=…`），
    而诊断只需要知道"指向哪个服务"。
    """
    try:
        parts = urlsplit(base_url)
    except ValueError:
        return "<无法解析>"
    if not parts.scheme or not parts.hostname:
        return "<无法解析>"
    host = parts.hostname
    if parts.port:
        host = f"{host}:{parts.port}"
    return f"{parts.scheme}://{host}"


def _llm_section() -> dict:
    """LLM 配置是否就位。

    ★ 未配置**不是**错误（可以不配 LLM 只用工具代理），但必须如实报出来 ——
      否则用户会以为配好了，直到第一次对话才失败。
    """
    try:
        cfg = LlmConfig.from_env()
    except LlmConfigError as exc:
        return {
            "configured": False,
            "error": str(exc),
            "required_env": [ENV_BASE_URL, ENV_API_KEY, ENV_MODEL],
            "optional_env": [ENV_TIMEOUT_S],
        }
    return {
        "configured": True,
        "endpoint": safe_endpoint(cfg.base_url),
        "model": cfg.model,
        "timeout_s": cfg.timeout_s,
        # ★ 只报"是否设置"，绝不回显值
        "api_key_set": bool(cfg.api_key),
    }


def _powermcp_section(cfg: GatewayConfig) -> dict:
    registry = cfg.powermcp_root / "powermcp" / "registry.py"
    return {
        "root": str(cfg.powermcp_root),
        "root_ok": registry.is_file(),
        "venv_python": str(cfg.python),
        "venv_python_ok": cfg.python.is_file(),
        "server_timeout_s": cfg.server_timeout_s,
    }


def _paths_section() -> dict:
    raw = os.environ.get(ENV_ALLOWED_ROOTS, "")
    roots = [p for p in (x.strip() for x in raw.split(os.pathsep)) if p]
    return {
        "env_var": ENV_ALLOWED_ROOTS,
        "set": bool(roots),
        "roots": roots,
        "note": (
            "路径围笼：server 只能读写这些根下的文件。"
            "**未设置时 server 读不到算例目录**（工程上最容易漏的一步）。"
        ),
    }


def _solvers_section() -> dict:
    highs = os.environ.get(ENV_HIGHS_LIB_DIR, "").strip()
    return {
        "allowed": list(ALLOWED_SOLVERS),
        "excluded": list(EXCLUDED_SOLVERS),
        "highs_lib_dir_set": bool(highs),
        "note": (
            "只允许开源求解器以避免许可依赖；Gurobi 显式排除。"
            "⚠️ Egret 的 Ipopt 实测不可用 → 其 OPF 能力受限，能力矩阵须如实标注。"
        ),
    }


def _modules_section(cfg: GatewayConfig) -> dict:
    root = modules_root(cfg)
    found: list[str] = []
    if root.is_dir():
        found = sorted(
            p.parent.name for p in root.glob("*/module.yaml")
        )
    return {
        "root": str(root),
        "root_exists": root.is_dir(),
        "modules": found,
        "note": (
            "选题模块（方案 v4 §六）。尚未实现装配机制 —— "
            "当前只如实报出目录与已发现的模块清单。"
        ),
    }


def build_report(cfg: GatewayConfig) -> dict:
    """`GET /environment` 的响应体。"""
    py_ok = sys.version_info[:2] >= MIN_PYTHON
    skills = skills_report(cfg)
    return {
        "gateway": {
            "python": ".".join(str(x) for x in sys.version_info[:3]),
            "python_ok": py_ok,
            "min_python": ".".join(str(x) for x in MIN_PYTHON),
        },
        "powermcp": _powermcp_section(cfg),
        "paths": _paths_section(),
        "solvers": _solvers_section(),
        "llm": _llm_section(),
        "contracts": {
            "registered": [
                {"contract": e.contract, "name": e.name, "timeframe": e.timeframe}
                for e in REGISTRY.all()
            ],
            "note": (
                "契约 3（参数）由代理层**逐调用**产出，不进注册表；"
                "契约 8（运行时依赖）属 T1，**尚未实现**。"
            ),
        },
        "skills": {
            "root": skills["root"],
            "root_exists": skills["root_exists"],
            "total": skills["summary"]["total"],
            "by_kind": skills["summary"]["by_kind"],
        },
        "modules": _modules_section(cfg),
        "notes": list(_NOTES),
    }
