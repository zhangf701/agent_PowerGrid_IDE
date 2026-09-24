"""SSE 序列化 —— 双通道物理分离。

通道即 SSE 的 `event:` 名（`evidence` / `telemetry`），前端按名分派，
不需要解析 payload 才知道该不该丢。

`id:` 用事件的单调序列号（`event.seq`），用途有二：
  - **客户端排序**：多引擎结果到达顺序不确定，必须靠 id 排序（方案 §11.7-③）；
  - **客户端自行去重**（见下）。

⚠️ **服务端不解析 `Last-Event-ID`**：本模块与 SSE 端点（`api.py` 的 `gen()`）
  都**不读取该请求头**。断线重连一律由历史**全量重放**兜底 —— 因此事件**不丢**，
  但**会重复**投递；客户端可按 `id` 去重。

通道策略（见 `session.py` 的背压不变式）：`evidence` 通道**不可丢**，
`telemetry` 通道可丢。
"""

from __future__ import annotations

import json

from .session import Event


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
