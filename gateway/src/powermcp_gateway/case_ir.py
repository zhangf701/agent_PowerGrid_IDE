"""算例 → PowerIO IR 的解析与产物管理。

★ 这是**第一个真实拉起 MCP server 的单元**。实测（2026-09-25，`.superpowers/sdd/m11-live-parse.py`）：

  - 修复 env 透传后：`powerio.parse` 成功返回 59773 字符；
  - **反事实**：模拟修复前（`server_env()` 返回空）→ `is_error=True: Error executing tool parse`
    —— 证明那次修复是**必要**的，不是"恰好能跑"；
  - `parse` → IR → `diagnostics` 往返成功。

★ **PowerIO 的返回值是双层编码**，这点必须写清否则一定踩：
  `parse` 的文本是 JSON，其 `powerio_ir` 字段**又是一个 JSON 字符串**：

      {"value_type": "powerio.BalancedNetwork",
       "powerio_ir": "{\\n  \\"schema\\": \\"pio-ir\\", ...}"}

  故本模块**原样保存该字符串**（`ir` 字段），不做二次编解码 —— 任何"顺手解析一下"
  都会让 `diagnostics` 拿到错的东西。

★ **产物落盘**（`~/.powermcp_gateway/cases/<cid>/parse.json`）而不是每次重算：
  `parse` 要拉起 server（秒级），`diagnostics` 复用同一份 IR 才有意义。
  同时记录 `source_sha256` —— 源文件改了就让 IR 变**陈旧**，读取时如实报 `stale`。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cases import Case
from .config import GatewayConfig
from .inventory import build_inventory
from .proxy import call_tool

logger = logging.getLogger(__name__)

#: 产物文件名
ARTIFACT_NAME = "parse.json"

#: 解析算例用的 server 与工具
POWERIO = "powerio"
TOOL_PARSE = "parse"
TOOL_DIAGNOSTICS = "diagnostics"
TOOL_SUMMARIZE = "summarize"


class CaseIrError(RuntimeError):
    """解析或诊断失败 —— **引擎侧问题**（未拉起 / 工具报错），映射 502。"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class ParseArtifact:
    case_id: str
    source_path: str
    source_sha256: str
    parsed_at: str
    tool: str
    value_type: str
    ir: str                       # ★ 原样的 `powerio_ir`（JSON 字符串）
    ir_bytes: int


def artifact_dir(root: Path, case_id: str) -> Path:
    return root / case_id


def artifact_path(root: Path, case_id: str) -> Path:
    return artifact_dir(root, case_id) / ARTIFACT_NAME


def save_artifact(root: Path, payload: dict) -> Path:
    """原子写入产物（同 `CaseStore` 的取舍：不留半截文件）。"""
    path = artifact_path(root, str(payload.get("case_id", "")))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    import os
    os.replace(tmp, path)
    return path


def load_artifact(root: Path, case_id: str) -> dict | None:
    path = artifact_path(root, case_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # 产物损坏 = 需要重新解析；如实告警，不静默当成"没解析过"
        logger.warning("算例产物损坏，需重新解析：%s（%s）", path, exc)
        return None
    return data if isinstance(data, dict) else None


async def _call_powerio(cfg: GatewayConfig, tool: str, args: dict[str, Any]) -> dict:
    """经**生产路径**调用 powerio 工具（含契约 3 校验）。

    ⚠️ 每次都要 `build_inventory` 取声明的 schema（契约 3 的输入）——
      这是已知的 T6-M5 成本（每轮拉起 server）。此处无法回避：
      schema 必须来自 `list_tools` 的真实返回，硬编码就失去了契约 3 的意义。
    """
    try:
        inv = await build_inventory(cfg, [POWERIO])
    except Exception as exc:
        raise CaseIrError(f"无法构建 {POWERIO} 工具清单：{exc}") from exc

    recs = [t for t in inv.tools if t.server == POWERIO and t.name == tool]
    if not recs:
        failed = [f"{f.server}: {f.error}" for f in inv.failures]
        detail = f"（{'; '.join(failed)}）" if failed else ""
        raise CaseIrError(f"{POWERIO}.{tool} 不存在或 {POWERIO} 未拉起{detail}")

    outcome = await call_tool(cfg, POWERIO, tool, args, schema=recs[0].input_schema)
    if not outcome.ok:
        raise CaseIrError(outcome.error or f"{POWERIO}.{tool} 调用失败")
    return outcome.result or {}


def _text_of(result: dict) -> str:
    """从 MCP 结果提取纯文本（非 text 项与畸形项安全跳过）。"""
    content = result.get("content")
    if not isinstance(content, (list, tuple)):
        return ""
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
    return "\n".join(parts)


def _loads(text: str, what: str) -> dict:
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise CaseIrError(f"{what} 返回的不是合法 JSON：{exc}（前 200 字符：{text[:200]}）") from exc
    if not isinstance(obj, dict):
        raise CaseIrError(f"{what} 返回的不是 JSON 对象，而是 {type(obj).__name__}")
    return obj


async def parse_case(cfg: GatewayConfig, case: Case) -> ParseArtifact:
    """把算例解析为 PowerIO IR 并落盘。

    Raises:
        CaseIrError: powerio 未拉起 / 工具报错 / 返回不可解析。
    """
    result = await _call_powerio(cfg, TOOL_PARSE, {"path": case.source_path})
    payload = _loads(_text_of(result), f"{POWERIO}.{TOOL_PARSE}")

    ir = payload.get("powerio_ir")
    if not isinstance(ir, str) or not ir.strip():
        # 双层编码是 PowerIO 的实际形态；缺了它说明上游变了 —— 必须响亮
        raise CaseIrError(
            f"{POWERIO}.{TOOL_PARSE} 的返回缺少 `powerio_ir` 字符串字段"
            f"（顶层键：{sorted(payload)}）—— PowerIO 的返回形态可能已变"
        )

    return ParseArtifact(
        case_id=case.id,
        source_path=case.source_path,
        source_sha256=case.sha256,
        parsed_at=_now(),
        tool=f"{POWERIO}.{TOOL_PARSE}",
        value_type=str(payload.get("value_type", "")),
        ir=ir,
        ir_bytes=len(ir.encode("utf-8")),
    )


async def run_diagnostics(cfg: GatewayConfig, ir: str) -> dict:
    """用已解析的 IR 跑 `powerio.diagnostics`。"""
    result = await _call_powerio(cfg, TOOL_DIAGNOSTICS, {"powerio_ir": ir})
    return _loads(_text_of(result), f"{POWERIO}.{TOOL_DIAGNOSTICS}")


def artifact_to_payload(a: ParseArtifact) -> dict:
    return {
        "case_id": a.case_id,
        "source_path": a.source_path,
        "source_sha256": a.source_sha256,
        "parsed_at": a.parsed_at,
        "tool": a.tool,
        "value_type": a.value_type,
        "ir": a.ir,
        "ir_bytes": a.ir_bytes,
    }
