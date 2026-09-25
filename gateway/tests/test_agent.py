"""`agent.py` 的测试。

★ 全部离线：用 `FakeProvider` 脚本化 LLM 的每一轮流式输出，工具执行器为本地桩。
★ 重点覆盖**错误路径**：工具不存在 / 参数非法 / 执行器抛异常 / LLM 失败 / 轮次超限。
"""

from __future__ import annotations

import json

from powermcp_gateway.agent import (
    build_tools_payload,
    run_turn,
    wire_name,
)
from powermcp_gateway.inventory import ToolRecord
from powermcp_gateway.llm import ChatMessage, Chunk, LlmError, ToolCall
from powermcp_gateway.proxy import CallOutcome


def _spec(server: str, name: str, **kw) -> ToolRecord:
    return ToolRecord(
        server=server, name=name,
        description=kw.get("description", f"{name} 的描述"),
        input_schema=kw.get("input_schema", {"type": "object", "properties": {}}),
        output_schema=None,
    )


def _call(name: str, arguments: str = "{}", cid: str = "c1") -> ToolCall:
    return ToolCall(id=cid, name=name, arguments=arguments)


def _tool_chunk(*calls: ToolCall) -> Chunk:
    return Chunk(tool_calls=calls, finish_reason="tool_calls")


class FakeProvider:
    """按脚本逐轮产出 chunk。脚本用尽后返回空流（等价于「无工具调用 → 收尾」）。"""

    def __init__(self, script: list[list[Chunk]]) -> None:
        self._script = list(script)
        self.calls: list[dict] = []

    async def stream_chat(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        chunks = self._script.pop(0) if self._script else []
        for c in chunks:
            yield c


class RaisingProvider:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def stream_chat(self, messages, tools=None):
        raise self._exc
        yield  # pragma: no cover —— 使其成为异步生成器


async def _run(provider, specs=(), execute=None, messages=None, max_rounds=8):
    events = []
    async for e in run_turn(
        provider,
        messages or [ChatMessage(role="user", content="hi")],
        specs=list(specs),
        execute=execute or _ok_executor,
        max_rounds=max_rounds,
    ):
        events.append(e)
    return events


async def _ok_executor(server: str, tool: str, args: dict) -> CallOutcome:
    return CallOutcome(
        ok=True, server=server, tool=tool,
        result={"is_error": False, "content": [{"type": "text", "text": "工具输出"}]},
    )


def _kinds(events) -> list[str]:
    return [e.kind for e in events]


# ---------------------------------------------------------------- 工具清单构造


def test_wire_name_prefixes_server():
    """★ 跨 server 同名工具必须可消歧（契约 5）——`load_network` 在三个 server 都有。"""
    assert wire_name("pypsa", "load_network") == "pypsa__load_network"
    assert wire_name("surge", "load_network") != wire_name("pypsa", "load_network")


def test_build_tools_payload_shape_and_index():
    specs = [_spec("surge", "run_n1_branch_contingency", description="N-1 扫描")]
    payload, index = build_tools_payload(specs)
    fn = payload[0]["function"]
    assert fn["name"] == "surge__run_n1_branch_contingency"
    assert fn["description"] == "N-1 扫描"
    assert fn["parameters"] == {"type": "object", "properties": {}}
    assert index["surge__run_n1_branch_contingency"] is specs[0]


def test_missing_schema_falls_back_to_empty_object():
    specs = [ToolRecord(server="s", name="t", description=None, input_schema={}, output_schema=None)]
    payload, _ = build_tools_payload(specs)
    assert payload[0]["function"]["parameters"] == {"type": "object", "properties": {}}
    assert payload[0]["function"]["description"] == "s.t"


def test_oversize_function_name_is_skipped():
    """函数名超 64 字符会被 provider 拒掉**整个请求** —— 必须跳过该工具而非照发。"""
    long_tool = _spec("s", "t" * 70)
    short = _spec("s", "ok")
    payload, index = build_tools_payload([long_tool, short])
    assert [p["function"]["name"] for p in payload] == ["s__ok"]
    assert "s__ok" in index


def test_duplicate_wire_name_keeps_first():
    a = _spec("s", "t")
    b = _spec("s", "t")
    payload, index = build_tools_payload([a, b])
    assert len(payload) == 1
    assert index["s__t"] is a


# ---------------------------------------------------------------- 纯对话


async def test_plain_conversation_yields_text_then_final():
    p = FakeProvider([[Chunk(text="你"), Chunk(text="好")]])
    events = await _run(p)
    assert _kinds(events) == ["text", "text", "final"]
    assert events[-1].text == "你好"


async def test_empty_specs_sends_no_tools_field():
    """无可用工具时退化为纯对话 —— 不发 `tools`，避免模型被诱导去调不存在的工具。"""
    p = FakeProvider([[Chunk(text="hi")]])
    await _run(p, specs=[])
    assert p.calls[0]["tools"] is None


# ---------------------------------------------------------------- 工具调用


async def test_tool_call_round_trip():
    p = FakeProvider([
        [Chunk(text="我来查一下。"), _tool_chunk(_call("surge__run_power_flow", '{"net": 1}'))],
        [Chunk(text="结果是 1.02 pu。")],
    ])
    seen: list[tuple] = []

    async def exec_(server, tool, args):
        seen.append((server, tool, args))
        return await _ok_executor(server, tool, args)

    events = await _run(p, specs=[_spec("surge", "run_power_flow")], execute=exec_)

    assert seen == [("surge", "run_power_flow", {"net": 1})]
    assert _kinds(events) == ["text", "tool_call", "text", "final"]
    assert events[-1].text == "我来查一下。结果是 1.02 pu。"
    # 第二轮请求必须带上 assistant 的 tool_calls 与 role=tool 的回填
    second = p.calls[1]["messages"]
    assert second[-2].role == "assistant" and second[-2].tool_calls[0].name == "surge__run_power_flow"
    assert second[-1].role == "tool" and second[-1].tool_call_id == "c1"
    assert second[-1].content == "工具输出"


async def test_parallel_tool_calls_are_all_executed():
    p = FakeProvider([
        [_tool_chunk(_call("s__a", "{}", "c1"), _call("s__b", "{}", "c2"))],
        [Chunk(text="done")],
    ])
    seen: list[str] = []

    async def exec_(server, tool, args):
        seen.append(tool)
        return await _ok_executor(server, tool, args)

    events = await _run(p, specs=[_spec("s", "a"), _spec("s", "b")], execute=exec_)
    assert seen == ["a", "b"]
    assert _kinds(events) == ["tool_call", "tool_call", "text", "final"]


async def test_unknown_tool_is_reported_and_loop_continues():
    """模型可能编造工具名 —— 必须如实回填并让它自行调整，不得中断整轮。"""
    p = FakeProvider([
        [_tool_chunk(_call("nonexistent__tool", "{}"))],
        [Chunk(text="抱歉，我改用 surge。")],
    ])
    events = await _run(p, specs=[_spec("surge", "run_power_flow")])
    assert _kinds(events) == ["tool_error", "text", "final"]
    assert events[0].kind == "tool_error"
    assert "不存在的工具" in events[0].detail
    # 错误文本必须回填给模型
    assert "不存在的工具" in p.calls[1]["messages"][-1].content


async def test_malformed_args_are_reported_not_fatal():
    p = FakeProvider([
        [_tool_chunk(_call("s__t", "{这不是 JSON"))],
        [Chunk(text="重试成功")],
    ])
    events = await _run(p, specs=[_spec("s", "t")])
    assert _kinds(events) == ["tool_error", "text", "final"]
    assert "不是合法 JSON" in events[0].detail


async def test_non_object_args_are_rejected():
    """`123` / `[]` 是合法 JSON 但不是对象 —— 静默塞进 validate_args 只会得到难归因的违规。"""
    p = FakeProvider([
        [_tool_chunk(_call("s__t", "123"))],
        [Chunk(text="ok")],
    ])
    events = await _run(p, specs=[_spec("s", "t")])
    assert _kinds(events) == ["tool_error", "text", "final"]
    assert "必须是 JSON 对象" in events[0].detail


async def test_blank_args_mean_no_arguments():
    p = FakeProvider([
        [_tool_chunk(_call("s__t", "   "))],
        [Chunk(text="ok")],
    ])
    seen: list[dict] = []

    async def exec_(server, tool, args):
        seen.append(args)
        return await _ok_executor(server, tool, args)

    await _run(p, specs=[_spec("s", "t")], execute=exec_)
    assert seen == [{}]


async def test_tool_failure_does_not_break_loop():
    """工具失败（ok=False）→ tool_error，但循环继续，最终回答仍产出。"""
    p = FakeProvider([
        [_tool_chunk(_call("s__t", "{}"))],
        [Chunk(text="工具挂了，但我仍给出结论。")],
    ])

    async def failing(server, tool, args):
        return CallOutcome(ok=False, server=server, tool=tool, error="solver diverged")

    events = await _run(p, specs=[_spec("s", "t")], execute=failing)
    assert _kinds(events) == ["tool_error", "text", "final"]
    assert events[0].detail == "solver diverged"
    assert "solver diverged" in p.calls[1]["messages"][-1].content


async def test_executor_exception_is_contained():
    p = FakeProvider([
        [_tool_chunk(_call("s__t", "{}"))],
        [Chunk(text="ok")],
    ])

    async def boom(server, tool, args):
        raise RuntimeError("executor 自身炸了")

    events = await _run(p, specs=[_spec("s", "t")], execute=boom)
    assert _kinds(events) == ["tool_error", "text", "final"]
    assert "executor 自身炸了" in events[0].detail


# ---------------------------------------------------------------- 整体失败


async def test_llm_error_yields_error_event_without_raising():
    p = RaisingProvider(LlmError("LLM 返回 HTTP 401：bad key"))
    events = await _run(p)
    assert _kinds(events) == ["error"]
    assert "401" in events[0].detail


async def test_max_rounds_exceeded_reports_error_not_silent():
    """永远要求调用工具 → 必须报「轮次超限」，不得静默结束。"""
    script = [[_tool_chunk(_call("s__t", "{}"))] for _ in range(10)]
    p = FakeProvider(script)
    events = await _run(p, specs=[_spec("s", "t")], max_rounds=3)
    assert events[-1].kind == "error"
    assert "轮次上限" in events[-1].detail
    assert sum(1 for e in events if e.kind == "tool_call") == 3
    assert not any(e.kind == "final" for e in events)


async def test_partial_text_is_preserved_when_llm_fails_midway():
    """已流出的文本必须已经产出（客户端已渲染）—— 失败只追加 error 事件。"""
    class MidFail:
        async def stream_chat(self, messages, tools=None):
            yield Chunk(text="前半")
            raise LlmError("连接中断")

    events = await _run(MidFail())
    assert _kinds(events) == ["text", "error"]
    assert events[0].text == "前半"


async def test_result_without_text_content_falls_back_to_json():
    """工具只返回结构化内容时，回填给模型的**不得是空串**。"""
    p = FakeProvider([
        [_tool_chunk(_call("s__t", "{}"))],
        [Chunk(text="ok")],
    ])

    async def structured(server, tool, args):
        return CallOutcome(ok=True, server=server, tool=tool,
                           result={"is_error": False, "content": []})

    await _run(p, specs=[_spec("s", "t")], execute=structured)
    filled = p.calls[1]["messages"][-1].content
    assert filled and json.loads(filled)["content"] == []
