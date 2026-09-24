import json

import pytest

from powermcp_gateway.audit import _FLUSH_EVERY, AuditLog
from powermcp_gateway.session import Channel, Event


def _ev(seq: int, channel=Channel.EVIDENCE, kind="tool_call", payload=None) -> Event:
    return Event(seq=seq, channel=channel, kind=kind,
                 payload=payload or {"a": seq}, at="2026-09-24T00:00:00Z")


def test_append_writes_ndjson_one_event_per_line(tmp_path):
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))
    log.append("s1", _ev(2))
    log.flush()

    lines = log.path_for("s1").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["seq"] == 1
    assert first["channel"] == "evidence"
    assert first["kind"] == "tool_call"


def test_telemetry_is_not_audited(tmp_path):
    """通道 B 不入审计 —— 否则审计被进度噪声淹没。"""
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1, channel=Channel.TELEMETRY, kind="progress"))
    log.append("s1", _ev(2, channel=Channel.EVIDENCE))
    log.flush()

    lines = log.path_for("s1").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["seq"] == 2


def test_replay_returns_events_in_order(tmp_path):
    log = AuditLog(tmp_path)
    for i in range(1, 6):
        log.append("s1", _ev(i))
    log.flush()

    events = log.replay("s1")
    assert [e.seq for e in events] == [1, 2, 3, 4, 5]
    assert events[0].channel is Channel.EVIDENCE


def test_replay_missing_session_is_empty(tmp_path):
    assert AuditLog(tmp_path).replay("nope") == ()


def test_replay_skips_corrupt_trailing_line(tmp_path):
    """进程被杀死时最后一行可能写了一半 —— 回放必须跳过而不是崩。"""
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))
    log.flush()
    with log.path_for("s1").open("a", encoding="utf-8") as fh:
        fh.write('{"seq": 2, "channel": "evi')   # 截断

    assert [e.seq for e in log.replay("s1")] == [1]


def test_audit_file_per_session(tmp_path):
    log = AuditLog(tmp_path)
    assert log.path_for("s1") != log.path_for("s2")
    assert log.path_for("s1").name.startswith("audit-s1")


# ── 以下为实现者实测发现的回归测试 ──────────────────────────────────────

def test_replay_sees_events_appended_without_explicit_flush(tmp_path):
    """★ 回归：append 有缓冲，replay 必须先 flush。

    初版 replay 直接 read_text，而 append 写的是带缓冲的文件对象 ——
    `_FLUSH_EVERY` 以内的事件**完全不可见**，且**静默返回**而非报错。
    原 6 条测试都在 replay 前调了 flush()，因此这个缺口毫无覆盖。
    """
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))
    log.append("s1", _ev(2))       # 故意不调 flush()

    assert [e.seq for e in log.replay("s1")] == [1, 2]


def test_replay_skips_valid_json_that_is_not_an_object(tmp_path):
    """★ 回归：截断的尾部可能是**合法 JSON 但不是对象**（如 `12345`）。

    初版只捕 JSONDecodeError，这种输入会抛 TypeError 把回放打崩，
    与 docstring 承诺的"不让回放崩掉"矛盾。
    """
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))
    log.flush()
    with log.path_for("s1").open("a", encoding="utf-8") as fh:
        fh.write("12345\n")            # 合法 JSON，不是对象
        fh.write('"just a string"\n')

    assert [e.seq for e in log.replay("s1")] == [1]


def test_replay_survives_a_torn_multibyte_tail(tmp_path):
    """★ 回归：撕裂写入切断一个**多字节字符**时，回放不得整体崩掉。

    写入用 `ensure_ascii=False`，payload 常含中文；一次撕裂写入会留下
    半个 UTF-8 字符。`read_text` 不带 `errors=` 会抛 UnicodeDecodeError ——
    而读取是整文件的，于是**整个会话的审计全部读不出来**，远不止坏的那一行。
    （审查者已实测复现。）
    """
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))
    log.flush()

    # 手工追加一条被切断的多字节尾部（"中" 的 UTF-8 是 e4 b8 ad）
    with log.path_for("s1").open("ab") as fh:
        fh.write(b'{"seq": 2, "kind": "\xe4\xb8')

    events = log.replay("s1")          # 初版会在此抛 UnicodeDecodeError
    assert [e.seq for e in events] == [1]


def test_replay_preserves_events_containing_unicode_line_separators(tmp_path):
    """★ 回归：payload 含 U+2028 / U+2029 / U+0085 时，**完整合法**的事件不得丢。

    这三个码点 ≥ 0x20，`json.dumps(ensure_ascii=False)` **不转义**它们；
    而 `str.splitlines()` 把它们当行边界 → 一条完好的事件被切成两段、
    两段都解析失败 → 整条 EVIDENCE 在回放中消失，且被误报为"损坏行"。
    命中「证据不可丢」这条核心不变量。
    """
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1, payload={"text": "a\u2028b"}))   # LINE SEPARATOR
    log.append("s1", _ev(2, payload={"text": "c\u2029d"}))   # PARAGRAPH SEPARATOR
    log.append("s1", _ev(3, payload={"text": "e\u0085f"}))   # NEXT LINE
    log.flush()

    events = log.replay("s1")
    assert [e.seq for e in events] == [1, 2, 3], "含 U+2028/2029/0085 的完整事件被丢弃"
    assert events[0].payload["text"] == "a\u2028b"


# ── 以下为本轮修复（T1-M4 / T1-M7 / T1-M8）的回归测试 ────────────────────

def _write_raw(log: AuditLog, session_id: str, raw: str) -> None:
    """绕过 append，向审计文件**原始**追加一行（模拟外部/损坏写入）。"""
    with log.path_for(session_id).open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(raw + "\n")


def test_replay_skips_payload_that_is_not_a_dict(tmp_path):
    """★ 回归（T1-M4）：读侧必须**复核不变量**，不得把 falsy payload 静默归一成 {}。

    旧写法 `d.get("payload") or {}`（`audit.py`）把 0 / "" / [] / False 全部吞成 `{}`
    —— 即审计证据被**静默改写**。审计证据的可信度是这一层的全部意义，
    "静默归一"不可接受：这样的行必须按**损坏行**跳过并告警。
    """
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))                        # 正常行
    log.flush()
    _write_raw(log, "s1", json.dumps(
        {"seq": 2, "channel": "evidence", "kind": "x", "payload": 0,
         "at": "2026-09-24T00:00:00Z"}))
    _write_raw(log, "s1", json.dumps(
        {"seq": 3, "channel": "evidence", "kind": "x", "payload": [],
         "at": "2026-09-24T00:00:00Z"}))

    events = log.replay("s1")
    assert [e.seq for e in events] == [1], "payload=0 / [] 的行被读回，未按损坏行跳过"
    assert all(e.payload != {} for e in events), "坏行被静默归一成了 payload={}"


def test_replay_skips_seq_that_is_not_an_int(tmp_path):
    """★ 回归（T1-M4）：`seq` 必须是 int 且非 bool —— 字符串 seq 按损坏行跳过。"""
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))
    log.flush()
    _write_raw(log, "s1", json.dumps(
        {"seq": "3", "channel": "evidence", "kind": "x", "payload": {},
         "at": "2026-09-24T00:00:00Z"}))
    _write_raw(log, "s1", json.dumps(
        {"seq": True, "channel": "evidence", "kind": "x", "payload": {},
         "at": "2026-09-24T00:00:00Z"}))          # bool 也是 int —— 必须排除

    assert [e.seq for e in log.replay("s1")] == [1]


def test_close_actually_closes_and_flushes(tmp_path):
    """★ 回归（T1-M7）：`close()` 必须真的关闭句柄 + flush + **幂等**。

    旧实现只有 `open("a")`、永不 close —— 长生命周期的网关每会话泄漏一个 fd；
    Windows 上还持续占住文件（阻碍外部工具读取/轮转）。close 必须先 flush，
    否则缓冲区内的证据会丢。

    ⚠️ 区分力：**必须断言写入句柄 `.closed`** —— 若只断言 `replay()` 能读到内容，
    则一个「no-op close」也会通过（`replay()` 内部自己会 `flush()`），测试将毫无区分力。
    """
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))
    fh = log._handle("s1")                           # 写入句柄（close 前应打开）
    assert not fh.closed

    log.close()
    assert fh.closed, "close() 未真正关闭文件句柄（fd 泄漏）"

    log.close()                                      # 第二次应是 no-op，不得抛
    assert [e.seq for e in log.replay("s1")] == [1]  # close 生效（flush 已落盘）


def test_append_after_close_reopens(tmp_path):
    """★ 回归（T1-M7）：close() 之后再 append 不得崩 —— 应重新打开文件。"""
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))
    log.close()
    log.append("s1", _ev(2))                         # 重新打开，不得抛
    assert [e.seq for e in log.replay("s1")] == [1, 2]


def test_close_closes_handles_even_if_flush_raises(tmp_path, monkeypatch):
    """★ B2：即使 flush 抛异常，close() **仍必须关闭句柄**（释放 fd 是第一职责）。

    若 flush 失败就把句柄一起留着，T1-M7 的「每会话泄漏一个 fd」会在失败路径上原样复发。
    """
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))
    fh = log._handle("s1")

    def _boom():
        raise RuntimeError("flush 爆炸")

    monkeypatch.setattr(fh, "flush", _boom)

    log.close()                                      # 不得外抛
    assert fh.closed, "flush 失败后 close() 未关闭句柄（fd 泄漏复发）"


def test_append_writes_strict_lf(tmp_path):
    """★ 回归（T1-M8）：写侧必须是**严格 LF**（跨进程 NDJSON）。

    Windows 上默认文本模式会把 "\\n" 翻译成 "\\r\\n"（实测 `b"\\r\\n" in raw == True`）。
    读侧虽用 .strip() 容忍，但方案把 NDJSON 定位为跨进程证据格式，
    外部消费者不应被迫同样容忍。
    """
    log = AuditLog(tmp_path)
    log.append("s1", _ev(1))
    log.flush()

    raw = log.path_for("s1").read_bytes()
    assert b"\r\n" not in raw, "写侧输出了 CRLF，非严格 NDJSON"
    assert raw.endswith(b"\n")


# ── C-2：审计写失败必须可观测（I-2 之后唯一残留的静默降级路径）─────────────


def test_append_returns_true_on_success(tmp_path):
    """成功路径返回 True —— 调用方（`proxy._emit`）靠它区分"已持久化"与"只在内存里"。"""
    log = AuditLog(tmp_path)
    assert log.append("s1", _ev(1)) is True
    # 通道 B 不入审计是**设计行为**，不是失败
    assert log.append("s1", _ev(2, channel=Channel.TELEMETRY)) is True
    st = log.stats()
    assert st["append_failures"] == 0
    assert st["last_error"] is None


def test_append_failure_is_counted_once_and_does_not_raise(tmp_path):
    """★ 磁盘/权限失败时：**不抛**（事件已进总线历史，不能反过来打断一个已执行完的
    调用结果），但必须**可观测** —— 累计计数 + `last_error` + error 级日志。

    且**一次 append 只计 1 次失败**：打开句柄 / write / 阈值触发的 flush 必须包在
    **同一处** try 内，否则磁盘满时 write 与 flush 各记一次，会虚增丢失量级。
    """
    log = AuditLog(tmp_path)

    class _Boom:
        def write(self, _s):
            raise OSError("No space left on device")

        def flush(self):
            raise OSError("No space left on device")

        def close(self):
            pass

    log._handles["s1"] = _Boom()
    log._pending["s1"] = _FLUSH_EVERY - 1     # 下一次 append 会同时触发 write 与 flush

    assert log.append("s1", _ev(1)) is False
    assert log.stats()["append_failures"] == 1, "一次故障被重复计数（write+flush 各记一次）"

    assert log.append("s1", _ev(2)) is False
    assert log.stats()["append_failures"] == 2
    assert "No space left" in (log.stats()["last_error"] or "")


def test_stats_reports_handles_as_current_state(tmp_path):
    """`handles` 是**现状量**，与 `append_failures` 的累计量互补。"""
    log = AuditLog(tmp_path)
    assert log.stats()["handles"] == 0
    log.append("s1", _ev(1))
    log.append("s2", _ev(1))
    assert log.stats()["handles"] == 2
    log.close()
    assert log.stats()["handles"] == 0
