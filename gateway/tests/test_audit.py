import json

import pytest

from powermcp_gateway.audit import AuditLog
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
