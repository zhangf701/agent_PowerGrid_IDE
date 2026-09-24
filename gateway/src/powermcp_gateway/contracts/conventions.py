"""契约 6 / 7：标识符与量纲约定。

**唯一真源是 design/tokens.json** —— 代码里不得硬编码引擎↔约定的绑定。
理由见《UI 设计规范》v1.2 §4.5：用显示名（PyPSA）代替 server id（pypsa）
会导致查表未命中、进而静默标错编号约定（该缺陷曾把跨引擎偏差放大 3.1 亿倍）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..config import GatewayConfig
from ..inventory import ToolInventory
from .model import ContractFinding

_CONVENTION_VALUES = {"0-based", "1-based", "unknown"}


def _default_tokens_path() -> Path:
    # gateway/src/powermcp_gateway/contracts/conventions.py -> 项目根
    return Path(__file__).resolve().parents[4] / "design" / "tokens.json"


@dataclass(frozen=True)
class Conventions:
    identifier: dict[str, str]
    suffix: dict[str, str]


def load_conventions(tokens_path: Path | None = None) -> Conventions:
    path = Path(tokens_path) if tokens_path is not None else _default_tokens_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    node = data.get("identifierConvention") or {}
    by_engine = dict(node.get("byEngine") or {})
    bad = {k: v for k, v in by_engine.items() if v not in _CONVENTION_VALUES}
    if bad:
        raise ValueError(f"{path} 中 byEngine 取值非法：{bad}")
    return Conventions(identifier=by_engine, suffix=dict(node.get("suffix") or {}))


class IdentifiersEvaluator:
    contract = 6
    name = "标识符契约"
    timeframe = "T0"

    def __init__(self, conventions: Conventions | None = None) -> None:
        self._c = conventions if conventions is not None else load_conventions()

    def evaluate(self, inv: ToolInventory, cfg: GatewayConfig) -> list[ContractFinding]:
        mounted = set(inv.servers())
        missing = sorted(mounted - set(self._c.identifier))
        unverified = sorted(s for s in mounted if self._c.identifier.get(s) == "unknown")

        findings: list[ContractFinding] = []

        if missing:
            findings.append(
                ContractFinding(
                    contract=6, state="degraded", reason=None, subject="*",
                    detail=(
                        f"{len(missing)} 个已挂载 server 没有编号约定绑定：{'、'.join(missing)}。"
                        f"这些引擎的标识符无法被安全归一。"
                    ),
                    evidence={"missing": missing, "source": "design/tokens.json"},
                )
            )
        if unverified:
            findings.append(
                ContractFinding(
                    contract=6, state="unknown", reason="structural", subject="*",
                    detail=(
                        f"{len(unverified)} 个 server 的编号约定**未实测**，界面显示"
                        f"「{self._c.suffix.get('unknown', '(约定未知)')}」：{'、'.join(unverified)}。"
                    ),
                    evidence={"unverified": unverified},
                )
            )
        if not missing and not unverified:
            findings.append(
                ContractFinding(
                    contract=6, state="satisfied", reason=None, subject="*",
                    detail=f"{len(mounted)} 个 server 的编号约定均已实测绑定。",
                    evidence={"bindings": {s: self._c.identifier[s] for s in sorted(mounted)}},
                )
            )
        return findings


class DimensionsEvaluator:
    """契约 7：量纲约定。T0 只校验约定表本身可用（逐值校验在 T2 / 前端）。"""

    contract = 7
    name = "量纲契约"
    timeframe = "T0"

    def __init__(self, conventions: Conventions | None = None) -> None:
        self._c = conventions if conventions is not None else load_conventions()

    def evaluate(self, inv: ToolInventory, cfg: GatewayConfig) -> list[ContractFinding]:
        if self._c.suffix:
            return [ContractFinding(
                contract=7, state="satisfied", reason=None, subject="*",
                detail="量纲/标识符约定表已加载；逐值校验在 T2 与前端执行。",
                evidence={"suffix_keys": sorted(self._c.suffix)},
            )]
        return [ContractFinding(
            contract=7, state="unknown", reason="structural", subject="*",
            detail="约定表缺少 suffix 定义，无法渲染归一标记。",
            evidence={},
        )]
