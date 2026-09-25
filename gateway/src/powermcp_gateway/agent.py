"""网关侧 agent 循环：自然语言 → 多轮工具调用 → 回答。

★ 为什么循环在**网关侧**（2026-09-25 张老师裁决）：
  工具执行统一走 `proxy.call_tool`，因此 **契约 3 的 fail-closed 前置校验、
  契约 finding 的 EVIDENCE 发布、NDJSON 审计** 全部天然在环内。
  循环若放在前端，每次调用都要前端自己补这些 —— 且与「内核不含领域知识」冲突。

★ 工具名必须**带 server 前缀**（`server__tool`）：
  本项目实测存在**跨 server 同名工具**（`load_network` 在 pandapower / PyPSA / surge
  三者同名，另有 `add_bus` / `run_power_flow` / `run_contingency_analysis` 等）——
  这正是**契约 5（命名空间契约）**要处理的问题。不带前缀的裸工具名会让模型
  无法消歧，且 OpenAI 的函数名规范也不允许 `.`，故用 `__` 连接。

★ 失败语义：
  - LLM 调用失败（网络 / 超时 / HTTP 错）→ 产出 `error` 事件后**结束本轮**，不抛。
  - 单个工具执行失败 → **不中断循环**，把失败文本回填给模型让它自行调整。
  - 工具参数不是合法 JSON 对象 → 同上（回填错误文本），不算致命。
  - 轮次超限 → 产出 `error` 事件，**不静默截断**。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .inventory import ToolRecord
from .llm import ChatMessage, LlmError, OpenAICompatProvider, ToolCall
from .proxy import CallOutcome

logger = logging.getLogger(__name__)

#: 工具调用的最大轮次。超过即产出 `error` 事件（不静默截断）。
DEFAULT_MAX_ROUNDS = 8

#: OpenAI 函数名允许的最大长度
_MAX_FUNCTION_NAME = 64

#: 分隔 server 与 tool 的记号
SEP = "__"


def wire_name(server: str, tool: str) -> str:
    """`(server, tool)` → 模型可见的函数名。"""
    return f"{server}{SEP}{tool}"


@dataclass(frozen=True)
class AgentEvent:
    """agent 循环对外产出的事件。

    | kind | 含义 | 关键字段 |
    |---|---|---|
    | `text` | 文本增量（用于流式渲染） | `text` |
    | `tool_call` | 一次工具调用**已执行**（成功） | `server` `tool` `args` |
    | `tool_error` | 工具调用失败 / 参数非法 / 工具不存在 | `server` `tool` `detail` |
    | `final` | 本轮最终回答（完整文本） | `text` |
    | `error` | 本轮整体失败（LLM 错误 / 轮次超限） | `detail` |
    """

    kind: str
    text: str = ""
    server: str = ""
    tool: str = ""
    args: dict[str, Any] | None = None
    detail: str = ""


ExecuteTool = Callable[[str, str, dict[str, Any]], Awaitable[CallOutcome]]


def build_tools_payload(
    specs: Sequence[ToolRecord],
) -> tuple[list[dict[str, Any]], dict[str, ToolRecord]]:
    """构造 OpenAI `tools` 数组，并返回 `函数名 → ToolRecord` 的解析表。

    ★ 返回**映射表**而非让调用方按 `__` 反解函数名 —— 工具名本身可能含 `__`，
      反解会产生歧义。以构造期的表为准，是唯一无歧义的解析方式。

    ⚠️ 函数名超长（> 64）的工具**跳过并 warning**：发一个不合规的名字会被
      provider 直接拒掉整个请求，代价远大于少一个工具。
    """
    payload: list[dict[str, Any]] = []
    index: dict[str, ToolRecord] = {}
    for spec in specs:
        name = wire_name(spec.server, spec.name)
        if len(name) > _MAX_FUNCTION_NAME:
            logger.warning(
                "工具 %s.%s 的函数名 %r 超过 %d 字符，已跳过（避免整个请求被拒）",
                spec.server, spec.name, name, _MAX_FUNCTION_NAME,
            )
            continue
        if name in index:
            logger.warning("函数名冲突 %r，已跳过后者 %s.%s", name, spec.server, spec.name)
            continue
        index[name] = spec
        payload.append({
            "type": "function",
            "function": {
                "name": name,
                "description": spec.description or f"{spec.server}.{spec.name}",
                "parameters": spec.input_schema or {"type": "object", "properties": {}},
            },
        })
    return payload, index


def _content_text(outcome: CallOutcome) -> str:
    """把工具结果转成回填给模型的文本。

    ★ MCP 的内容是 `[{"type": "text", "text": ...}, ...]`；非 text 项与畸形项
      **安全跳过**（隔离坏输入，不让一个坏 item 打断整轮对话）。
      完全取不到文本时退回 JSON 摘要，**绝不返回空串**（空串会让模型以为工具没输出）。
    """
    if outcome.error:
        return f"[失败] {outcome.error}"
    content = (outcome.result or {}).get("content")
    parts: list[str] = []
    if isinstance(content, (list, tuple)):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
    if parts:
        return "\n".join(parts)
    if outcome.result is not None:
        return json.dumps(outcome.result, ensure_ascii=False)[:4000]
    return "[空结果] 工具未返回内容"


async def run_turn(
    provider: OpenAICompatProvider,
    messages: Sequence[ChatMessage],
    *,
    specs: Sequence[ToolRecord],
    execute: ExecuteTool,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> AsyncIterator[AgentEvent]:
    """跑完一轮对话（可能含多次工具调用）。

    Args:
        provider: LLM 适配器。
        messages: 历史消息（含本轮 user 消息）。
        specs: 可用工具。**为空则退化为纯对话**（不发 `tools` 字段）。
        execute: 工具执行器 —— 生产环境传 `proxy.call_tool` 的封装，
            因此契约校验与审计天然在环内。
        max_rounds: 工具调用轮次上限。

    Yields:
        `AgentEvent`（见其 docstring）。
    """
    convo: list[ChatMessage] = list(messages)
    tools_payload, index = build_tools_payload(specs)
    answer: list[str] = []

    for _round in range(1, max_rounds + 1):
        pending: tuple[ToolCall, ...] = ()
        try:
            async for chunk in provider.stream_chat(
                convo, tools=tools_payload or None,
            ):
                if chunk.text:
                    answer.append(chunk.text)
                    yield AgentEvent(kind="text", text=chunk.text)
                if chunk.tool_calls:
                    pending = chunk.tool_calls
        except LlmError as exc:
            # 已流出的文本保持已流出（客户端已渲染），此处只报整体失败。
            yield AgentEvent(kind="error", detail=str(exc))
            return

        if not pending:
            yield AgentEvent(kind="final", text="".join(answer))
            return

        convo.append(ChatMessage(role="assistant", content="", tool_calls=pending))

        for call in pending:
            spec = index.get(call.name)
            if spec is None:
                detail = (
                    f"模型请求了不存在的工具 `{call.name}`。"
                    f"可用工具须为 `server{SEP}tool` 形式。"
                )
                convo.append(ChatMessage(role="tool", content=detail, tool_call_id=call.id))
                yield AgentEvent(kind="tool_error", tool=call.name, detail=detail)
                continue

            args, parse_error = _parse_args(call.arguments)
            if parse_error is not None:
                convo.append(
                    ChatMessage(role="tool", content=parse_error, tool_call_id=call.id)
                )
                yield AgentEvent(
                    kind="tool_error", server=spec.server, tool=spec.name,
                    detail=parse_error,
                )
                continue

            try:
                outcome = await execute(spec.server, spec.name, args)
            except Exception as exc:  # 执行器自身故障不得打断整轮对话
                detail = f"工具执行器抛出异常：{type(exc).__name__}: {exc}"
                logger.warning("%s（%s.%s）", detail, spec.server, spec.name, exc_info=True)
                convo.append(ChatMessage(role="tool", content=detail, tool_call_id=call.id))
                yield AgentEvent(
                    kind="tool_error", server=spec.server, tool=spec.name,
                    args=args, detail=detail,
                )
                continue

            convo.append(
                ChatMessage(role="tool", content=_content_text(outcome), tool_call_id=call.id)
            )
            if outcome.ok:
                if getattr(outcome, "remounted", False):
                    # ★ 子项目 4：连接断裂自动重连后，server 进程是新的 ——
                      # 状态丢失必须说出来，否则用户会以为刚才载入的算例还在。
                    yield AgentEvent(kind="notice", detail=(
                        f"`{spec.server}` 进程中断后已自动重连 —— "
                        "**此前装载的算例 / 网络状态已丢失**，需要重新载入。"))
                yield AgentEvent(
                    kind="tool_call", server=spec.server, tool=spec.name, args=args,
                )
            else:
                yield AgentEvent(
                    kind="tool_error", server=spec.server, tool=spec.name, args=args,
                    detail=outcome.error or "工具返回失败",
                )

    yield AgentEvent(
        kind="error",
        detail=(
            f"已达工具调用轮次上限（{max_rounds} 轮）—— 本轮未得出最终回答。"
            f"若这是常态，说明任务需要拆小或提高 max_rounds。"
        ),
    )


def _parse_args(raw: str) -> tuple[dict[str, Any], str | None]:
    """解析模型给出的工具参数。

    Returns:
        `(args, None)` 成功；`( {}, 错误文本 )` 失败 —— 错误文本直接回填给模型。

    ★ 空串 / 纯空白视为**无参数**（部分 provider 对无参函数下发空串），
      但**非对象**的合法 JSON（如 `123` / `[]`）是错误 —— 契约 3 的
      `validate_args` 期望 dict，静默塞进去只会得到一条难以归因的违规。
    """
    text = (raw or "").strip()
    if not text:
        return {}, None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        return {}, f"工具参数不是合法 JSON：{exc}（原始内容：{text[:200]}）"
    if not isinstance(parsed, dict):
        return {}, (
            f"工具参数必须是 JSON 对象，实际是 {type(parsed).__name__}"
            f"（原始内容：{text[:200]}）"
        )
    return parsed, None
