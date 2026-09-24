"""NDJSON 审计 —— 通道 A（不可丢）。

方案 §11.4：审计证据流用 **NDJSON 追加文件**（OS 保证小写入 append 的原子性、
无跨写者锁争用），而非 SQLite WAL（WAL 写仍串行，高频写入会争用）。

只落 EVIDENCE 通道；TELEMETRY 不进审计。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .session import Channel, Event

logger = logging.getLogger(__name__)

#: 批量 flush 的阈值 —— 每次 append 都 flush 会拖慢调用路径。
#: ⚠️ 这是 **flush（进 OS 页缓存）不是 fsync（落盘）** —— 名字如实反映行为，
#:    不得读作"断电可持久化"。（改名前叫 `_FSYNC_EVERY`，是个误导性命名。）
_FLUSH_EVERY = 32


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
        if n >= _FLUSH_EVERY:
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
          OS 层；否则 `read_text` 读不到最近 `_FLUSH_EVERY` 条以内的事件，
          而且**静默返回不完整的结果**而非报错 —— 这是最难发现的一类错
          （已由实现者实测：append 2 条后 replay 返回空）。
        """
        self.flush()                        # ← 回归修复：见 docstring

        path = self.path_for(session_id)
        if not path.is_file():
            return ()

        # ⚠️ `errors="replace"` 不可省：写入用 `ensure_ascii=False`，payload 常含中文，
        #    一次撕裂写入会切断一个多字节字符 → 不带它则 read_text 抛 UnicodeDecodeError。
        #    而读取是**整文件**的，于是**整个会话的审计全部读不出来**，不只是坏的那一行。
        #    用了 replace 后，坏字节变成 U+FFFD → 该行 JSON 解析失败 → 按损坏行跳过。
        text = path.read_text(encoding="utf-8", errors="replace")

        out: list[Event] = []
        skipped = 0
        # ⚠️ 必须用 `split("\n")` 而**不是 `splitlines()`**：
        #    `str.splitlines()` 把 U+2028 / U+2029 / U+0085 也当行边界，
        #    而这三个码点 ≥ 0x20，`json.dumps(ensure_ascii=False)` **不转义它们**。
        #    于是 payload 含其中任一字符的**完整合法事件**会被从中间切开、
        #    两段都解析失败 → 整条证据在回放中消失，还被误报成"损坏行"。
        #    （审查者实测：U+2028/U+2029/U+0085 各切成 2 段；U+000B/U+001C 被转义故无害。）
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if not isinstance(d, dict):
                    raise ValueError("合法 JSON 但不是对象")
                out.append(Event(
                    seq=d["seq"], channel=Channel(d["channel"]), kind=d["kind"],
                    payload=d.get("payload") or {}, at=d["at"],
                ))
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                # ⚠️ 跳过但**不静默** —— 否则"审计文件部分损坏"与"审计本来就少"
                #    回放结果一模一样，无法区分。
                skipped += 1
                logger.warning("审计行无法解析，已跳过：%s (%s)", exc, line[:80])
        if skipped:
            logger.warning("会话 %s 的审计回放跳过了 %d 行", session_id, skipped)
        return tuple(out)
