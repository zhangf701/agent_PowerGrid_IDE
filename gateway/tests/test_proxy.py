import asyncio
from pathlib import Path

import pytest

from powermcp_gateway.config import GatewayConfig
from powermcp_gateway.proxy import call_tool

SCHEMA = {
    "type": "object",
    "properties": {"network_name": {"type": "string"}},
    "required": ["network_name"],
}


def test_invalid_args_are_rejected_without_touching_the_engine(monkeypatch):
    """★ 核心：参数非法时**根本不应发起调用**。"""
    import powermcp_gateway.proxy as proxy

    called = []

    async def fake_dispatch(cfg, server, tool, args):
        called.append((server, tool, args))
        return {"status": "success"}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)

    outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="optimize_network",
        args={"network_name": "n", "linearized": True}, schema=SCHEMA,
    ))

    assert outcome.ok is False
    assert called == [], "非法参数被转发给了引擎"
    assert [v.kind for v in outcome.violations] == ["unknown_arg"]
    assert "linearized" in outcome.error


def test_valid_args_are_forwarded(monkeypatch):
    import powermcp_gateway.proxy as proxy

    async def fake_dispatch(cfg, server, tool, args):
        return {"status": "success", "value": 42}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)

    outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="optimize_network",
        args={"network_name": "n"}, schema=SCHEMA,
    ))
    assert outcome.ok is True
    assert outcome.result["value"] == 42
    assert outcome.violations == ()


def test_engine_error_is_surfaced_not_swallowed(monkeypatch):
    import powermcp_gateway.proxy as proxy

    async def boom(cfg, server, tool, args):
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(proxy, "_dispatch", boom)

    outcome = asyncio.run(call_tool(
        cfg=None, server="surge", tool="run_power_flow",
        args={"network_name": "n"}, schema=SCHEMA,
    ))
    assert outcome.ok is False
    assert "engine exploded" in outcome.error


def test_violation_is_published_to_evidence_channel(monkeypatch):
    """契约 3 的违规必须进审计（通道 A），不得只留在返回值里。"""
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway.session import Channel, EventBus

    async def fake_dispatch(cfg, server, tool, args):
        return {}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)
    bus = EventBus()

    asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="t", args={"nope": 1}, schema=SCHEMA,
        bus=bus, session_id="s1",
    ))

    kinds = [(e.channel, e.kind) for e in bus.events()]
    assert (Channel.EVIDENCE, "contract_violation") in kinds


def test_successful_call_publishes_tool_call_event(monkeypatch):
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway.session import Channel, EventBus

    async def fake_dispatch(cfg, server, tool, args):
        return {"status": "success"}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)
    bus = EventBus()

    asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="t", args={"network_name": "n"},
        schema=SCHEMA, bus=bus, session_id="s1",
    ))
    kinds = [e.kind for e in bus.events()]
    assert "tool_call" in kinds


def test_closed_bus_does_not_lose_the_outcome(monkeypatch):
    """★ 回归：总线已关闭时，结果 / 违规明细**仍必须**交回调用者。

    `EventBus.publish` 在 closed 时 raise RuntimeError。若 `_emit` 不处理，
    `call_tool` 会抛异常 —— 契约 3「返回 ok=False 与违规明细」的承诺被击穿，
    成功路径上更会**丢失一个已经执行完的调用结果**。
    """
    import powermcp_gateway.proxy as proxy
    from powermcp_gateway.session import EventBus

    async def fake_dispatch(cfg, server, tool, args):
        return {"status": "success"}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)
    bus = EventBus()
    bus.close()

    ok_outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="t", args={"network_name": "n"},
        schema=SCHEMA, bus=bus, session_id="s1",
    ))
    assert ok_outcome.ok is True
    assert ok_outcome.result == {"status": "success"}

    bad_outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="t", args={"network_name": "n", "nope": 1},
        schema=SCHEMA, bus=bus, session_id="s1",
    ))
    assert bad_outcome.ok is False
    assert [v.kind for v in bad_outcome.violations] == ["unknown_arg"]


def test_tool_is_error_is_not_reported_as_success(monkeypatch):
    """★ MCP 工具失败的标准形态：**不抛异常**，以 `is_error=True` 返回。

    只取 `content` 会把它报成 `ok=True` —— 正是契约 3 要防的
    「看起来成功、实际没生效」形态的镜像。
    """
    import powermcp_gateway.proxy as proxy

    async def failing_dispatch(cfg, server, tool, args):
        return {"is_error": True, "content": [{"type": "text", "text": "solver diverged"}]}

    monkeypatch.setattr(proxy, "_dispatch", failing_dispatch)

    outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="run_power_flow", args={"network_name": "n"},
        schema=SCHEMA,
    ))
    assert outcome.ok is False
    assert "is_error" in outcome.error
    assert outcome.result["content"][0]["text"] == "solver diverged"


def test_contract_violation_payload_is_a_contract_finding():
    """★ 契约 3 的违规事件必须与 `/contracts/t0` 的 finding **同形**。

    旧实现发的是裸字典 `{contract,server,tool,violations}` —— 缺
    `state`/`reason`/`subject`/`detail`/`evidence`：`ContractFinding(**payload)`
    直接 `TypeError`；且 `summarize()` 需要 `state` 才能参与双轨汇总，缺 state
    的 finding 永远进不了汇总 —— 主徽标不会因契约 3 违规变红，是静默 fail-open。
    """
    import asyncio

    from powermcp_gateway.contracts.model import ContractFinding
    from powermcp_gateway.session import EventBus

    bus = EventBus()
    asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="optimize_network",
        args={"network_name": "n", "linearized": True}, schema=SCHEMA,
        bus=bus, session_id="s1",
    ))

    payloads = [e.payload for e in bus.events() if e.kind == "contract_violation"]
    assert len(payloads) == 1

    # 形状齐全 ⇒ 能用 ContractFinding 反序列化（旧裸字典会在这里 TypeError）
    finding = ContractFinding(**payloads[0])
    assert finding.contract == 3
    assert finding.state == "violated"
    assert finding.subject == "pypsa"
    assert finding.evidence["violations"][0]["arg"] == "linearized"


def test_malformed_schema_does_not_escape_call_tool(monkeypatch):
    """★ 校验器无法判定的畸形 schema 不得让异常逃出 `call_tool`（= HTTP 500）。

    `{"properties": 5}` 是 (a) 层没有（也不应）清洗的畸形 —— `validate_args` 内
    `set(5)` 会 `TypeError`。修正后由 (b) 的 try 兜住：调用**照常转发**（不
    fail-closed 拒发合法调用），但如实发一条 structural unknown，不静默。
    """
    import asyncio

    import powermcp_gateway.proxy as proxy
    from powermcp_gateway.session import EventBus

    called = []

    async def fake_dispatch(cfg, server, tool, args):
        called.append((server, tool, args))
        return {"status": "success"}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)
    bus = EventBus()

    outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="t", args={"x": 1},
        schema={"properties": 5}, bus=bus, session_id="s1",
    ))

    assert outcome.ok is True, "畸形 schema 不应导致调用被拒发"
    assert called, "合法调用必须仍然转发给引擎"

    unknown = [
        e.payload for e in bus.events()
        if e.kind == "contract_unknown"
        and e.payload.get("state") == "unknown"
        and e.payload.get("reason") == "structural"
    ]
    assert unknown, "畸形 schema 必须报 contract_unknown/structural，不得静默"
    assert not [e for e in bus.events() if e.kind == "contract_violation"], (
        "无法判定不是违规 —— 不得混用 contract_violation（那是假警报）"
    )


def test_validator_exception_is_contained_as_structural_unknown(monkeypatch):
    """★ 防御纵深：即便校验器**自身**抛异常，`call_tool` 也绝不能冒泡。

    用 monkeypatch 强制 `validate_args` 抛 `RuntimeError` —— 模拟 (a) 未覆盖的
    畸形输入。断言调用仍返回、仍转发，并发了 structural unknown。
    """
    import asyncio

    import powermcp_gateway.proxy as proxy
    from powermcp_gateway.session import EventBus

    def boom(schema, args):
        raise RuntimeError("validator exploded")

    monkeypatch.setattr(proxy, "validate_args", boom)

    called = []

    async def fake_dispatch(cfg, server, tool, args):
        called.append((server, tool, args))
        return {"status": "success"}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)
    bus = EventBus()

    outcome = asyncio.run(call_tool(
        cfg=None, server="pypsa", tool="t", args={"network_name": "n"},
        schema=SCHEMA, bus=bus, session_id="s1",
    ))

    assert outcome.ok is True, "校验器异常不得冒泡，也不得拒发调用"
    assert called, "校验器异常后仍应转发调用"

    unknown = [
        e.payload for e in bus.events()
        if e.kind == "contract_unknown"
        and e.payload.get("state") == "unknown"
        and e.payload.get("reason") == "structural"
    ]
    assert unknown, "校验器无法判定时必须报 contract_unknown/structural"
    assert "RuntimeError" in unknown[0]["detail"]


# ---------------------------------------------------------------------------
# _dispatch 的真实映射护栏
#
# 上面所有测试都 monkeypatch 掉了 `_dispatch` —— 因此 `_dispatch` 内部的映射代码
# （回传 is_error、拼命令、超时补上下文）**没有任何测试保护**。探针 A 已实测证实：
# 把回传 is_error 那一行删掉，test_proxy.py 仍 7 passed。
#
# 下面这组测试改为 monkeypatch MCP **传输层**（`stdio_client` / `ClientSession`），
# 从而真正走到 `_dispatch` 的映射代码。
# ---------------------------------------------------------------------------


class _FakeContent:
    def __init__(self, text: str) -> None:
        self._text = text

    def model_dump(self) -> dict:
        return {"type": "text", "text": self._text}


class _FakeResult:
    def __init__(self, is_error: bool, texts: tuple[str, ...]) -> None:
        self.is_error = is_error
        self.content = [_FakeContent(t) for t in texts]


def _patch_transport(monkeypatch, *, result=None, hang=False):
    """把 `_dispatch` 依赖的 MCP 传输层换成假的，返回可观测状态字典。

    - `proxy.stdio_client(params)` 作为 `async with ... as (read, write)` 使用；
    - `proxy.ClientSession(read, write)` 作为 `async with ... as session` 使用；
    - 假 session 记录每次 `call_tool(name, arguments=...)`，`hang=True` 时永久挂起
      （用于验证超时路径）。
    """
    import powermcp_gateway.proxy as proxy

    state: dict = {"calls": [], "params": None}

    class FakeSession:
        async def initialize(self) -> None:
            return None

        async def call_tool(self, name, arguments=None):
            state["calls"].append((name, arguments))
            if hang:
                await asyncio.sleep(3600)
            return result

    class FakeStdioCtx:
        async def __aenter__(self):
            return ("read", "write")

        async def __aexit__(self, *exc):
            return False

    class FakeSessionCtx:
        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, *exc):
            return False

    def fake_stdio_client(params):
        state["params"] = params
        return FakeStdioCtx()

    def fake_client_session(read, write):
        return FakeSessionCtx()

    monkeypatch.setattr(proxy, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(proxy, "ClientSession", fake_client_session)
    return state


def _cfg(timeout_s: float = 5.0) -> GatewayConfig:
    return GatewayConfig(powermcp_root=Path("."), python=Path("py"),
                         server_timeout_s=timeout_s)


def test_dispatch_maps_is_error_true(monkeypatch):
    """★ 探针 A 的靶子：`_dispatch` 必须回传 `is_error=True`。

    MCP 工具失败**不抛异常**，以 `isError=True` 返回。丢掉它就会把引擎侧失败
    报成成功 —— 正是契约 3 要防的「看起来成功、实际没生效」形态的镜像。
    """
    import powermcp_gateway.proxy as proxy

    _patch_transport(monkeypatch, result=_FakeResult(True, ("solver diverged",)))
    out = asyncio.run(proxy._dispatch(
        _cfg(), "pypsa", "run_power_flow", {"network_name": "n"}))

    assert out["is_error"] is True
    assert out["content"] == [{"type": "text", "text": "solver diverged"}]


def test_dispatch_maps_is_error_false_and_dumps_content(monkeypatch):
    import powermcp_gateway.proxy as proxy

    _patch_transport(monkeypatch, result=_FakeResult(False, ("ok", "done")))
    out = asyncio.run(proxy._dispatch(
        _cfg(), "pypsa", "optimize_network", {"network_name": "n"}))

    assert out["is_error"] is False
    assert out["content"] == [
        {"type": "text", "text": "ok"},
        {"type": "text", "text": "done"},
    ]


def test_dispatch_forwards_tool_and_args_unchanged(monkeypatch):
    """入参不得被静默改写；命令拼装用 stdin 的 server 名。"""
    from mcp import StdioServerParameters

    import powermcp_gateway.proxy as proxy

    state = _patch_transport(monkeypatch, result=_FakeResult(False, ("ok",)))
    args = {"network_name": "n", "extra": 1}
    asyncio.run(proxy._dispatch(_cfg(), "pypsa", "optimize", args))

    assert state["calls"] == [("optimize", args)]
    assert args == {"network_name": "n", "extra": 1}, "入参被改写了"
    assert isinstance(state["params"], StdioServerParameters)
    assert state["params"].args == ["-m", "powermcp.cli", "run", "pypsa"]
    assert "pypsa" in state["params"].args


def test_dispatch_timeout_error_carries_context(monkeypatch):
    """★ 超时必须给可执行信息：`asyncio.timeout` 的 `TimeoutError` 消息为空，
    `_dispatch` 负责补上 server 名与工具名 —— 否则调用方只看到 "TimeoutError: "。"""
    import powermcp_gateway.proxy as proxy

    _patch_transport(monkeypatch, hang=True)
    with pytest.raises(TimeoutError) as ei:
        asyncio.run(proxy._dispatch(
            _cfg(timeout_s=0.05), "opendss", "solve_snapshot", {"x": 1}))

    msg = str(ei.value)
    assert msg, "超时异常消息为空 —— 未补上下文"
    assert "opendss" in msg, "超时消息缺少 server 名"
    assert "solve_snapshot" in msg, "超时消息缺少工具名"
