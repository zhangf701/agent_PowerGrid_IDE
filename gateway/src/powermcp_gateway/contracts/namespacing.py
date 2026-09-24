"""契约 5：命名空间。

跨 server 的工具重名。PowerMCP 有约 250 个工具分布在 9 个 server 上，
重名在语义上可能相同也可能完全不同 —— 后者会让"调用了哪个"变得不可判定。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..config import GatewayConfig
from ..inventory import ToolInventory
from .model import ContractFinding


def schema_fingerprint(schema: dict[str, Any]) -> str:
    """对 input_schema 做稳定哈希 —— 键序无关，但类型差异必须体现。"""

    def normalise(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: normalise(v) for k, v in sorted(node.items())}
        if isinstance(node, list):
            return [normalise(v) for v in node]
        return node

    blob = json.dumps(normalise(schema), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class NamespacingEvaluator:
    contract = 5
    name = "命名空间契约"
    timeframe = "T0"

    def evaluate(self, inv: ToolInventory, cfg: GatewayConfig) -> list[ContractFinding]:
        findings: list[ContractFinding] = []

        for name in sorted({t.name for t in inv.tools}):
            hits = inv.by_name(name)
            if len(hits) < 2:
                continue

            servers = sorted(t.server for t in hits)
            prints = {schema_fingerprint(t.input_schema) for t in hits}
            same = len(prints) == 1

            findings.append(
                ContractFinding(
                    contract=5,
                    state="degraded",
                    reason=None,
                    subject=name,
                    detail=(
                        f"工具 `{name}` 在 {len(servers)} 个 server 中同名："
                        f"{'、'.join(servers)}；"
                        + ("入参 schema 一致。" if same else "**入参 schema 不同** —— 同名不同义，易误调用。")
                    ),
                    evidence={
                        "tool": name,
                        "servers": servers,
                        "schemas_match": same,
                        "fingerprints": {t.server: schema_fingerprint(t.input_schema) for t in hits},
                    },
                )
            )

        if not findings:
            findings.append(
                ContractFinding(
                    contract=5,
                    state="satisfied",
                    reason=None,
                    subject="*",
                    detail=f"已挂载 {len(inv.servers())} 个 server，无跨 server 工具重名。",
                    evidence={"servers": list(inv.servers()), "tool_count": len(inv.tools)},
                )
            )
        return findings
