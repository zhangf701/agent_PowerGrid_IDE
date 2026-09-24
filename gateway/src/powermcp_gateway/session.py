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
        self._subscribers: list[asyncio.Queue[Event | None]] = []
        self._seq = 0
        self._closed = False

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
        ★ 终止条件：**已关闭 且 队列已排空** —— 先排空再退出，因此**零丢失**。
        """
        if self._closed:
            return

        q: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=1024)
        self._subscribers.append(q)
        try:
            while True:
                if self._closed and q.empty():
                    return
                event = await q.get()
                if event is None:          # 终止哨兵
                    return
                yield event
        finally:
            self._subscribers.remove(q)

    def subscribe_queue(self) -> asyncio.Queue[Event | None]:
        """**同步**注册一个订阅者并返回其队列 —— 立即生效，无 await 窗口。

        与 `subscribe()` 的区别：后者是 async generator，订阅者要到第一次
        `__anext__()` 才真正注册。调用方若需要「注册订阅者」与「取历史快照」
        原子（例如 SSE 端点要先订阅、再补发历史），必须用本方法 ——
        否则两步之间 `yield` 让出的窗口里发布的事件会既不在快照里、
        也不在订阅队列里，**静默丢失**。

        调用方负责在结束时调用 `unsubscribe(q)`。
        """
        q: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=1024)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event | None]) -> None:
        """注销 `subscribe_queue()` 返回的队列。**幂等**。"""
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    def close(self) -> None:
        """关闭总线：所有订阅者会在**排空积压后**终止，**不丢弃任何事件**。

        ★ 关键观察：**队列为空时，哨兵必然放得下** —— 所以只在空队列时放哨兵。
          队列非空时**不放也没关系**：订阅者排空后会自己检查
          `_closed and q.empty()` 并退出。
          这一条同时消掉了两种错误做法：
          - 初版 `except QueueFull: pass`（吞掉哨兵 → 队列满的订阅者永久挂起）；
          - 以及「驱逐队首腾位」（在拆除路径上静默丢掉一条可能是 EVIDENCE 的事件，
            与 `publish()`「宁可拒绝发布也绝不丢证据」自相矛盾）。

        **幂等**：重复调用无副作用。
        """
        if self._closed:
            return
        self._closed = True
        for q in list(self._subscribers):
            if q.empty():
                q.put_nowait(None)      # 队列空 → 一定放得下


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
