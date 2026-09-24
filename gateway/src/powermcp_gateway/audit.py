"""NDJSON 审计 —— 通道 A（不可丢）。

方案 §11.4：审计证据流用 **NDJSON 追加文件**（OS 保证小写入 append 的原子性、
无跨写者锁争用），而非 SQLite WAL（WAL 写仍串行，高频写入会争用）。

只落 EVIDENCE 通道；TELEMETRY 不进审计。
"""

from __future__ import annotations

import json
from pathlib import Path

from .session import Channel, Event

#: 批量 fsync 的阈值 —— 每次 append 都 fsync 会拖慢调用路径
_FSYNC_EVERY = 32


class AuditLog:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._pending: dict[str, int] = {}
        self._handles: dict[str, object] = {}

    def path_for(self, session_id: str) -> Path:
        return self._root / f"audit-{session_id}.ndjson"

    def _handle(self, session_id: str):
        fh = self._handles.get(session_id)
        if fh is None:
            fh = self.path_for(session_id).open("a", encoding="utf-8")
            self._handles[session_id] = fh
        return fh

    def append(self, session_id: str, event: Event) -> None:
        if event.channel is not Channel.EVIDENCE:
            return                      # 通道 B 不入审计
        fh = self._handle(session_id)
        fh.write(json.dumps({
            "seq": event.seq,
            "channel": event.channel.value,
            "kind": event.kind,
            "payload": event.payload,
            "at": event.at,
        }, ensure_ascii=False) + "\n")

        n = self._pending.get(session_id, 0) + 1
        if n >= _FSYNC_EVERY:
            fh.flush()
            self._pending[session_id] = 0
        else:
            self._pending[session_id] = n

    def flush(self) -> None:
        for fh in self._handles.values():
            fh.flush()
        self._pending.clear()

    def replay(self, session_id: str) -> tuple[Event, ...]:
        """回放某会话的审计流。

        ★ 必须先 `flush()`：`append` 写的是**带缓冲的文件对象**，只有 flush 才落到
          OS 层；否则 `read_text` 读不到最近 `_FSYNC_EVERY` 条以内的事件，
          而且**静默返回不完整的结果**而非报错 —— 这是最难发现的一类错
          （已由实现者实测：append 2 条后 replay 返回空）。
        """
        self.flush()                        # ← 回归修复：见 docstring

        path = self.path_for(session_id)
        if not path.is_file():
            return ()

        out: list[Event] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if not isinstance(d, dict):
                    continue        # 合法 JSON 但不是对象（如截断成 `12345`）
                out.append(Event(
                    seq=d["seq"], channel=Channel(d["channel"]), kind=d["kind"],
                    payload=d.get("payload") or {}, at=d["at"],
                ))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue        # 截断/损坏的行跳过，不让回放崩掉
        return tuple(out)
