"""会话与事件总线。

★ 双通道（方案 §2.3）：EVIDENCE 不可丢 / TELEMETRY 可丢，**物理分离**。
  审计一旦可丢，审计就不可信 —— 契约面板全部结论随之失效。
★ 单调序列号（方案 §11.7-③）：多引擎结果到达顺序不确定，必须靠序列号排序，
  否则一致性视图会**静默给出错误的一致性结论**。
"""

from __future__ import annotations

import asyncio
import enum
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator


class Channel(enum.Enum):
    EVIDENCE = "evidence"      # 不可丢：调用记录、契约判定、edits 轨迹
    TELEMETRY = "telemetry"    # 可丢：进度、临时状态


#: 背压策略挂在通道上，调用方无需记忆
DROPPABLE: dict[Channel, bool] = {Channel.EVIDENCE: False, Channel.TELEMETRY: True}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Event:
    seq: int
    channel: Channel
    kind: str
    payload: dict
    at: str


@dataclass(frozen=True)
class Session:
    id: str
    servers: tuple[str, ...]
    created_at: str


class EventBus:
    """会话内的事件总线。每个订阅者收到**全部**事件，各自按 channel 过滤。"""

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._subscribers: list[asyncio.Queue[Event]] = []
        self._seq = 0
        self._closed = False
        #: 关闭信号 —— 订阅者同时等待它与自己的队列，从而在**不丢事件**的前提下退出
        self._closed_event = asyncio.Event()

    def publish(self, channel: Channel, kind: str, payload: dict) -> Event:
        if self._closed:
            raise RuntimeError("EventBus 已关闭，不能再发布事件")

        # ★ 证据通道：**先全量校验，再动任何状态**（审查发现）
        #   初版是在投递循环里 raise —— 那时 _events 已追加、部分订阅者已收到，
        #   发布方重试又会 _seq += 1 再追加一条 → 不可丢的审计流里出现重复记录。
        #   现在：拒绝时不消耗 seq、不追加历史、不投递给任何人 —— 全有或全无。
        if not DROPPABLE[channel]:
            full = [q for q in self._subscribers if q.full()]
            if full:
                raise RuntimeError(
                    f"证据通道有 {len(full)} 个订阅者队列已满，拒绝发布 "
                    f"{kind}(channel={channel.value}) —— 证据不可丢，不做半投递"
                )

        self._seq += 1
        event = Event(seq=self._seq, channel=channel, kind=kind, payload=payload, at=_now())
        self._events.append(event)

        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                if not DROPPABLE[channel]:
                    # 不可达：单线程 asyncio 下，上面的预校验与这里之间没有 await，
                    # 队列不可能被填满。保留 raise 作为断言，而非静默丢弃证据。
                    raise AssertionError("预校验通过后仍遇到满队列 —— 不应发生")
        return event

    async def subscribe(self) -> AsyncIterator[Event]:
        """订阅事件流。

        ★ 在**已关闭**的总线上调用会**立即返回**，不得挂起 ——
          否则晚挂上的订阅者永远等不到事件，还会作为孤儿滞留在 `_subscribers`。
          （审查发现：给 `publish` 加 `_closed` 守卫后，这个入口被漏掉了。）
        ★ 终止条件：**已关闭 且 队列已排空** —— 先排空再退出，因此**零丢失**。
        """
        if self._closed:
            return

        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=1024)
        self._subscribers.append(q)
        try:
            while True:
                if self._closed and q.empty():
                    return
                # 同时等「队列有事件」与「总线已关闭」——
                # 只等前者会在 close() 时永久挂起（哨兵放不进满队列）。
                get_task = asyncio.ensure_future(q.get())
                close_task = asyncio.ensure_future(self._closed_event.wait())
                done, pending = await asyncio.wait(
                    {get_task, close_task}, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                if pending:
                    # 吞掉 CancelledError，避免 "Task was destroyed but it is pending" 噪声
                    await asyncio.gather(*pending, return_exceptions=True)
                if get_task in done:
                    yield get_task.result()
        finally:
            self._subscribers.remove(q)

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    def close(self) -> None:
        """关闭总线：所有订阅者会在**排空积压后**终止，**不丢弃任何事件**。

        实现方式：只置标志并唤醒等待者 —— **不发哨兵、不驱逐队列**。
        订阅者侧靠 `subscribe()` 同时等待「队列」与「关闭事件」来退出（见上）。

        ★ 为什么不用哨兵（审查发现，两版都被否）：
        - 初版 `except QueueFull: pass` 会**吞掉哨兵** → 队列满的订阅者永久挂起（已复现）；
        - 改为「驱逐队首腾位」后，拆除路径会**静默丢掉一条可能是 EVIDENCE 的事件** ——
          与 `publish()`「宁可拒绝发布也绝不丢证据」的取舍**自相矛盾**，
          且当时的 docstring 拿"NDJSON 审计"当兜底，而那个组件当时**还不存在**。

        **幂等**：重复调用无副作用。
        """
        if self._closed:
            return
        self._closed = True
        self._closed_event.set()


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._buses: dict[str, EventBus] = {}

    def create(self, servers) -> Session:
        s = Session(id=uuid.uuid4().hex[:12], servers=tuple(servers), created_at=_now())
        self._sessions[s.id] = s
        self._buses[s.id] = EventBus()
        return s

    def get(self, sid: str) -> Session:
        return self._sessions[sid]

    def bus(self, sid: str) -> EventBus:
        return self._buses[sid]
