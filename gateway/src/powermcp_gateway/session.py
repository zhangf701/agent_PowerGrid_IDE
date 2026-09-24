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
from dataclasses import dataclass, field
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

    def publish(self, channel: Channel, kind: str, payload: dict) -> Event:
        self._seq += 1
        event = Event(seq=self._seq, channel=channel, kind=kind, payload=payload, at=_now())
        self._events.append(event)
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                if not DROPPABLE[channel]:
                    raise  # 证据通道绝不静默丢弃
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
        for q in self._subscribers:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass


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
