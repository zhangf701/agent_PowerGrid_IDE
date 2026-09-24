import json

from powermcp_gateway.events import format_sse
from powermcp_gateway.session import Channel, Event


def test_format_sse_includes_id_and_event_name():
    ev = Event(seq=7, channel=Channel.EVIDENCE, kind="contract",
               payload={"contract": 3}, at="2026-09-24T00:00:00Z")
    frame = format_sse(ev)

    assert frame.endswith("\n\n")
    lines = dict(
        (l.split(": ", 1) for l in frame.strip().splitlines() if ": " in l)
    )
    assert lines["id"] == "7"                       # 序列号即 id —— 断线重连可续
    assert lines["event"] == "evidence"             # ★ 通道即事件名
    assert json.loads(lines["data"])["payload"]["contract"] == 3


def test_format_sse_telemetry_uses_its_own_event_name():
    ev = Event(seq=8, channel=Channel.TELEMETRY, kind="progress", payload={},
               at="2026-09-24T00:00:00Z")
    assert "event: telemetry" in format_sse(ev)
