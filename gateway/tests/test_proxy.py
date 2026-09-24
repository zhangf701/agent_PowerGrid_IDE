import asyncio

from powermcp_gateway.proxy import call_tool

SCHEMA = {
    "type": "object",
    "properties": {"network_name": {"type": "string"}},
    "required": ["network_name"],
}


def test_invalid_args_are_rejected_without_touching_the_engine(monkeypatch):
    """★ 核心：参数非法时**根本不应发起调用**。"""
    import powermcp_gateway.proxy as proxy

    called = []

    async def fake_dispatch(cfg, server, tool, args):
        called.append((server, tool, args))
        return {"status": "success"}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)

    outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="optimize_network",
        args={"network_name": "n", "linearized": True}, schema=SCHEMA,
    ))

    assert outcome.ok is False
    assert called == [], "非法参数被转发给了引擎"
    assert [v.kind for v in outcome.violations] == ["unknown_arg"]
    assert "linearized" in outcome.error


def test_valid_args_are_forwarded(monkeypatch):
    import powermcp_gateway.proxy as proxy

    async def fake_dispatch(cfg, server, tool, args):
        return {"status": "success", "value": 42}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)

    outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="optimize_network",
        args={"network_name": "n"}, schema=SCHEMA,
    ))
    assert outcome.ok is True
    assert outcome.result["value"] == 42
    assert outcome.violations == ()


def test_engine_error_is_surfaced_not_swallowed(monkeypatch):
    import powermcp_gateway.proxy as proxy

    async def boom(cfg, server, tool, args):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(proxy, "_dispatch", boom)

    outcome = asyncio.run(call_tool(
        cfg=None, server="surge", tool="run_power_flow",
        args={"network_name": "n"}, schema=SCHEMA,
    ))
    assert outcome.ok is False
    assert "engine exploded" in outcome.error


def test_violation_is_published_to_evidence_channel(monkeypatch):
    """契约 3 的违规必须进审计（通道 A），不得只留在返回值里。"""
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway.session import Channel, EventBus

    async def fake_dispatch(cfg, server, tool, args):
        return {}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)
    bus = EventBus()

    asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="t", args={"nope": 1}, schema=SCHEMA,
        bus=bus, session_id="s1",
    ))

    kinds = [(e.channel, e.kind) for e in bus.events()]
    assert (Channel.EVIDENCE, "contract_violation") in kinds


def test_successful_call_publishes_tool_call_event(monkeypatch):
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway.session import Channel, EventBus

    async def fake_dispatch(cfg, server, tool, args):
        return {"status": "success"}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)
    bus = EventBus()

    asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="t", args={"network_name": "n"},
        schema=SCHEMA, bus=bus, session_id="s1",
    ))
    kinds = [e.kind for e in bus.events()]
    assert "tool_call" in kinds


def test_closed_bus_does_not_lose_the_outcome(monkeypatch):
    """★ 回归：总线已关闭时，结果 / 违规明细**仍必须**交回调用者。

    `EventBus.publish` 在 closed 时 raise RuntimeError。若 `_emit` 不处理，
    `call_tool` 会抛异常 —— 契约 3「返回 ok=False 与违规明细」的承诺被击穿，
    成功路径上更会**丢失一个已经执行完的调用结果**。
    """
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway.session import EventBus

    async def fake_dispatch(cfg, server, tool, args):
        return {"status": "success"}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)
    bus = EventBus()
    bus.close()

    ok_outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="t", args={"network_name": "n"},
        schema=SCHEMA, bus=bus, session_id="s1",
    ))
    assert ok_outcome.ok is True
    assert ok_outcome.result == {"status": "success"}

    bad_outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="t", args={"network_name": "n", "nope": 1},
        schema=SCHEMA, bus=bus, session_id="s1",
    ))
    assert bad_outcome.ok is False
    assert [v.kind for v in bad_outcome.violations] == ["unknown_arg"]


def test_tool_is_error_is_not_reported_as_success(monkeypatch):
    """★ MCP 工具失败的标准形态：**不抛异常**，以 `is_error=True` 返回。

    只取 `content` 会把它报成 `ok=True` —— 正是契约 3 要防的
    「看起来成功、实际没生效」形态的镜像。
    """
    import powermcp_gateway.proxy as proxy

    async def failing_dispatch(cfg, server, tool, args):
        return {"is_error": True, "content": [{"type": "text", "text": "solver diverged"}]}

    monkeypatch.setattr(proxy, "_dispatch", failing_dispatch)

    outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="run_power_flow", args={"network_name": "n"},
        schema=SCHEMA,
    ))
    assert outcome.ok is False
    assert "is_error" in outcome.error
    assert outcome.result["content"][0]["text"] == "solver diverged"
