"""MCP 代理调用 —— 契约 3 的落地点。

★ 这里是唯一能"阻止"参数契约缺陷的位置：在把调用转发给引擎**之前**校验参数。
  校验不通过 → 不转发。fail-closed。
  理由：一个会被引擎静默忽略的调用，跑过去比不跑更危险 —— 它会产出一个
  "看起来成功、实际没生效"的结果，而那正是 original 缺陷（linearized）的形态。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .audit import AuditLog
from .config import GatewayConfig
from .contracts.params import ArgViolation, validate_args
from .session import Channel, EventBus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallOutcome:
    ok: bool
    server: str
    tool: str
    result: dict | None = None
    violations: tuple[ArgViolation, ...] = ()
    error: str | None = None


async def _dispatch(cfg: GatewayConfig, server: str, tool: str, args: dict) -> dict:
    """真正转发给 MCP server。单测里会被 monkeypatch 掉。

    ⚠️ **必须有超时**（与 `inventory.fetch_server_tools` 一致，复用同一个 `cfg.server_timeout_s`）：
      已知 opendss 的失效形态正是「裸 stdio 探针正常、经 SDK 握手挂起」——
      没有超时会让整个网关请求**永久挂住**，且调用方无从判断是慢还是死。
    """
    params = StdioServerParameters(
        command=str(cfg.python),
        args=["-m", "powermcp.cli", "run", server],
        cwd=str(cfg.powermcp_root),
    )
    async with asyncio.timeout(cfg.server_timeout_s):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments=args)
                return {"content": [c.model_dump() for c in result.content]}


def _emit(bus: EventBus | None, audit: AuditLog | None, session_id: str | None,
          kind: str, payload: dict) -> None:
    """把事件发到会话总线并落审计 —— **尽力而为，失败不得吞掉调用结果**。

    ⚠️ `EventBus.publish` 在总线已关闭时会 raise RuntimeError；`audit.append` 也可能因
      磁盘/权限失败。这两者**都不允许**让 `call_tool` 抛异常：
        - 成功路径上调用**已经执行**，结果必须交回调用者；
        - 违规路径上必须交出 fail-closed 的违规明细。
      否则契约 3「校验不通过 → 返回 ok=False 与违规明细」的承诺会被一次发布失败击穿。
      失败本身记 warning（**不静默**，可诊断）。
    """
    if bus is None or session_id is None:
        return
    try:
        event = bus.publish(Channel.EVIDENCE, kind, payload)
        if audit is not None:
            audit.append(session_id, event)
    except Exception:
        logger.warning(
            "事件发布/审计失败（kind=%s, session=%s）—— 调用结果仍会返回",
            kind, session_id, exc_info=True,
        )


async def call_tool(
    cfg: GatewayConfig,
    server: str,
    tool: str,
    args: dict[str, Any],
    *,
    schema: dict,
    bus: EventBus | None = None,
    audit: AuditLog | None = None,
    session_id: str | None = None,
) -> CallOutcome:
    violations = validate_args(schema, args)

    if violations:
        _emit(bus, audit, session_id, "contract_violation", {
            "contract": 3, "server": server, "tool": tool,
            "violations": [v.__dict__ for v in violations],
        })
        return CallOutcome(
            ok=False, server=server, tool=tool, violations=violations,
            error="; ".join(v.detail for v in violations),
        )

    try:
        result = await _dispatch(cfg, server, tool, args)
    except Exception as exc:  # 引擎失败要如实暴露，不吞
        _emit(bus, audit, session_id, "tool_error", {
            "server": server, "tool": tool, "error": f"{type(exc).__name__}: {exc}"[:300],
        })
        return CallOutcome(ok=False, server=server, tool=tool,
                           error=f"{type(exc).__name__}: {exc}"[:300])

    _emit(bus, audit, session_id, "tool_call", {
        "server": server, "tool": tool, "args": args,
    })
    return CallOutcome(ok=True, server=server, tool=tool, result=result)
