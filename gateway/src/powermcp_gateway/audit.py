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
        #: 累计写入失败的事件条数（**丢失量级**）—— 见 `append()` 与 `stats()`
        self.append_failures = 0
        #: 最近一次写入失败的可读原因（无失败时为 None）
        self.last_error: str | None = None

    def path_for(self, session_id: str) -> Path:
        return self._root / f"audit-{session_id}.ndjson"

    def _handle(self, session_id: str):
        fh = self._handles.get(session_id)
        if fh is None:
            # ⚠️ `newline="\n"` 不可省（T1-M8）：Windows 上默认文本模式会把 "\n"
            #    翻译成 "\r\n"，写出非严格 LF 的 NDJSON。读侧虽用 .strip() 容忍，
            #    但方案把 NDJSON 定位为**跨进程证据格式**，外部消费者不应被迫同样容忍。
            fh = self.path_for(session_id).open("a", encoding="utf-8", newline="\n")
            self._handles[session_id] = fh
        return fh

    def append(self, session_id: str, event: Event) -> bool:
        """把一个 EVIDENCE 事件追加到该会话的 NDJSON。**返回是否已写入**。

        ★ 返回 `bool` 而不是 `None`：调用方（`proxy._emit`）需要区分"已持久化"与
          "只在内存历史里"。若磁盘满/权限失败，事件**已经进了总线历史**，因此
          **不抛异常**（不能因持久化失败反过来打断一个已经执行完的调用结果）；
          但**必须可观测** —— 计数 `append_failures`、记下 `last_error`、
          `logger.error`。这与 `EventBus` 的背压计数（`lagged_deliveries`）
          是同一口径：**降级可以发生，但不许静默**。

        ⚠️ 一次调用最多计 1 次失败（打开句柄、write、阈值触发的 flush 包在同一处
          try 内），否则一次磁盘故障会被重复计数、夸大丢失量级。
        ⚠️ 通道 B（TELEMETRY）不入审计，返回 `True` —— 那是**设计行为，不是失败**。
        """
        if event.channel is not Channel.EVIDENCE:
            return True                 # 通道 B 不入审计（正常路径）
        try:
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
            return True
        except Exception as exc:
            self.append_failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            logger.error(
                "审计写入失败（session=%s, kind=%s, 累计失败 %d 条）—— "
                "该事件**在内存历史中但未持久化**到 NDJSON。原因：%s",
                session_id, event.kind, self.append_failures, self.last_error,
            )
            return False

    def flush(self) -> None:
        for fh in self._handles.values():
            fh.flush()
        self._pending.clear()

    def stats(self) -> dict:
        """审计层的只读观测面（与 `EventBus.stats()` 对称）。

        ★ 审计写失败是 I-2 之后**唯一残留的静默降级路径**：事件在内存历史里有、
          在 NDJSON 里没有。这里把它变成可读的数字，并由 `GET /health` 暴露。

        - `handles`：当前打开的句柄数（**现状量**）
        - `append_failures`：累计未被持久化的事件条数（**累计量 = 丢失量级**）
        - `last_error`：最近一次失败的可读原因（无失败为 None）
        """
        return {
            "handles": len(self._handles),
            "append_failures": self.append_failures,
            "last_error": self.last_error,
        }

    def close(self) -> None:
        """先尝试 flush，再关闭**所有**句柄并清空台账/待 flush 计数（T1-M7）。

        网关是长生命周期进程，而 `_handle()` 只 `open("a")`、从不关闭 ——
        每个新会话都会**泄漏一个文件句柄**；Windows 上还会持续占住文件，
        阻碍外部工具读取/轮转。

        ★ **释放 fd 是第一职责**：即使 flush 抛异常，也**必须**关闭全部句柄 ——
          否则 T1-M7 的"每会话泄漏一个 fd"会在失败路径上原样复发。
          故 flush 包 try/except（失败只告警），随后无论成败都关闭每个句柄
          （每个 `fh.close()` 亦各自包 try/except，一个失败不拖累其余）。

        **幂等**：重复调用无副作用（第二次时 `_handles` 已空）。
        **可重复 append**：close 之后再 `append` 会重新打开文件，不得崩 ——
        `_handle()` 因此依赖"close 已清空 `_handles`"这一不变式。
        """
        try:
            self.flush()
        except Exception:
            logger.warning("关闭审计前 flush 失败 —— 仍将关闭句柄", exc_info=True)
        for fh in self._handles.values():
            try:
                fh.close()
            except Exception:
                logger.warning("关闭审计句柄失败", exc_info=True)
        self._handles.clear()
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

                # ⚠️ 读侧**复核不变量**，不得静默归一（T1-M4）：
                #    旧写法 `d.get("payload") or {}` 会把 0 / "" / [] / False 全部
                #    吞成 `{}` —— 即审计证据被**静默改写**。审计证据的可信度是这一层
                #    的全部意义，"静默归一"不可接受。不合格的行按损坏行走既有告警路径。
                #    校验失败一律 raise ValueError（**不要**把 TypeError 加进下面的
                #    捕获元组 —— 那会吞掉模型层故障，见 T1-I4 的教训）。
                seq = d["seq"]
                if isinstance(seq, bool) or not isinstance(seq, int):
                    raise ValueError(f"seq 必须是 int（且非 bool），实际为 {type(seq).__name__}")
                kind = d["kind"]
                if not isinstance(kind, str):
                    raise ValueError(f"kind 必须是 str，实际为 {type(kind).__name__}")
                payload = d["payload"]
                if not isinstance(payload, dict):
                    raise ValueError(f"payload 必须是 dict，实际为 {type(payload).__name__}")
                at = d["at"]
                if not isinstance(at, str):
                    raise ValueError(f"at 必须是 str，实际为 {type(at).__name__}")

                # channel 的存在性由 KeyError、合法性由 Channel(...) 的 ValueError 保证。
                out.append(Event(
                    seq=seq, channel=Channel(d["channel"]), kind=kind,
                    payload=payload, at=at,
                ))
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                # ⚠️ 跳过但**不静默** —— 否则"审计文件部分损坏"与"审计本来就少"
                #    回放结果一模一样，无法区分。
                skipped += 1
                logger.warning("审计行无法解析，已跳过：%s (%s)", exc, line[:80])
        if skipped:
            logger.warning("会话 %s 的审计回放跳过了 %d 行", session_id, skipped)
        return tuple(out)
