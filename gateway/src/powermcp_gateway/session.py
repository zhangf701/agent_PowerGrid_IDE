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

    async def subscribe(self):
        q: asyncio.Queue[Event | None] = asyncio.Queue(maxsize=1024)
        self._subscribers.append(q)
        try:
            while True:
                event = await q.get()
                if event is None:
                    return
                yield event
        finally:
            self._subscribers.remove(q)

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def events(self) -> tuple[Event, ...]:
        return tuple(self._events)

    def close(self) -> None:
        """关闭总线：所有订阅者都会终止。

        ★ 修订（审查发现）：初版 `except QueueFull: pass` 会**吞掉终止哨兵** ——
        队列已满的订阅者再也等不到 `None`，`await q.get()` 永久挂起。
        审查者已复现（1024 条 TELEMETRY 后 close → 任务永不结束）。

        现在的做法：队列满时**丢弃队首一条**以腾位给哨兵。
        这是有意的取舍 —— `close()` 是会话拆除路径，为一个已不再消费的订阅者
        无限阻塞没有意义；且被丢弃的事件仍在 `self._events` 与 NDJSON 审计中，
        **不会真正丢失**，只是该订阅者看不到积压的那一条。
        """
        self._closed = True
        for q in list(self._subscribers):
            while True:
                try:
                    q.put_nowait(None)      # 终止哨兵
                    break
                except asyncio.QueueFull:
                    try:
                        q.get_nowait()      # 丢队首，腾位置
                    except asyncio.QueueEmpty:
                        break               # 竞态下已空，重试一次 put


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
