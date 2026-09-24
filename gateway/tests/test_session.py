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


async def test_two_subscribers_both_get_all_events():
    """每个订阅者都拿到**全部**事件 —— 通道分离不是"分流"，是各自的过滤视图。

    ★ 修订（审查发现）：初版此测试**从未创建订阅者**，只断言了
    `subscriber_count() == 0` 与一条事件存在 —— 即"没人订阅时发布不崩"，
    与其函数名/docstring 声称的扇出语义无关。双通道分离是 ★ 要求，
    必须有真正验证它的测试。
    """
    bus = EventBus()
    got_a: list[int] = []
    got_b: list[int] = []

    async def consume(sink: list[int]):
        async for ev in bus.subscribe():
            sink.append(ev.seq)

    task_a = asyncio.create_task(consume(got_a))
    task_b = asyncio.create_task(consume(got_b))
    await asyncio.sleep(0)                       # 让两个订阅者都挂上
    assert bus.subscriber_count() == 2

    bus.publish(Channel.EVIDENCE, "a", {})
    bus.publish(Channel.TELEMETRY, "b", {})
    await asyncio.sleep(0)

    bus.close()
    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=2)

    assert got_a == [1, 2]
    assert got_b == [1, 2], "第二个订阅者没有拿到全部事件"
    assert bus.subscriber_count() == 0           # 生成器退出后自动注销


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


async def test_close_terminates_subscriber_with_full_queue():
    """★ 回归：审查复现的挂死 —— close() 必须让队列已满的订阅者也退出。"""
    bus = EventBus()
    got: list[int] = []

    async def consume():
        async for ev in bus.subscribe():
            got.append(ev.seq)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    for i in range(1025):                     # 超过 maxsize=1024，撑满队列
        bus.publish(Channel.TELEMETRY, "noise", {"i": i})
    assert bus.subscriber_count() == 1

    bus.close()
    await asyncio.wait_for(task, timeout=2)   # 初版会在此超时
    assert bus.subscriber_count() == 0


def test_publish_evidence_refuses_when_a_subscriber_queue_is_full():
    """★ 回归：证据通道不做半投递 —— 队列满时整体拒绝，且拒绝不留痕。"""
    bus = EventBus()
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    q.put_nowait("filler")                    # 把队列占满
    bus._subscribers.append(q)

    with pytest.raises(RuntimeError, match="证据不可丢"):
        bus.publish(Channel.EVIDENCE, "critical", {})

    assert bus.events() == ()                 # 被拒绝的事件没有进入历史
    assert bus.publish(Channel.TELEMETRY, "noise", {}).seq == 1   # seq 也未被消耗


def test_publish_after_close_raises():
    bus = EventBus()
    bus.close()
    with pytest.raises(RuntimeError, match="已关闭"):
        bus.publish(Channel.TELEMETRY, "x", {})
