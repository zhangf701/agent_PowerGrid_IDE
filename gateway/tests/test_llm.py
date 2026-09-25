"""`llm.py` 的测试。

★ 全部**离线**：用 `httpx.MockTransport` 注入传输层，不发任何真实网络请求。
★ 重点覆盖**错误路径**（本项目周期教训：高价值修复集中在错误路径，
  而恰恰错误路径的覆盖最差）—— HTTP 错误、超时补上下文、畸形 SSE 行、
  非流式回退形态、client 所有权。
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from powermcp_gateway.llm import (
    ENV_API_KEY,
    ENV_BASE_URL,
    ENV_MODEL,
    ENV_TIMEOUT_S,
    ChatMessage,
    LlmConfig,
    LlmConfigError,
    LlmError,
    OpenAICompatProvider,
    ToolCall,
)

_BASE_ENV = {
    ENV_BASE_URL: "https://api.example.com/v1",
    ENV_API_KEY: "sk-test",
    ENV_MODEL: "test-model",
}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _sse(*objs: dict | str) -> bytes:
    """构造 SSE 响应体。字符串原样作为 data 行（用于 [DONE] 与畸形行）。"""
    parts = []
    for o in objs:
        payload = o if isinstance(o, str) else json.dumps(o, ensure_ascii=False)
        parts.append(f"data: {payload}\n\n")
    return "".join(parts).encode("utf-8")


def _text_delta(text: str) -> dict:
    return {"choices": [{"delta": {"content": text}, "finish_reason": None}]}


async def _collect(provider: OpenAICompatProvider, **kw):
    return [c async for c in provider.stream_chat(**kw)]


# ---------------------------------------------------------------- 配置


def test_config_from_env_reads_all_fields():
    cfg = LlmConfig.from_env(dict(_BASE_ENV))
    assert cfg.base_url == "https://api.example.com/v1"
    assert cfg.model == "test-model"
    assert cfg.timeout_s == 120.0


def test_config_missing_env_is_fail_loud():
    for drop in (ENV_BASE_URL, ENV_API_KEY, ENV_MODEL):
        env = {k: v for k, v in _BASE_ENV.items() if k != drop}
        with pytest.raises(LlmConfigError) as ei:
            LlmConfig.from_env(env)
        assert drop in str(ei.value)


def test_config_allows_explicitly_empty_api_key():
    """本地 vLLM / Ollama 常不校验 key —— 允许空串，但必须**显式设置**。"""
    env = dict(_BASE_ENV, **{ENV_API_KEY: ""})
    assert LlmConfig.from_env(env).api_key == ""


def test_config_rejects_non_numeric_timeout():
    env = dict(_BASE_ENV, **{ENV_TIMEOUT_S: "abc"})
    with pytest.raises(LlmConfigError) as ei:
        LlmConfig.from_env(env)
    assert ENV_TIMEOUT_S in str(ei.value)


def test_config_rejects_empty_model():
    with pytest.raises(LlmConfigError):
        LlmConfig(base_url="https://x/v1", api_key="k", model="   ")


def test_chat_url_strips_trailing_slash():
    a = LlmConfig(base_url="https://x/v1/", api_key="k", model="m")
    b = LlmConfig(base_url="https://x/v1", api_key="k", model="m")
    assert a.chat_url == b.chat_url == "https://x/v1/chat/completions"


# ---------------------------------------------------------------- 流式文本


async def test_streams_text_deltas():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(
            _text_delta("你好"), _text_delta("，"), _text_delta("世界"), "[DONE]",
        ))

    p = OpenAICompatProvider(LlmConfig.from_env(dict(_BASE_ENV)), client=_client(handler))
    chunks = await _collect(p, messages=[ChatMessage(role="user", content="hi")])
    assert "".join(c.text for c in chunks) == "你好，世界"
    assert all(not c.tool_calls for c in chunks)


async def test_request_payload_shape():
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=_sse("[DONE]"))

    p = OpenAICompatProvider(LlmConfig.from_env(dict(_BASE_ENV)), client=_client(handler))
    await _collect(p, messages=[ChatMessage(role="user", content="hi")])

    assert seen["url"] == "https://api.example.com/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["model"] == "test-model"
    assert seen["body"]["stream"] is True
    assert seen["body"]["messages"] == [{"role": "user", "content": "hi"}]


async def test_tools_are_sent_with_auto_choice():
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=_sse("[DONE]"))

    p = OpenAICompatProvider(LlmConfig.from_env(dict(_BASE_ENV)), client=_client(handler))
    await _collect(
        p,
        messages=[ChatMessage(role="user", content="hi")],
        tools=[{"type": "function", "function": {"name": "f"}}],
    )
    assert seen["body"]["tools"][0]["function"]["name"] == "f"
    assert seen["body"]["tool_choice"] == "auto"


# ---------------------------------------------------------------- 工具调用累积


async def test_accumulates_tool_call_across_chunks():
    """OpenAI 按 index 分片下发工具调用：id/name 只在首片，arguments 逐片拼接。"""
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "call_a", "function": {"name": "run", "arguments": '{"a"'}}
            ]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": ":1}"}}
            ]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            "[DONE]",
        ))

    p = OpenAICompatProvider(LlmConfig.from_env(dict(_BASE_ENV)), client=_client(handler))
    chunks = await _collect(p, messages=[ChatMessage(role="user", content="hi")])

    tool_chunks = [c for c in chunks if c.tool_calls]
    assert len(tool_chunks) == 1, "工具调用必须**一次性**产出，不得逐片外泄"
    (call,) = tool_chunks[0].tool_calls
    assert (call.id, call.name, call.arguments) == ("call_a", "run", '{"a":1}')
    assert tool_chunks[0].finish_reason == "tool_calls"


async def test_parallel_tool_calls_ordered_by_index():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(
            {"choices": [{"delta": {"tool_calls": [
                {"index": 1, "id": "b", "function": {"name": "second", "arguments": "{}"}}
            ]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "a", "function": {"name": "first", "arguments": "{}"}}
            ]}}]},
            "[DONE]",
        ))

    p = OpenAICompatProvider(LlmConfig.from_env(dict(_BASE_ENV)), client=_client(handler))
    chunks = await _collect(p, messages=[ChatMessage(role="user", content="hi")])
    (tc,) = [c for c in chunks if c.tool_calls]
    assert [t.name for t in tc.tool_calls] == ["first", "second"]


async def test_tool_call_wire_round_trip():
    """assistant 消息里的 tool_calls 与 tool 消息的 tool_call_id 必须上线。"""
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=_sse("[DONE]"))

    p = OpenAICompatProvider(LlmConfig.from_env(dict(_BASE_ENV)), client=_client(handler))
    await _collect(p, messages=[
        ChatMessage(role="user", content="hi"),
        ChatMessage(role="assistant", content="", tool_calls=(
            ToolCall(id="call_a", name="run", arguments='{"a":1}'),
        )),
        ChatMessage(role="tool", content="ok", tool_call_id="call_a"),
    ])
    msgs = seen["body"]["messages"]
    assert msgs[1]["tool_calls"][0] == {
        "id": "call_a", "type": "function",
        "function": {"name": "run", "arguments": '{"a":1}'},
    }
    assert msgs[2]["tool_call_id"] == "call_a"


# ---------------------------------------------------------------- 错误路径


async def test_http_error_raises_with_status_and_body():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b'{"error":"bad key"}')

    p = OpenAICompatProvider(LlmConfig.from_env(dict(_BASE_ENV)), client=_client(handler))
    with pytest.raises(LlmError) as ei:
        await _collect(p, messages=[ChatMessage(role="user", content="hi")])
    assert "401" in str(ei.value) and "bad key" in str(ei.value)


async def test_malformed_sse_line_is_skipped_not_fatal():
    """坏输入隔离：一个畸形 chunk 不得打断整个回答，但必须 warning 可见。"""
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(
            _text_delta("前"), "{这不是 JSON", _text_delta("后"), "[DONE]",
        ))

    p = OpenAICompatProvider(LlmConfig.from_env(dict(_BASE_ENV)), client=_client(handler))
    chunks = await _collect(p, messages=[ChatMessage(role="user", content="hi")])
    assert "".join(c.text for c in chunks) == "前后"


async def test_timeout_error_carries_context():
    """★ `asyncio.timeout` 的 TimeoutError 消息为空 —— 必须补上下文。"""
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1.0)
        return httpx.Response(200, content=_sse("[DONE]"))

    cfg = LlmConfig(base_url="https://x/v1", api_key="k", model="m", timeout_s=0.05)
    p = OpenAICompatProvider(cfg, client=_client(handler))
    with pytest.raises(LlmError) as ei:
        await _collect(p, messages=[ChatMessage(role="user", content="hi")])
    msg = str(ei.value)
    assert "0.05" in msg and "m" in msg, f"超时错误必须带上下文，实际：{msg!r}"


async def test_non_dict_json_line_is_ignored():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse("12345", _text_delta("ok"), "[DONE]"))

    p = OpenAICompatProvider(LlmConfig.from_env(dict(_BASE_ENV)), client=_client(handler))
    chunks = await _collect(p, messages=[ChatMessage(role="user", content="hi")])
    assert "".join(c.text for c in chunks) == "ok"


async def test_non_streaming_message_fallback():
    """部分兼容实现不返回 delta 而返回 message —— 必须仍能取到内容。"""
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(
            {"choices": [{"message": {"role": "assistant", "content": "回退"}, "finish_reason": "stop"}]},
            "[DONE]",
        ))

    p = OpenAICompatProvider(LlmConfig.from_env(dict(_BASE_ENV)), client=_client(handler))
    chunks = await _collect(p, messages=[ChatMessage(role="user", content="hi")])
    assert "".join(c.text for c in chunks) == "回退"


# ---------------------------------------------------------------- 资源所有权


async def test_aclose_does_not_close_injected_client():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse("[DONE]"))

    injected = _client(handler)
    p = OpenAICompatProvider(LlmConfig.from_env(dict(_BASE_ENV)), client=injected)
    await p.aclose()
    assert not injected.is_closed, "注入的 client 归调用方所有，不得代为关闭"
    await injected.aclose()
