"""会话与事件总线。

★ 双通道（方案 §2.3）：EVIDENCE 不可丢 / TELEMETRY 可丢，**物理分离**。
  审计一旦可丢，审计就不可信 —— 契约面板全部结论随之失效。
★ 单调序列号（方案 §11.7-③）：多引擎结果到达顺序不确定，必须靠序列号排序，
  否则一致性视图会**静默给出错误的一致性结论**。

★ 背压不变式（I-2 根治，**有意替换旧语义**）：
  旧实现是「全有或全无」—— 任一订阅者队列满即 `raise RuntimeError` **拒绝发布**，
  理由是"宁可拒绝发布也绝不丢证据"。但该取舍有一个被审查实测确证的致命后果：
  一个**连着但不读**的 SSE 客户端会让队列填满 → 此后该会话所有 EVIDENCE 发布被拒
  → 事件既不进总线历史、也不落 NDJSON 审计（只有一条没人看的 warning），
  直接击穿「EVIDENCE 不可丢」这一子项目 3 的核心前提。

  新不变式：**持久记录（历史 + NDJSON 审计）永不因旁观者阻塞而丢失**。
  `publish()` **先记录、后扇出**：`_seq` 递增与 `_events.append` 在任何扇出之前完成，
  因此发布**不再因满队列而失败**。扇出改为**尽力而为**：
    - 可丢通道（`DROPPABLE` 为真，如 TELEMETRY）：满则跳过，**每条**计入 `dropped_telemetry`；
    - 不可丢通道（EVIDENCE）：满则**不报错**。每当某条 EVIDENCE **未能投递到某订阅者**
      （该队列满），就把 `lagged_deliveries` **累计 +1**；该队列**首次**判满时加入
      `_lagged`（现状量，供 `is_lagged()` 判定）并 `logger.warning` **一次**。
      ⚠️ `lagged_deliveries` 是**丢失量级**（累计条数）而非「每队列计 1」——
      否则一个卡死客户端丢了一万条，计数仍停在 1，看不出降级规模。
  为什么这样仍然"一条证据都不丢"：一个停滞的订阅者**只影响它自己的投递连续性**，
  它会被标记为滞后、由其消费者（SSE 端点）主动结束连接，重连后靠历史全量重放恢复
  —— 端到端证据因此**一条都不丢**（记录从未被丢弃，只是投递延后/重建）。
"""

from __future__ import annotations

import asyncio
import enum
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator

logger = logging.getLogger(__name__)


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
        #: 已滞后的订阅者队列（**现状量**：当前处于滞后态的队列集合）。
        self._lagged: set[asyncio.Queue[Event | None]] = set()
        #: 累计被跳过、**未能投递到订阅者**的 EVIDENCE 条数（**累计量**：每次满即 +1）。
        self._lagged_deliveries = 0
        #: 累计丢弃遥测事件数（**累计量**：可丢通道每遇满队列即 +1）。
        self._dropped_telemetry = 0

    def publish(self, channel: Channel, kind: str, payload: dict) -> Event:
        """发布一条事件。

        ★ 先记录、后扇出（见模块 docstring 的背压不变式）：
          1. `_seq += 1` 与 `_events.append(event)` **无条件先发生** ——
             持久记录不依赖任何订阅者，因此**不会因满队列而失败**；
          2. 之后才尽力扇出。扇出**绝不抛异常**：
             - 可丢通道满 → 跳过并计 `dropped_telemetry`；
             - 不可丢通道满 → `lagged_deliveries` 累计 +1；该队列**首次**判满时
               标记滞后并告警**一次**（此后不再刷屏，但计数继续累加）。

        只有向**已关闭**的总线发布才 `raise RuntimeError`（这是编程错误，保留）。
        """
        if self._closed:
            raise RuntimeError("EventBus 已关闭，不能再发布事件")

        # ① 持久记录 —— 先于任何扇出，且不依赖订阅者。
        self._seq += 1
        event = Event(seq=self._seq, channel=channel, kind=kind, payload=payload, at=_now())
        self._events.append(event)

        # ② 尽力扇出。未注册的通道按「不可丢」处理（保守）—— 同时消除硬下标 KeyError。
        droppable = DROPPABLE.get(channel, False)
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                if droppable:
                    self._dropped_telemetry += 1
                else:
                    # 不可丢通道：不报错。**累计**记录「这一条没能投递给该订阅者」。
                    self._lagged_deliveries += 1
                    if q not in self._lagged:
                        # 首次判满：标记滞后（现状量）+ 告警**一次**（噪声控制）。
                        # 计数与告警是两件事 —— 此后不再刷屏，但计数继续累加。
                        self._lagged.add(q)
                        logger.warning(
                            "订阅者队列已满，标记为滞后（channel=%s, kind=%s, seq=%d）—— "
                            "持久记录不受影响；该订阅者应由其消费者结束连接并按历史全量重放",
                            channel.value, kind, event.seq,
                        )
        return event

    def is_lagged(self, q: asyncio.Queue[Event | None]) -> bool:
        """该订阅者队列是否已滞后（曾因不可丢通道满而被跳过投递）。

        供消费者（SSE 端点）主动结束连接、触发重连后按历史全量重放。
        """
        return q in self._lagged

    def stats(self) -> dict:
        """只读观测快照 —— 让"证据流已降级"可被诊断，而非只有一条 warning。

        逐键语义（**现状量 vs 累计量**必须分清，否则会误读降级规模）：
          - `queues`            **现状量**：当前订阅者数；
          - `events`            **现状量**：持久历史条数；
          - `lagged_queues`     **现状量**：当前处于滞后态的订阅者队列数；
          - `lagged_deliveries` **累计量**：迄今被跳过、未能投递给订阅者的 EVIDENCE 条数
                                （每次因某队列满而投递失败即 +1，含首次判满那条）；
          - `dropped_telemetry` **累计量**：迄今被丢弃的 TELEMETRY 条数。
        """
        return {
            "queues": len(self._subscribers),
            "events": len(self._events),
            "lagged_queues": len(self._lagged),
            "lagged_deliveries": self._lagged_deliveries,
            "dropped_telemetry": self._dropped_telemetry,
        }

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
        """注销 `subscribe_queue()` 返回的队列。**幂等**。

        同时清除其滞后标记 —— 否则已注销的队列会作为悬垂引用留在 `_lagged` 中，
        既泄漏内存，又让 `stats()["lagged_queues"]` 长期虚高。
        """
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass
        self._lagged.discard(q)

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
            与 `publish()`「持久记录永不丢弃」的不变式自相矛盾）。

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
