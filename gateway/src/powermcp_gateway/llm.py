"""LLM Provider 适配器（OpenAI 兼容）。

★ 为什么只做 **OpenAI 兼容**（2026-09-25 张老师裁决）：
  一个适配器覆盖 OpenAI / DeepSeek / 本地 vLLM / Ollama 的兼容模式，
  实现面与测试面最小；需要 Anthropic 原生或 Ollama 原生 API 时再各自新增适配器。

★ 为什么网关侧跑循环（同日裁决）：
  工具执行经 `proxy.call_tool`，**契约 3 的 fail-closed 校验天然在环内** ——
  循环若放在前端，每次工具调用都要前端自己补校验与审计，且与
  「内核不含领域知识」的约束冲突。

设计要点：
  - **流式**：`stream=True`，逐 chunk 解析 SSE；工具调用参数是**跨 chunk 累积**的，
    故由本模块负责累积，对外只暴露「文本增量」与「最终工具调用集」两种形态。
  - **坏输入隔离**：无法解析的 SSE 行**跳过并 warning**，不让一个畸形 chunk 打断整个回答。
  - **超时必须补上下文**：`asyncio.timeout` 抛出的 `TimeoutError` 消息为空，
    不补的话错误信息会退化成 `"TimeoutError: "`（与 `proxy._dispatch` 同一坑）。
  - **可离线测试**：`httpx.AsyncClient` 可注入（`httpx.MockTransport`），
    本模块自身不发真实网络请求。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

#: 环境变量名（前缀 POWERMCP_LLM_）
ENV_BASE_URL = "POWERMCP_LLM_BASE_URL"
ENV_API_KEY = "POWERMCP_LLM_API_KEY"
ENV_MODEL = "POWERMCP_LLM_MODEL"
ENV_TIMEOUT_S = "POWERMCP_LLM_TIMEOUT_S"


class LlmConfigError(RuntimeError):
    """LLM 配置缺失或非法。**fail-loud** —— 不静默退回默认值。"""


class LlmError(RuntimeError):
    """LLM 调用失败（HTTP 错误 / 超时 / 响应不可解析）。"""


@dataclass(frozen=True)
class LlmConfig:
    base_url: str
    api_key: str
    model: str
    timeout_s: float = 120.0

    def __post_init__(self) -> None:
        for name, value in (("base_url", self.base_url), ("model", self.model)):
            if not isinstance(value, str) or not value.strip():
                raise LlmConfigError(f"LLM 配置项 `{name}` 不能为空")
        if not isinstance(self.timeout_s, (int, float)) or self.timeout_s <= 0:
            raise LlmConfigError("LLM 配置项 `timeout_s` 必须为正数")

    @property
    def chat_url(self) -> str:
        """拼接 chat completions 端点。

        ⚠️ `base_url` **需自带 `/v1`**（若该 provider 要求）——
        本模块只做「去掉尾部斜杠 + 追加 `/chat/completions`」，不做路径猜测。
        """
        return self.base_url.rstrip("/") + "/chat/completions"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LlmConfig":
        """从环境变量读取配置。

        ★ **缺任一必需项即抛 `LlmConfigError`**（fail-loud）：静默用一个假默认值
          会让用户以为"配好了"，直到第一次调用才失败 —— 那正是本项目反复否掉的
          静默 fail-open 形态。
        ★ `api_key` 允许为空串（本地 vLLM / Ollama 通常不校验），但**必须显式设置**
          —— 区分「没配」与「有意留空」。
        """
        e = os.environ if env is None else env
        missing = [k for k in (ENV_BASE_URL, ENV_API_KEY, ENV_MODEL) if k not in e]
        if missing:
            raise LlmConfigError(
                "LLM 配置缺失：" + "、".join(missing)
                + "（需设置 POWERMCP_LLM_BASE_URL / _API_KEY / _MODEL）"
            )
        raw_timeout = e.get(ENV_TIMEOUT_S)
        try:
            timeout_s = float(raw_timeout) if raw_timeout not in (None, "") else 120.0
        except (TypeError, ValueError) as exc:
            raise LlmConfigError(
                f"{ENV_TIMEOUT_S} 不是合法数字：{raw_timeout!r}"
            ) from exc
        return cls(
            base_url=e[ENV_BASE_URL], api_key=e[ENV_API_KEY],
            model=e[ENV_MODEL], timeout_s=timeout_s,
        )


@dataclass(frozen=True)
class ToolCall:
    """模型请求的一次工具调用。

    `arguments` 保留**原始 JSON 字符串**（不做解析）—— 解析失败是 agent 的职责，
    且把解析放在这里会让"模型给了畸形参数"这一可诊断事实变成一个不可见的默认值。
    """

    id: str
    name: str
    arguments: str = ""


@dataclass(frozen=True)
class ChatMessage:
    role: str                                   # system | user | assistant | tool
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class Chunk:
    """流式增量。

    ★ 两种形态**互斥**，由 `tool_calls` 是否非空区分：
      - `text` 非空、`tool_calls` 为空 → 文本增量（用于流式渲染）
      - `text` 为空、`tool_calls` 非空 → **本轮流结束**，模型请求工具调用
        （由本模块累积完毕后**一次性**产出，agent 无需自己拼参数片段）
    """

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None


def _to_wire(msg: ChatMessage) -> dict[str, Any]:
    """`ChatMessage` → OpenAI 线格式。`content` **总是**出现（空串可接受），
    避免不同 provider 对缺字段的处理差异。"""
    out: dict[str, Any] = {"role": msg.role, "content": msg.content}
    if msg.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": tc.arguments},
            }
            for tc in msg.tool_calls
        ]
    if msg.tool_call_id:
        out["tool_call_id"] = msg.tool_call_id
    return out


@dataclass
class _ToolCallAccum:
    """跨 chunk 累积一次工具调用（OpenAI 按 `index` 分片下发）。"""

    id: str = ""
    name: str = ""
    arguments: str = ""


class OpenAICompatProvider:
    """OpenAI 兼容 chat completions 的流式客户端。

    ⚠️ 本类**不**做重试：重试策略属于上层（agent / 进程监管）。
      在流式响应上盲目重试会重复已经产生的副作用。
    """

    def __init__(self, cfg: LlmConfig, *, client: httpx.AsyncClient | None = None) -> None:
        self._cfg = cfg
        self._client = client
        self._owns_client = client is None

    @property
    def model(self) -> str:
        return self._cfg.model

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            # 超时在 stream_chat 里用 asyncio.timeout 统一兜底；
            # 这里给 httpx 一个宽松值，避免两套超时互相打断。
            self._client = httpx.AsyncClient(timeout=None)
        return self._client

    async def aclose(self) -> None:
        """只关闭**自己创建**的 client —— 注入的 client 由调用方负责。"""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> AsyncIterator[Chunk]:
        """流式对话。

        Yields:
            `Chunk(text=...)` 文本增量；若模型请求工具调用，则**最后**产出
            一个 `Chunk(tool_calls=..., finish_reason="tool_calls")`。

        Raises:
            LlmError: HTTP 非 2xx、超时、或流中断。
        """
        payload: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": [_to_wire(m) for m in messages],
            "stream": True,
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }

        accums: dict[int, _ToolCallAccum] = {}
        finish_reason: str | None = None

        try:
            async with asyncio.timeout(self._cfg.timeout_s):
                async with self._http().stream(
                    "POST", self._cfg.chat_url, json=payload, headers=headers,
                ) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", "replace")
                        raise LlmError(
                            f"LLM 返回 HTTP {resp.status_code}：{body[:300]}"
                        )
                    async for line in resp.aiter_lines():
                        parsed = _parse_sse_line(line)
                        if parsed is None:
                            continue
                        if parsed is _DONE:
                            break
                        delta = _first_delta(parsed)
                        if delta is None:
                            continue
                        if isinstance(delta.get("finish_reason"), str):
                            finish_reason = delta["finish_reason"]
                        text = delta.get("content")
                        if isinstance(text, str) and text:
                            yield Chunk(text=text)
                        _accumulate_tool_calls(delta.get("tool_calls"), accums)
        except LlmError:
            raise
        except Exception as exc:
            if _is_timeout(exc):
                raise LlmError(
                    f"LLM 在 {self._cfg.timeout_s:g}s 内未完成响应（model={self._cfg.model}）—— "
                    f"可能是网络不可达、模型过慢，或 base_url 指向了不存在的端点"
                ) from exc
            raise LlmError(f"LLM 调用失败：{type(exc).__name__}: {exc}") from exc

        if accums:
            calls = tuple(
                ToolCall(id=a.id, name=a.name, arguments=a.arguments)
                for _, a in sorted(accums.items())
            )
            yield Chunk(tool_calls=calls, finish_reason=finish_reason or "tool_calls")


#: SSE 结束哨兵（模块私有，仅用于内部比较）
_DONE = object()


def _parse_sse_line(line: str) -> dict | None | object:
    """解析一行 SSE。

    Returns:
        `None` → 忽略（空行 / 注释 / 畸形 JSON）
        `_DONE` → 流结束哨兵
        `dict`  → 已解析的 JSON 对象
    """
    line = line.strip()
    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None
    data = line[len("data:"):].strip()
    if data == "[DONE]":
        return _DONE
    try:
        obj = json.loads(data)
    except (json.JSONDecodeError, ValueError):
        # 坏输入隔离：一个畸形 chunk 不得打断整个回答（但要可见）
        logger.warning("跳过无法解析的 SSE 数据行：%r", data[:120])
        return None
    return obj if isinstance(obj, dict) else None


def _first_delta(obj: dict) -> dict | None:
    """取 `choices[0].delta`；结构不符时返回 None（不抛）。"""
    choices = obj.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    delta = first.get("delta")
    if isinstance(delta, dict):
        return delta
    # 非流式回退形态：choices[0].message（部分兼容实现会这样返回）
    message = first.get("message")
    if isinstance(message, dict):
        out = dict(message)
        fr = first.get("finish_reason")
        if isinstance(fr, str):
            out["finish_reason"] = fr
        return out
    return None


def _accumulate_tool_calls(raw: Any, accums: dict[int, _ToolCallAccum]) -> None:
    """把 `delta.tool_calls` 累积进 `accums`（按 index 分片）。

    OpenAI 的流式工具调用形如：
      {"index":0,"id":"call_1","function":{"name":"foo","arguments":"{\\"a\\""}}
      {"index":0,"function":{"arguments":":1}"}}
    故 `id` / `name` 只在首片出现，`arguments` 逐片拼接。
    """
    if not isinstance(raw, list):
        return
    for item in raw:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        if not isinstance(idx, int):
            idx = 0
        slot = accums.setdefault(idx, _ToolCallAccum())
        cid = item.get("id")
        if isinstance(cid, str) and cid:
            slot.id = cid
        fn = item.get("function")
        if isinstance(fn, dict):
            name = fn.get("name")
            if isinstance(name, str) and name:
                slot.name = name
            args = fn.get("arguments")
            if isinstance(args, str):
                slot.arguments += args


def _is_timeout(exc: BaseException) -> bool:
    """判断异常（含 ExceptionGroup 嵌套）是否由超时引起。

    与 `proxy._is_timeout` / `inventory._is_timeout` 逻辑相同 —— 这是**第三处**消费者。
    `proxy.py` 的注释写明「若出现第三处消费者，再提取共享模块」——
    故此处**有意重复**，并把提取共享模块列入后续待办（见 `docs/journal`）。
    """
    if isinstance(exc, TimeoutError):
        return True
    for sub in getattr(exc, "exceptions", ()) or ():
        if _is_timeout(sub):
            return True
    return False
