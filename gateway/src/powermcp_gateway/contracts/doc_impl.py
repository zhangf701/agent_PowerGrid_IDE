"""契约 2：文档-实现一致性。

比对 server 的 README.md 所声明的工具名 vs list_tools 实际返回。
已知证据：opendss 的 README / SKILL.md 引用的 6 个工具名全部不存在。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..config import GatewayConfig
from ..inventory import ToolInventory
from .model import ContractFinding

# server id -> PowerMCP 仓库内的目录名（大小写敏感，实测自仓库结构）
SERVER_DOC_DIRS: dict[str, str] = {
    "pandapower": "pandapower",
    "pypsa": "PyPSA",
    "surge": "surge",
    "andes": "ANDES",
    "egret": "Egret",
    "opendss": "OpenDSS",
    "hope": "HOPE",
    "genx": "GenX",
}

_BACKTICKED = re.compile(r"`([a-z][a-z0-9_]{2,})`")


def extract_declared_tool_names(markdown: str) -> set[str]:
    """README 中反引号包裹的 snake_case 标识符。

    只收含下划线的名字：工具名一律带下划线（run_power_flow），
    而 `pandapower` / `pip` 这类词是包名或命令，不是工具。
    """
    return {m for m in _BACKTICKED.findall(markdown) if "_" in m}


class DocImplEvaluator:
    contract = 2
    name = "文档-实现一致性"
    timeframe = "T0"

    def __init__(self, doc_dirs: dict[str, str] | None = None) -> None:
        self._doc_dirs = dict(doc_dirs) if doc_dirs is not None else dict(SERVER_DOC_DIRS)

    def evaluate(self, inv: ToolInventory, cfg: GatewayConfig) -> list[ContractFinding]:
        findings: list[ContractFinding] = []

        for server in inv.servers():
            actual = set(inv.names(server))
            dirname = self._doc_dirs.get(server)
            readme = (cfg.powermcp_root / dirname / "README.md") if dirname else None

            if readme is None or not readme.is_file():
                findings.append(
                    ContractFinding(
                        contract=2, state="unknown", reason="structural", subject=server,
                        detail=f"未找到 {server} 的 README.md，无法比对文档与实现。",
                        evidence={"server": server, "readme": str(readme) if readme else None},
                    )
                )
                continue

            declared = extract_declared_tool_names(readme.read_text(encoding="utf-8"))
            declared_missing = sorted(declared - actual)
            undocumented = sorted(actual - declared)

            if declared_missing:
                findings.append(
                    ContractFinding(
                        contract=2, state="violated", reason=None, subject=server,
                        detail=(
                            f"README 声明的 {len(declared_missing)} 个工具在运行时不存在："
                            f"{'、'.join(declared_missing)}。"
                        ),
                        evidence={"server": server, "declared_missing": declared_missing,
                                  "readme": str(readme)},
                    )
                )
            if undocumented:
                findings.append(
                    ContractFinding(
                        contract=2, state="degraded", reason=None, subject=server,
                        detail=(
                            f"{len(undocumented)} 个工具未在 README 中声明："
                            f"{'、'.join(undocumented)}。"
                        ),
                        evidence={"server": server, "undocumented": undocumented},
                    )
                )
            if not declared_missing and not undocumented:
                findings.append(
                    ContractFinding(
                        contract=2, state="satisfied", reason=None, subject=server,
                        detail=f"{server} 的 README 与运行时工具面一致（{len(actual)} 个）。",
                        evidence={"server": server, "tool_count": len(actual)},
                    )
                )

        return findings
