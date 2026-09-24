import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from powermcp_gateway.api import create_app


@pytest.fixture
def app():
    return create_app()


# ── SSE 生成器（gen()）的测试工装 ──────────────────────────────────────────

def _events_endpoint(app, sid):
    """返回 `(endpoint, request)`，用于**直接驱动** SSE 生成器。

    在 `ASGITransport` 下 `gen()` 永不结束，无法整体 await（见本文件既有注释），
    故取出 `route.endpoint` 手工构造 `Request` 并逐步驱动 `resp.body_iterator`。

    ⚠️ 必须给 `Request` 注入 `receive`：starlette 1.6 的 `is_disconnected()` 会
      `await self._receive()`，裸 `Request` 用 `empty_receive` 会 **抛 RuntimeError**。
      注入一个「返回非 disconnect 消息」的 receive → 恒得 False（模拟客户端仍连着）。
    """
    from starlette.requests import Request

    route = next(r for r in app.routes
                 if getattr(r, "path", None) == "/sessions/{sid}/events")

    async def _receive():
        return {"type": "http.request"}

    request = Request({"type": "http", "method": "GET", "path": "/x",
                       "headers": [], "query_string": b""}, receive=_receive)
    return route.endpoint, request


async def _drive(gen) -> list[str]:
    """把生成器跑到结束，收集所有 SSE 帧（若挂起则由调用方的 wait_for 兜底）。"""
    out: list[str] = []
    async for chunk in gen:
        out.append(chunk)
    return out


async def _wait_until(pred, timeout: float = 2.0) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while not pred():
        if loop.time() > deadline:
            raise AssertionError("等待条件超时")
        await asyncio.sleep(0.005)


def _sse_id(frame: str) -> int:
    """取 SSE 帧的 `id:` 字段（= 事件的单调序列号）。"""
    return int(frame.split("id: ", 1)[1].split("\n", 1)[0])


async def test_create_session(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/sessions", json={"servers": ["pandapower", "pypsa"]})
    assert r.status_code == 200
    body = r.json()
    assert body["id"]
    assert body["servers"] == ["pandapower", "pypsa"]


async def test_create_session_rejects_unknown_server(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/sessions", json={"servers": ["powerworld"]})
    assert r.status_code == 400        # 商业引擎已被方案 v3 移除


async def test_session_events_returns_streaming_response(app):
    """★ `ASGITransport` **无法**测无限流式响应 —— 实测会挂死。

    它会等 ASGI 应用整体结束，而 SSE 永不结束，所以
    `async with c.stream(...)` **连响应头都拿不到**。故直接调用端点函数检查返回对象。

    验证「路由已注册 + 返回 `StreamingResponse` + `media_type` 为 `text/event-stream`」。
    真实 HTTP 下的响应头与断开清理留给 Task 7 的端到端验收；流的序列化由
    `test_events.py` 的 `format_sse` 单测覆盖。
    """
    from fastapi.responses import StreamingResponse
    from starlette.requests import Request

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pypsa"]})).json()["id"]

    route = next(r for r in app.routes
                 if getattr(r, "path", None) == "/sessions/{sid}/events")
    request = Request({"type": "http", "method": "GET", "path": "/x",
                       "headers": [], "query_string": b""})
    resp = await route.endpoint(sid, request)

    assert isinstance(resp, StreamingResponse)
    assert resp.media_type == "text/event-stream"


async def test_unknown_session_events_404(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/sessions/nope/events")
    assert r.status_code == 404


async def test_call_with_valid_args_streams_tool_call_event(app, monkeypatch):
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway import api as api_mod

    async def fake_dispatch(cfg, server, tool, args):
        return {"status": "success", "content": []}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pandapower"]})).json()["id"]

    outcome = await api_mod.call_with_contracts(
        sid, "pandapower", "run_power_flow", {"net": "x"},
        get_schema=lambda s, t: {"properties": {"net": {"type": "string"}}},
    )
    assert outcome.ok is True
    assert "tool_call" in [e.kind for e in api_mod._STORE.bus(sid).events()]


async def test_contract_violation_is_emitted_as_contract_finding(app, monkeypatch):
    """★ 契约违规事件必须与 `/contracts/t0` 的 finding **同形**（原测试名 overpromise）。

    原名为 `..._is_reported_as_finding`，却只断言 `payload["contract"] == 3`
    —— 名字承诺的「被报告为 finding」毫无覆盖（台账反复出现的「测试名 overpromise」）。
    本测试**在 api 层**（经 `call_with_contracts`，即 `api.py` 的接线）补上形状断言：
    payload 必须能原样 `ContractFinding(**payload)` 构造，且关键字段/evidence 正确。
    （proxy 层的同形状断言由 `test_proxy.py` 覆盖 —— 两层各测各的，不重复。）
    """
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway import api as api_mod
    from powermcp_gateway.contracts.model import ContractFinding

    async def fake_dispatch(cfg, server, tool, args):
        return {}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pandapower"]})).json()["id"]

    outcome = await api_mod.call_with_contracts(
        sid, "pandapower", "run_power_flow",
        {"nets": "x"},                                   # ← 拼错的参数名
        get_schema=lambda s, t: {"properties": {"net": {"type": "string"}},
                                 "required": ["net"]},
    )

    assert outcome.ok is False
    viol = [e for e in api_mod._STORE.bus(sid).events() if e.kind == "contract_violation"]
    assert viol, "未发出 contract_violation 事件"

    payload = viol[0].payload
    # ★ 形状断言：payload 必须能被 ContractFinding **原样构造**（同形 + 通过 __post_init__ 校验）
    finding = ContractFinding(**payload)
    assert finding.state == "violated"
    assert finding.subject == "pandapower"
    assert finding.contract == 3
    assert finding.reason is None
    assert finding.evidence["violations"][0]["arg"] == "nets"   # 传入的拼错参数名


async def test_audit_file_records_the_violation(tmp_path, monkeypatch):
    """★ 契约 3 的违规必须落进 NDJSON 审计 —— 只有事件不落盘等于没法事后追。

    注入 tmp_path 的 AuditLog，避免测试往真实 ~/.powermcp/audit 里写文件。
    """
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway import api as api_mod
    from powermcp_gateway.audit import AuditLog

    async def fake_dispatch(cfg, server, tool, args):
        return {}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)
    scratch = AuditLog(tmp_path)
    monkeypatch.setattr(api_mod, "_AUDIT", scratch)

    app = api_mod.create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pandapower"]})).json()["id"]

    await api_mod.call_with_contracts(
        sid, "pandapower", "run_power_flow", {"nets": "x"},
        get_schema=lambda s, t: {"properties": {"net": {"type": "string"}}},
    )
    scratch.flush()

    kinds = [e.kind for e in scratch.replay(sid)]
    assert "contract_violation" in kinds
    assert scratch.path_for(sid).is_file()


async def test_shutdown_flushes_audit(tmp_path, monkeypatch):
    """★ 关闭时**必须** flush 审计 —— 否则缓冲区里的证据事件直接丢失。

    `AuditLog` 是批量写入（每 32 条 flush 一次）。网关没有 shutdown 钩子时，
    进程退出会让缓冲区内容丢失 —— 实测单条违规后审计文件仍是 **0 字节**。

    直接进出 lifespan，不用 `TestClient` —— 后者会在测试输出里引入
    starlette 内部的 `DeprecationWarning`，污染输出。
    """
    from powermcp_gateway import api as api_mod
    from powermcp_gateway.audit import AuditLog
    from powermcp_gateway.session import Channel, Event

    scratch = AuditLog(tmp_path)
    monkeypatch.setattr(api_mod, "_AUDIT", scratch)

    app = api_mod.create_app()

    scratch.append("s1", Event(seq=1, channel=Channel.EVIDENCE, kind="k",
                               payload={}, at="2026-09-24T00:00:00Z"))
    assert scratch.path_for("s1").stat().st_size == 0, "未 flush 前不应落盘"

    async with api_mod._lifespan(app):      # 进入 / 退出 lifespan
        pass

    assert scratch.path_for("s1").stat().st_size > 0, "shutdown 未 flush 审计"


async def test_shutdown_closes_audit_handles(tmp_path, monkeypatch):
    """★ 回归（T1-M7）：lifespan shutdown 必须 **close** 审计句柄。

    `AuditLog` 只 `open("a")`、从不关闭 —— 长生命周期的网关每会话泄漏一个 fd，
    Windows 上还持续占住文件（阻碍外部工具读取/轮转）。

    ⚠️ 区分力：断言写入句柄 `.closed`。若只断言「replay 能读到内容」，
    一个 no-op close 也会通过（replay 内部自己会 flush）—— 测试将毫无区分力。
    经 `app.router.lifespan_context(app)` 进出 —— 走的正是 FastAPI 注册的 lifespan 接线。
    """
    from powermcp_gateway import api as api_mod
    from powermcp_gateway.audit import AuditLog
    from powermcp_gateway.session import Channel, Event

    scratch = AuditLog(tmp_path)
    monkeypatch.setattr(api_mod, "_AUDIT", scratch)
    app = api_mod.create_app()

    scratch.append("s1", Event(seq=1, channel=Channel.EVIDENCE, kind="k",
                               payload={}, at="2026-09-24T00:00:00Z"))
    fh = scratch._handle("s1")
    assert not fh.closed

    async with app.router.lifespan_context(app):
        pass

    assert fh.closed, "lifespan shutdown 未 close 审计句柄（fd 泄漏）"


# ── gen()（SSE 生成器）行为测试 ────────────────────────────────────────────
# 这些直接驱动 `route.endpoint` 返回的 `resp.body_iterator`，覆盖 gen() 的接线行为。

async def test_events_stream_backfills_history_to_late_subscriber(app):
    """★ gen() ①：晚订阅者先收到**历史补发** —— 断线重连不丢早先的证据。"""
    from powermcp_gateway import api as api_mod
    from powermcp_gateway.session import Channel

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pypsa"]})).json()["id"]

    bus = api_mod._STORE.bus(sid)
    bus.publish(Channel.EVIDENCE, "a", {})       # 在订阅**之前**发布 → 只能靠历史补发
    bus.publish(Channel.EVIDENCE, "b", {})

    endpoint, request = _events_endpoint(app, sid)
    resp = await endpoint(sid, request)
    gen = resp.body_iterator                     # 尚未启动（async generator）

    first = await asyncio.wait_for(gen.__anext__(), 2)
    second = await asyncio.wait_for(gen.__anext__(), 2)
    assert [_sse_id(first), _sse_id(second)] == [1, 2]

    bus.close()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), 2)
    assert bus.subscriber_count() == 0


async def test_events_stream_delivers_live_events(app):
    """★ gen() ②：订阅之后发布的事件被**实时**投递（含 is_disconnected 检查不误杀）。"""
    from powermcp_gateway import api as api_mod
    from powermcp_gateway.session import Channel

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pypsa"]})).json()["id"]

    bus = api_mod._STORE.bus(sid)
    endpoint, request = _events_endpoint(app, sid)
    resp = await endpoint(sid, request)
    gen = resp.body_iterator

    pending = asyncio.create_task(gen.__anext__())
    await _wait_until(lambda: bus.subscriber_count() == 1)   # gen 已订阅并阻塞在 q.get()
    bus.publish(Channel.EVIDENCE, "live", {})

    frame = await asyncio.wait_for(pending, 2)
    assert _sse_id(frame) == 1
    assert '"kind": "live"' in frame

    bus.close()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), 2)


async def test_events_stream_terminates_when_bus_closes(app):
    """★ gen() ③：总线关闭后，先排空积压再结束 —— **不得永久挂起**。"""
    from powermcp_gateway import api as api_mod
    from powermcp_gateway.session import Channel

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pypsa"]})).json()["id"]

    bus = api_mod._STORE.bus(sid)
    bus.publish(Channel.EVIDENCE, "a", {})

    endpoint, request = _events_endpoint(app, sid)
    resp = await endpoint(sid, request)
    task = asyncio.create_task(_drive(resp.body_iterator))

    await _wait_until(lambda: bus.subscriber_count() == 1)
    bus.close()                                  # 队列空 → 放入终止哨兵

    frames = await asyncio.wait_for(task, 2)     # 挂起则 → TimeoutError → 失败
    assert [_sse_id(f) for f in frames] == [1]   # 历史既已投递，又正常结束


async def test_events_stream_unsubscribes_on_completion(app):
    """★ gen() ④：生成器结束（客户端断开/总线关闭）后必须注销订阅 —— 不留孤儿。"""
    from powermcp_gateway import api as api_mod

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pypsa"]})).json()["id"]

    bus = api_mod._STORE.bus(sid)
    endpoint, request = _events_endpoint(app, sid)
    resp = await endpoint(sid, request)
    task = asyncio.create_task(_drive(resp.body_iterator))

    await _wait_until(lambda: bus.subscriber_count() == 1)
    assert bus.subscriber_count() == 1

    bus.close()
    await asyncio.wait_for(task, 2)
    assert bus.subscriber_count() == 0            # finally: bus.unsubscribe(q)


async def test_events_stream_self_terminates_when_lagged(app):
    """★ gen() ⑤（I-2）：队列被撑满而标记滞后后，生成器**主动结束**。

    滞后即「该订阅者已跟不上」—— 让其结束连接、由浏览器重连并按历史全量重放，
    而不是继续半速跟随。这是 `api.py` 里 `bus.is_lagged(q)` 接线的行为断言。
    """
    from powermcp_gateway import api as api_mod
    from powermcp_gateway.session import Channel

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pypsa"]})).json()["id"]

    bus = api_mod._STORE.bus(sid)
    endpoint, request = _events_endpoint(app, sid)
    resp = await endpoint(sid, request)
    task = asyncio.create_task(_drive(resp.body_iterator))

    await _wait_until(lambda: bus.subscriber_count() == 1)
    for i in range(1025):                        # 撑满 maxsize=1024 并触发满队列
        bus.publish(Channel.EVIDENCE, "noise", {"i": i})
    assert bus.stats()["lagged_queues"] == 1

    await asyncio.wait_for(task, 3)              # 滞后 → gen 主动 return（不挂起）
    assert bus.subscriber_count() == 0           # 且已注销


async def test_events_stream_deduplicates_history_and_live(app, monkeypatch):
    """★ gen() ⑥（C1，审查探针 C 靶心）：同一条事件**既在历史快照又在订阅队列**时只投一次。

    `event.seq <= last_seq: continue` 这条去重分支因 `subscribe_queue()` 与
    `bus.events()` 相邻同步调用而**不可自然触发**，须注入才测得到：
    monkeypatch **该 bus 实例**的 `events`，在返回真实快照**之前**先 `publish` 一条
    —— 于是它既进了返回的快照、也进了已订阅的队列。
    """
    from powermcp_gateway import api as api_mod
    from powermcp_gateway.session import Channel

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pypsa"]})).json()["id"]

    bus = api_mod._STORE.bus(sid)
    real_events = bus.events

    def events_and_inject():
        bus.publish(Channel.EVIDENCE, "injected", {})   # 既进快照、也进订阅队列
        return real_events()

    monkeypatch.setattr(bus, "events", events_and_inject)

    endpoint, request = _events_endpoint(app, sid)
    resp = await endpoint(sid, request)
    gen = resp.body_iterator

    first = await asyncio.wait_for(gen.__anext__(), 2)
    assert _sse_id(first) == 1                    # 历史补发出了这条

    # 队列里还留着同一条（seq=1）：去重分支命中 → 不再产出，阻塞在 q.get()
    pending = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0.02)
    assert not pending.done(), "seq 去重失效：同一条事件被第二次投递"

    bus.close()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(pending, 2)


async def test_events_stream_stops_on_client_disconnect(app, monkeypatch):
    """★ gen() ⑦（C2，审查探针 C 靶心）：空闲轮询到客户端已断开 → 结束并注销订阅。

    覆盖 `except asyncio.TimeoutError:` 里的 `if await request.is_disconnected(): return`
    （Task 6 修的另一个核心错误路径）。**有界等待**：变异时表现为失败而非挂死。
    """
    from powermcp_gateway import api as api_mod

    monkeypatch.setattr(api_mod, "_DISCONNECT_POLL_S", 0.01)   # 加速轮询

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pypsa"]})).json()["id"]

    bus = api_mod._STORE.bus(sid)
    endpoint, request = _events_endpoint(app, sid)

    async def _disconnected():
        return True                                # 客户端已断开

    monkeypatch.setattr(request, "is_disconnected", _disconnected)

    resp = await endpoint(sid, request)
    gen = resp.body_iterator

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), 1)   # 有界：挂死 → TimeoutError → 失败
    assert bus.subscriber_count() == 0            # 断开后已注销


# ── /sessions/{sid}/tools/call 路由（HTTP 端到端）──────────────────────────
# 以上测试打的是 `api_mod.call_with_contracts`（**函数**），路由本身零覆盖（N-5）。
# 下面经 `POST /sessions/{sid}/tools/call` 覆盖 M-2/M-3：
#   缺字段 → 400（不再是 500）、工具不存在 → 404、配置/清单失败 → 503、
#   成功路径的 `dataclasses.asdict(outcome)` 序列化。


def _fake_inventory(*tools):
    """构造一个只含给定工具的 `ToolInventory`（测试用最小真源）。"""
    from powermcp_gateway.inventory import ToolInventory

    return ToolInventory(tools=tuple(tools), failures=(), requested=("pandapower",))


def _tool_record(**over):
    from powermcp_gateway.inventory import ToolRecord

    base = dict(
        server="pandapower",
        name="run_power_flow",
        description=None,
        input_schema={"properties": {"net": {"type": "string"}}},
        output_schema=None,
    )
    base.update(over)
    return ToolRecord(**base)


async def test_tools_call_unknown_session_404(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/sessions/nope/tools/call",
                         json={"server": "pandapower", "tool": "run_power_flow"})
    assert r.status_code == 404


async def test_tools_call_missing_server_field_400(app):
    """★ 缺 `server` 键必须是 400（客户端错误），**不再是 500**（M-2）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pandapower"]})).json()["id"]
        r = await c.post(f"/sessions/{sid}/tools/call", json={"tool": "run_power_flow"})
    assert r.status_code == 400
    assert "server" in r.json()["detail"]


async def test_tools_call_missing_tool_field_400(app):
    """★ 缺 `tool` 键同样必须是 400（M-2）。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pandapower"]})).json()["id"]
        r = await c.post(f"/sessions/{sid}/tools/call", json={"server": "pandapower"})
    assert r.status_code == 400
    assert "tool" in r.json()["detail"]


async def test_tools_call_unknown_tool_404(app, monkeypatch):
    """工具不在清单里（此处清单为空）→ 404，而非 500。"""
    from pathlib import Path

    from powermcp_gateway import api as api_mod
    from powermcp_gateway.config import GatewayConfig

    monkeypatch.setattr(
        api_mod, "_cfg",
        lambda: GatewayConfig(powermcp_root=Path("."), python=Path("py")),
    )

    async def fake_inv(cfg, servers, timeout_s=None):
        return _fake_inventory()                       # 空清单 → recs 为空

    monkeypatch.setattr(api_mod, "build_inventory", fake_inv)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pandapower"]})).json()["id"]
        r = await c.post(f"/sessions/{sid}/tools/call",
                         json={"server": "pandapower", "tool": "nope", "args": {}})
    assert r.status_code == 404


async def test_tools_call_success_serializes_outcome(app, monkeypatch):
    """★ 成功路径：钉住 `dataclasses.asdict(outcome)` 的序列化与路由接线。

    打桩方式选择：monkeypatch `api_mod.build_inventory`（造清单）+ `_cfg`（避开
    真实配置发现）+ `proxy._dispatch`（不拉起引擎），**让真实的路由 → `call_with_contracts`
    → `call_tool` 链路跑通**。理由：本测试要覆盖的正是**路由自身的接线**（取 `recs[0].
    input_schema` 作 `get_schema`、经会话总线求值、`asdict` 序列化）—— 只打桩 `_dispatch`
    即可让这整条链真实执行，比直接打桩 `call_with_contracts` 覆盖更深；而 `build_inventory`
    必须打桩，否则会真的拉起 stdio 子进程。
    """
    from pathlib import Path

    import powermcp_gateway.proxy as proxy
    from powermcp_gateway import api as api_mod
    from powermcp_gateway.config import GatewayConfig

    monkeypatch.setattr(
        api_mod, "_cfg",
        lambda: GatewayConfig(powermcp_root=Path("."), python=Path("py")),
    )

    async def fake_inv(cfg, servers, timeout_s=None):
        return _fake_inventory(_tool_record())

    monkeypatch.setattr(api_mod, "build_inventory", fake_inv)

    seen: dict = {}

    async def fake_dispatch(cfg, server, tool, args):
        seen["called"] = (server, tool, args)
        return {"is_error": False, "content": [{"type": "text", "text": "ok"}]}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pandapower"]})).json()["id"]
        r = await c.post(f"/sessions/{sid}/tools/call",
                         json={"server": "pandapower", "tool": "run_power_flow",
                               "args": {"net": "x"}})

    assert r.status_code == 200
    body = r.json()                                    # 能被 JSON 解析即覆盖 asdict 序列化
    assert body["ok"] is True
    assert body["server"] == "pandapower"
    assert body["tool"] == "run_power_flow"
    assert body["result"]["content"][0]["text"] == "ok"
    assert seen["called"] == ("pandapower", "run_power_flow", {"net": "x"})


async def test_tools_call_config_failure_is_503(app, monkeypatch):
    """★ `_cfg()` 失败必须映射为 503（与 `/contracts/t0` 同语义），不是 500（M-3）。"""
    from powermcp_gateway import api as api_mod
    from powermcp_gateway.config import ConfigError

    def boom():
        raise ConfigError("配置无法解析")

    monkeypatch.setattr(api_mod, "_cfg", boom)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["pandapower"]})).json()["id"]
        r = await c.post(f"/sessions/{sid}/tools/call",
                         json={"server": "pandapower", "tool": "run_power_flow", "args": {}})
    assert r.status_code == 503