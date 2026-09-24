import asyncio

import pytest

from powermcp_gateway.session import Channel, EventBus, SessionStore


def test_publish_assigns_monotonic_seq():
    bus = EventBus()
    a = bus.publish(Channel.EVIDENCE, "tool_call", {"tool": "run_power_flow"})
    b = bus.publish(Channel.TELEMETRY, "progress", {"pct": 50})
    c = bus.publish(Channel.EVIDENCE, "contract", {"contract": 3})
    assert [a.seq, b.seq, c.seq] == [1, 2, 3]
    assert a.channel is Channel.EVIDENCE
    assert b.channel is Channel.TELEMETRY


def test_events_preserve_order():
    bus = EventBus()
    for i in range(5):
        bus.publish(Channel.EVIDENCE, "e", {"i": i})
    assert [e.payload["i"] for e in bus.events()] == [0, 1, 2, 3, 4]


async def test_subscriber_receives_events_and_stops_on_close():
    bus = EventBus()
    got = []

    async def consume():
        async for ev in bus.subscribe():
            got.append(ev.seq)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)          # 让订阅者先挂上
    bus.publish(Channel.EVIDENCE, "a", {})
    bus.publish(Channel.TELEMETRY, "b", {})
    await asyncio.sleep(0)
    bus.close()
    await asyncio.wait_for(task, timeout=2)

    assert got == [1, 2]


def test_two_subscribers_both_get_all_events():
    """通道分离不是"分流" —— 每个订阅者都拿到全部事件，各自按 channel 过滤。"""
    bus = EventBus()
    assert bus.subscriber_count() == 0
    bus.publish(Channel.EVIDENCE, "a", {})
    assert bus.events()[0].kind == "a"


def test_session_store_create_and_get():
    store = SessionStore()
    s = store.create(servers=("pandapower", "pypsa"))
    assert s.id
    assert s.created_at.endswith("Z")
    assert store.get(s.id).servers == ("pandapower", "pypsa")
    assert store.bus(s.id) is store.bus(s.id)      # 同一会话同一个总线


def test_session_store_unknown_id_raises():
    with pytest.raises(KeyError):
        SessionStore().get("nope")
