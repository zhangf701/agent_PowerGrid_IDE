"""T0 契约求值编排与缓存。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import GatewayConfig
from ..inventory import ToolInventory
from .model import ContractFinding, ReportSummary, summarize
from .registry import REGISTRY, EvaluatorRegistry


def cache_key(inv: ToolInventory) -> str:
    """由"工具面"派生 —— 工具名或 schema 变了，缓存即失效。"""
    payload = {
        "servers": list(inv.servers()),
        "tools": sorted(
            (t.server, t.name, json.dumps(t.input_schema, sort_keys=True, ensure_ascii=False))
            for t in inv.tools
        ),
        "failures": sorted((f.server, f.error) for f in inv.failures),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class T0Report:
    findings: tuple[ContractFinding, ...]
    summary: ReportSummary
    cache_key: str
    evaluated_at: str


class T0Cache:
    """内存缓存。磁盘持久化留待需要时再加（YAGNI）。"""

    def __init__(self) -> None:
        self._mem: dict[str, T0Report] = {}

    def get(self, key: str) -> T0Report | None:
        return self._mem.get(key)

    def put(self, report: T0Report) -> None:
        self._mem[report.cache_key] = report


async def evaluate_t0(
    inv: ToolInventory,
    cfg: GatewayConfig,
    *,
    registry: EvaluatorRegistry | None = None,
    cache: T0Cache | None = None,
) -> T0Report:
    """求值全部已注册的 T0 契约。

    单个求值器崩溃 → 记为该契约的 incident 未知；**绝不让整体失败**。
    依据 UI 规范 v1.2 §4.6.6 的失败语义：fail-loud but non-blocking。
    """
    reg = registry if registry is not None else REGISTRY
    key = cache_key(inv)

    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return hit

    findings: list[ContractFinding] = []

    for evaluator in reg.all():
        try:
            findings.extend(evaluator.evaluate(inv, cfg))
        except Exception as exc:  # noqa: BLE001 —— 见 docstring：降级而非中断
            findings.append(
                ContractFinding(
                    contract=evaluator.contract,
                    state="unknown",
                    reason="incident",
                    subject="*",
                    detail=(
                        f"契约 {evaluator.contract}（{evaluator.name}）的求值器崩溃："
                        f"{type(exc).__name__}: {exc}"[:200]
                    ),
                    evidence={"evaluator": evaluator.name, "error": repr(exc)[:400]},
                )
            )

    # 挂了但拿不到清单的 server 本身也是一条 incident
    for failure in inv.failures:
        findings.append(
            ContractFinding(
                contract=8, state="unknown", reason="incident", subject=failure.server,
                detail=f"server `{failure.server}` 未能拉起：{failure.error}",
                evidence={"server": failure.server, "error": failure.error},
            )
        )

    report = T0Report(
        findings=tuple(findings),
        summary=summarize(findings),
        cache_key=key,
        evaluated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    if cache is not None:
        cache.put(report)
    return report
