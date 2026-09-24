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


# ── 以下 7 条为审查发现的回归测试 ──────────────────────────────────────────

async def test_close_terminates_subscriber_with_full_queue():
    """★ 回归：`close()` 必须让队列已满的订阅者也退出。

    （初版 `except QueueFull: pass` 吞掉终止哨兵 → 该订阅者永久挂起。）
    """
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


def test_publish_evidence_keeps_record_when_a_subscriber_queue_is_full():
    """★ 钉住 I-2 的**新**不变式：不可丢通道遇到满队列时**不拒绝发布**。

    本条**替代**旧的 `test_publish_evidence_refuses_when_a_subscriber_queue_is_full` ——
    旧不变式「任一订阅者队列满即拒绝发布（全有或全无）」**已被有意替换**
    （见 `session.py` 模块 docstring 的背压不变式）。替换理由：一个「连着但不读」的
    旁观客户端曾能让整个会话的 EVIDENCE 发布被拒 → 证据既不进历史、也不落审计。
    新不变式是「持久记录永不因旁观者阻塞而丢失」：发布**不抛异常**，事件照常入历史，
    该满队列被标记为**滞后**，其余未满订阅者不受牵连。
    """
    bus = EventBus()

    full_q: asyncio.Queue = asyncio.Queue(maxsize=1)
    full_q.put_nowait("filler")               # 把该订阅者队列占满
    bus._subscribers.append(full_q)

    live_q = bus.subscribe_queue()            # 一个未满的正常订阅者（旁路）

    # ③ publish 不得抛异常（旧实现会在此处 raise RuntimeError）
    event = bus.publish(Channel.EVIDENCE, "critical", {})

    # ① 事件仍进入持久历史，seq 正常递增
    assert event.seq == 1
    assert [e.seq for e in bus.events()] == [1]

    # ② 满队列被标记为滞后，stats 如实反映
    assert bus.is_lagged(full_q) is True
    assert bus.stats()["lagged_queues"] == 1
    assert bus.stats()["lagged_deliveries"] == 1

    # ④ 未满的订阅者不被牵连，仍正常收到该事件
    assert live_q.get_nowait().seq == 1

    # B1：`lagged_deliveries` 是**累计被跳过条数** —— 每条未能投递到 full_q 的都 +1；
    #     `lagged_queues`（现状量）仍为 1，且 warning 只发一次（计数与噪声控制分离）。
    event2 = bus.publish(Channel.EVIDENCE, "critical2", {})
    assert event2.seq == 2
    assert [e.seq for e in bus.events()] == [1, 2]
    assert bus.stats()["lagged_queues"] == 1
    assert bus.stats()["lagged_deliveries"] == 2
    assert live_q.get_nowait().seq == 2          # 旁路仍两条都收到

    bus.unsubscribe(live_q)


def test_lagged_deliveries_counts_every_skipped_evidence_delivery():
    """★ B1：`lagged_deliveries` 是**累计被跳过条数**，不是「每队列首次计 1」。

    后者下，一个卡死客户端丢了一万条、计数仍停在 1 —— 看不出降级规模，
    I-2「让证据流降级可观测」的意义随之失效。`lagged_queues` 是现状量，
    `lagged_deliveries` 是累计量，二者互补。
    """
    bus = EventBus()
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    q.put_nowait("filler")                       # 占满
    bus._subscribers.append(q)

    for i in range(5):
        bus.publish(Channel.EVIDENCE, "e", {"i": i})

    assert len(bus.events()) == 5                # 持久记录 5 条，一条不丢
    assert bus.stats()["lagged_queues"] == 1     # 现状量
    assert bus.stats()["lagged_deliveries"] == 5  # 累计量：5 条都没能投递到 q


def test_dropped_telemetry_counts_every_dropped_event():
    """可丢通道满队列 —— **每条**丢弃都计入 `dropped_telemetry`（累计量）。"""
    bus = EventBus()
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    q.put_nowait("filler")
    bus._subscribers.append(q)

    for i in range(3):
        bus.publish(Channel.TELEMETRY, "noise", {"i": i})

    assert bus.stats()["dropped_telemetry"] == 3
    assert bus.stats()["lagged_queues"] == 0     # 可丢通道不产生滞后
    assert len(bus.events()) == 3


def test_publish_after_close_raises():
    bus = EventBus()
    bus.close()
    with pytest.raises(RuntimeError, match="已关闭"):
        bus.publish(Channel.TELEMETRY, "x", {})


async def test_subscribe_after_close_returns_immediately():
    """★ 回归：close() **之后**才挂上的订阅者不得挂起。

    （给 `publish` 加 `_closed` 守卫时曾漏掉这个入口 —— 晚到的订阅者
      永远等不到事件，还会作为孤儿滞留在 `_subscribers`。）
    """
    bus = EventBus()
    bus.close()

    got: list[int] = []
    async for ev in bus.subscribe():          # 未修复时会永久挂起
        got.append(ev.seq)

    assert got == []
    assert bus.subscriber_count() == 0        # 不留孤儿


async def test_close_does_not_drop_evidence_when_queue_is_full():
    """★ 回归：队列**恰好填满**时 close()，不得丢弃任何一条 EVIDENCE。

    （曾为塞入终止哨兵而驱逐队首 —— 在拆除路径上静默丢掉一条证据，
      与 `publish()`「宁可拒绝发布也绝不丢证据」的取舍自相矛盾。）
    """
    bus = EventBus()
    got: list[int] = []

    async def consume():
        async for ev in bus.subscribe():
            got.append(ev.seq)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)

    for i in range(1024):                     # 恰好填满 maxsize=1024（不触背压）
        bus.publish(Channel.EVIDENCE, "critical", {"i": i})
    assert got == [], "发布循环无 await，消费者不应在此前被调度"

    bus.close()
    await asyncio.wait_for(task, timeout=2)
    assert got == list(range(1, 1025)), "close() 丢弃了证据事件"


def test_close_is_idempotent():
    bus = EventBus()
    bus.close()
    bus.close()                               # 第二次应是 no-op，不得抛错
    with pytest.raises(RuntimeError, match="已关闭"):
        bus.publish(Channel.TELEMETRY, "x", {})


async def test_cancelled_subscriber_leaves_no_orphan():
    """★ 回归：订阅者被取消（SSE 客户端断开时正是如此）不得残留孤儿订阅。

    上一版用 `ensure_future` 竞速等「队列」与「关闭事件」，外层被取消时
    两个子任务无人回收 → GC 打印 `Task was destroyed but it is pending!`。
    pytest-asyncio 会在 teardown 前取消任务，所以那个泄漏**在测试里看不见、
    在 uvicorn 里才现形**。现版没有任何子任务，结构上不可能泄漏。
    """
    bus = EventBus()

    async def consume():
        async for _ in bus.subscribe():
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    assert bus.subscriber_count() == 1

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert bus.subscriber_count() == 0        # 不留孤儿


# ── 以下两条覆盖本任务新增的同步注册 API ──────────────────────────────────

def test_subscribe_queue_registers_synchronously():
    """★ 注册必须**同步**生效 —— 否则「先订阅再补历史」之间会有丢失窗口。"""
    bus = EventBus()
    bus.publish(Channel.EVIDENCE, "before", {})
    q = bus.subscribe_queue()
    assert bus.subscriber_count() == 1          # 无需 await 即已注册
    bus.publish(Channel.EVIDENCE, "after", {})
    assert q.get_nowait().kind == "after"       # 注册之后的事件进队列
    bus.unsubscribe(q)
    assert bus.subscriber_count() == 0


def test_unsubscribe_is_idempotent():
    bus = EventBus()
    q = bus.subscribe_queue()
    bus.unsubscribe(q)
    bus.unsubscribe(q)                          # 重复注销不得抛
    assert bus.subscriber_count() == 0
