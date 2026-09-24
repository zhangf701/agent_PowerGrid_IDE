"""SSE 序列化 —— 双通道物理分离。

通道即 SSE 的 `event:` 名（`evidence` / `telemetry`），前端按名分派，
不需要解析 payload 才知道该不该丢。

`id:` 用事件的单调序列号 —— 断线重连时前端可用 `Last-Event-ID` 续传，
且**乱序到达时可按 id 排序**（方案 §11.7-③）。
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from .session import Channel, Event, EventBus


def format_sse(event: Event) -> str:
    data = json.dumps({
        "seq": event.seq,
        "kind": event.kind,
        "payload": event.payload,
        "at": event.at,
    }, ensure_ascii=False)
    return (
        f"id: {event.seq}\n"
        f"event: {event.channel.value}\n"
        f"data: {data}\n\n"
    )


async def sse_stream(bus: EventBus) -> AsyncIterator[str]:
    """把总线上的事件转成 SSE 帧（**不含历史补发**）。

    ⚠️ 与 `EventBus.subscribe_queue()` 的区别：本生成器是 async generator，
      订阅者要到**第一次迭代**才注册 —— 所以**不能**用它实现"先订阅、再补发历史"，
      两步之间会有丢失窗口。需要历史补发的场景（HTTP SSE 端点）请用
      `subscribe_queue()`。本函数适合"只要实时流、不要历史"的消费者。
    """
    async for event in bus.subscribe():
        yield format_sse(event)
