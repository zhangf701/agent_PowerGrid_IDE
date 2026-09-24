"""契约状态模型与汇总。

取值与汇总规则必须与《PowerMCP UI 设计规范》v1.2 §3.8 / §4.3 逐字一致：
前端与网关对"同一份契约数据"的汇总结论不能出现两个版本。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

KnownState = Literal["satisfied", "degraded", "violated"]
UnknownReason = Literal["structural", "incident"]
ContractState = Literal["satisfied", "degraded", "violated", "unknown"]

# 1–8，与方案 §2.2 及 tokens.json#contractTypes 一致
CONTRACT_NAMES: dict[int, str] = {
    1: "API 版本契约",
    2: "文档-实现一致性",
    3: "参数契约",
    4: "状态映射契约",
    5: "命名空间契约",
    6: "标识符契约",
    7: "量纲契约",
    8: "运行时依赖契约",
}

# 已知状态的严重度。unknown 不在此表 —— 它走双轨，不参与主徽标竞争
_KNOWN_SEVERITY: dict[KnownState, int] = {"satisfied": 0, "degraded": 1, "violated": 2}
_UNKNOWN_REASONS: frozenset[str] = frozenset({"structural", "incident"})


@dataclass(frozen=True)
class ContractFinding:
    contract: int
    state: ContractState
    reason: UnknownReason | None
    subject: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.contract not in CONTRACT_NAMES:
            raise ValueError(f"契约编号必须是 1–8，收到 {self.contract}")
        if self.state not in (*_KNOWN_SEVERITY, "unknown"):
            raise ValueError(f"未知的状态取值：{self.state!r}")
        if self.state == "unknown" and self.reason not in _UNKNOWN_REASONS:
            raise ValueError(
                f"state='unknown' 时必须给出 reason（structural/incident），收到 {self.reason!r}"
            )
        if self.state != "unknown" and self.reason is not None:
            raise ValueError(
                f"state={self.state!r} 不得携带 reason，收到 {self.reason!r}"
            )


@dataclass(frozen=True)
class ReportSummary:
    primary: KnownState | Literal["unknown", "incident"]
    structural_unknown: int
    incident_unknown: int


def summarize(findings: Iterable[ContractFinding]) -> ReportSummary:
    """双轨汇总 —— 与 UI 规范 §4.3 同规则。

    primary 的确定顺序：
      1. 有 incident 未知  → 'incident'          （整体不可信，必须喧宾夺主）
      2. 否则取已知项的最差 → violated > degraded > satisfied
      3. 无任何已知项      → 'unknown'           （绝不取 satisfied）
    structural 未知只计数，不参与 primary 竞争。
    """
    items = list(findings)
    structural = sum(1 for f in items if f.state == "unknown" and f.reason == "structural")
    incident = sum(1 for f in items if f.state == "unknown" and f.reason == "incident")

    if incident:
        return ReportSummary("incident", structural, incident)

    known = [f.state for f in items if f.state != "unknown"]
    if not known:
        return ReportSummary("unknown", structural, incident)

    worst = max(known, key=lambda s: _KNOWN_SEVERITY[s])  # type: ignore[index]
    return ReportSummary(worst, structural, incident)  # type: ignore[arg-type]
