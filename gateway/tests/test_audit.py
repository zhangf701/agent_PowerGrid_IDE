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
