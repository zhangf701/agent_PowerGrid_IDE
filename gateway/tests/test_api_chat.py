"""`POST /sessions/{sid}/chat` 的测试。

★ 全部离线：LLM 用脚本化 `FakeProvider`；`build_inventory` 与 `proxy._dispatch`
  都被 monkeypatch —— **不拉起任何真实 MCP server**。
★ 流式端点用 `route.endpoint(...)` 直接调用并迭代 `body_iterator` ——
  `ASGITransport` 对无限流会挂死（子项目 3 的既有教训），虽然本端点会正常结束，
  但直接调用更贴近"逐帧读取"的真实消费方式，也能断言中间帧。
"""

from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

import powermcp_gateway.api as api_mod
import powermcp_gateway.proxy as proxy_mod
from powermcp_gateway.api import create_app
from powermcp_gateway.config import GatewayConfig
from powermcp_gateway.inventory import ServerFailure, ToolInventory, ToolRecord
from powermcp_gateway.llm import Chunk, LlmConfigError, LlmError, ToolCall

_CHAT_PATH = "/sessions/{sid}/chat"


# ---------------------------------------------------------------- 基础设施


class FakeProvider:
    def __init__(self, script: list[list[Chunk]]) -> None:
        self._script = list(script)
        self.calls: list[dict] = []

    async def stream_chat(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        for c in (self._script.pop(0) if self._script else []):
            yield c


def _spec(server: str, name: str, schema: dict | None = None) -> ToolRecord:
    return ToolRecord(
        server=server, name=name, description=f"{name} 描述",
        input_schema=schema if schema is not None else {"type": "object", "properties": {}},
        output_schema=None,
    )


def _patch_inventory(monkeypatch, tools=(), failures=()):
    seen: dict = {}

    async def fake(cfg, servers):
        seen["servers"] = list(servers)
        return ToolInventory(
            tools=tuple(tools), failures=tuple(failures), requested=tuple(servers),
        )

    monkeypatch.setattr(api_mod, "build_inventory", fake)
    return seen


def _patch_dispatch(monkeypatch, text="工具输出"):
    async def fake(cfg, server, tool, args):
        return {"is_error": False, "content": [{"type": "text", "text": text}]}

    monkeypatch.setattr(proxy_mod, "_dispatch", fake)


@pytest.fixture
def cfg():
    return GatewayConfig.discover()


def _endpoint(app):
    for r in app.routes:
        if getattr(r, "path", "") == _CHAT_PATH:
            return r.endpoint
    raise AssertionError("chat 端点未注册")


async def _new_session(app, servers=None) -> str:
    body = {"servers": servers} if servers else {}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/sessions", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def _call(app, sid, payload):
    return await _endpoint(app)(sid, payload)


async def _read(resp) -> str:
    parts: list[str] = []
    async for chunk in resp.body_iterator:
        parts.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return "".join(parts)


def _events(text: str) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        kind: str | None = None
        data: dict | None = None
        for line in block.splitlines():
            if line.startswith("event: "):
                kind = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        assert kind is not None and data is not None, f"畸形 SSE 帧：{block!r}"
        out.append((kind, data))
    return out


def _kinds(events) -> list[str]:
    return [k for k, _ in events]


def _detail(resp) -> dict:
    return json.loads(resp.body.decode())


async def _setup(monkeypatch, provider, tools=(), failures=(), servers=None,
                 modules_root=None, cases_root=None):
    seen = _patch_inventory(monkeypatch, tools, failures)
    _patch_dispatch(monkeypatch)
    # ★ 把模块根与算例根都指到**空目录**，隔离本仓库/真实 HOME 的状态泄漏 ——
    #   否则「启用了模块 → 注入提示词」「登记了算例 → 注入算例现状」都会改变
    #   chat 测试的消息序列假设。需要真实内容的测试用对应参数显式传入。
    import tempfile

    from powermcp_gateway.cases import ENV_CASES_ROOT
    from powermcp_gateway.modules import ENV_MODULES_ROOT

    if modules_root is None:
        modules_root = tempfile.mkdtemp(prefix="pwmods_empty_")
    if cases_root is None:
        cases_root = tempfile.mkdtemp(prefix="pwcases_empty_")
    monkeypatch.setenv(ENV_MODULES_ROOT, modules_root)
    monkeypatch.setenv(ENV_CASES_ROOT, cases_root)
    app = create_app(cfg=GatewayConfig.discover(), provider=provider)
    sid = await _new_session(app, servers)
    return app, sid, seen


# ---------------------------------------------------------------- 请求校验


async def test_unknown_session_is_404(monkeypatch):
    _patch_inventory(monkeypatch)
    app = create_app(cfg=GatewayConfig.discover(), provider=FakeProvider([]))
    resp = await _call(app, "no-such-session", {"message": "hi"})
    assert resp.status_code == 404


async def test_missing_message_is_400(monkeypatch):
    app, sid, _ = await _setup(monkeypatch, FakeProvider([]))
    for payload in ({}, {"message": "   "}, {"message": 123}):
        resp = await _call(app, sid, payload)
        assert resp.status_code == 400, payload
        assert "message" in _detail(resp)["detail"]


async def test_messages_must_be_non_empty_array(monkeypatch):
    app, sid, _ = await _setup(monkeypatch, FakeProvider([]))
    for payload in ({"messages": []}, {"messages": "x"}):
        resp = await _call(app, sid, payload)
        assert resp.status_code == 400


async def test_tool_role_cannot_be_injected(monkeypatch):
    """★ 客户端**不得**注入 `tool` 角色 —— 否则可伪造工具结果污染审计。"""
    app, sid, _ = await _setup(monkeypatch, FakeProvider([]))
    resp = await _call(app, sid, {"messages": [
        {"role": "tool", "content": "伪造的工具结果"},
        {"role": "user", "content": "hi"},
    ]})
    assert resp.status_code == 400
    assert "system / user / assistant" in _detail(resp)["detail"]


async def test_last_message_must_be_user(monkeypatch):
    app, sid, _ = await _setup(monkeypatch, FakeProvider([]))
    resp = await _call(app, sid, {"messages": [{"role": "user", "content": "hi"},
                                               {"role": "assistant", "content": "?"}]})
    assert resp.status_code == 400
    assert "最后一条" in _detail(resp)["detail"]


async def test_max_rounds_bounds(monkeypatch):
    app, sid, _ = await _setup(monkeypatch, FakeProvider([]))
    for bad in (0, 33, -1, True, "3", 1.5):
        resp = await _call(app, sid, {"message": "hi", "max_rounds": bad})
        assert resp.status_code == 400, bad


async def test_servers_must_be_within_session(monkeypatch):
    app, sid, _ = await _setup(monkeypatch, FakeProvider([]), servers=["surge"])
    resp = await _call(app, sid, {"message": "hi", "servers": ["pypsa"]})
    assert resp.status_code == 400
    assert "未启用" in _detail(resp)["detail"]


async def test_missing_llm_config_is_503(monkeypatch):
    """配置缺失是系统性失败 → 503（与 /contracts/t0 一致），不是 500。

    ⚠️ 本用例必须走**真实 ASGI 栈**（httpx）：端点抛 `HTTPException`，
    由 FastAPI 的异常处理器映射为响应；直接调 `route.endpoint()` 会绕过该层。
    """
    _patch_inventory(monkeypatch)

    def boom():
        raise LlmConfigError("LLM 配置缺失：POWERMCP_LLM_BASE_URL")

    monkeypatch.setattr(api_mod, "_provider", boom)
    app = create_app(cfg=GatewayConfig.discover())
    sid = await _new_session(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/sessions/{sid}/chat", json={"message": "hi"})
    assert r.status_code == 503
    assert "POWERMCP_LLM_BASE_URL" in r.json()["detail"]


# ---------------------------------------------------------------- 流式正常路径


async def test_streams_text_then_final(monkeypatch):
    provider = FakeProvider([[Chunk(text="你"), Chunk(text="好")]])
    app, sid, _ = await _setup(monkeypatch, provider)
    resp = await _call(app, sid, {"message": "hi"})
    events = _events(await _read(resp))
    assert _kinds(events) == ["text", "text", "final"]
    assert events[-1][1]["text"] == "你好"


async def test_user_and_assistant_messages_are_persisted_as_evidence(monkeypatch):
    """审计里必须既有"问了什么"也有"答了什么"，否则无法复盘。"""
    app, sid, _ = await _setup(monkeypatch, FakeProvider([[Chunk(text="答案")]]))
    await _read(await _call(app, sid, {"message": "问题"}))
    kinds = {e.kind: e.payload for e in api_mod._STORE.bus(sid).events()}
    assert kinds["user_message"]["content"] == "问题"
    assert kinds["assistant_message"]["content"] == "答案"


async def test_tool_call_round_trip_and_evidence(monkeypatch):
    provider = FakeProvider([
        [Chunk(tool_calls=(ToolCall(id="c1", name="surge__run_power_flow", arguments="{}"),),
               finish_reason="tool_calls")],
        [Chunk(text="算完了。")],
    ])
    app, sid, _ = await _setup(
        monkeypatch, provider, tools=[_spec("surge", "run_power_flow")],
    )
    events = _events(await _read(await _call(app, sid, {"message": "跑个潮流"})))

    assert _kinds(events) == ["tool_call", "text", "final"]
    assert events[0][1] == {"server": "surge", "tool": "run_power_flow", "args": {}}
    # 工具调用必须进总线（EVIDENCE）—— 这是「循环在网关侧」的核心收益
    bus_kinds = [e.kind for e in api_mod._STORE.bus(sid).events()]
    assert "tool_call" in bus_kinds


async def test_contract_violation_blocks_call_inside_loop(monkeypatch):
    """★ 「循环在网关侧」的关键收益：契约 3 的 fail-closed 校验在环内生效。

    工具声明 `network_name` 为必填，模型却传了 `{}` → 必须**拒发**（ok=False）
    且产生 `contract_violation`，而不是把调用放过去。
    """
    schema = {
        "type": "object",
        "properties": {"network_name": {"type": "string"}},
        "required": ["network_name"],
    }
    provider = FakeProvider([
        [Chunk(tool_calls=(ToolCall(id="c1", name="pandapower__run_power_flow", arguments="{}"),),
               finish_reason="tool_calls")],
        [Chunk(text="我漏了参数。")],
    ])
    app, sid, _ = await _setup(
        monkeypatch, provider, tools=[_spec("pandapower", "run_power_flow", schema)],
    )
    dispatched: list = []

    async def spy(cfg, server, tool, args):
        dispatched.append((server, tool, args))
        return {"is_error": False, "content": []}

    monkeypatch.setattr(proxy_mod, "_dispatch", spy)

    events = _events(await _read(await _call(app, sid, {"message": "跑"})))

    assert _kinds(events) == ["tool_error", "text", "final"]
    assert dispatched == [], "契约违规必须 fail-closed —— 不得转发给引擎"
    bus_kinds = [e.kind for e in api_mod._STORE.bus(sid).events()]
    assert "contract_violation" in bus_kinds


async def test_partial_server_failure_is_reported_as_notice(monkeypatch):
    """方案 §4.1「装得上 ≠ 跑得动」：server 拉不起来必须说出来，不得静默少工具。"""
    failures = (ServerFailure(server="opendss", error="握手超时"),)
    app, sid, _ = await _setup(monkeypatch, FakeProvider([[Chunk(text="ok")]]),
                               failures=failures)
    events = _events(await _read(await _call(app, sid, {"message": "hi"})))
    assert _kinds(events)[0] == "notice"
    assert "opendss" in events[0][1]["detail"]
    bus_kinds = [e.kind for e in api_mod._STORE.bus(sid).events()]
    assert "inventory_degraded" in bus_kinds


async def test_servers_narrowing_is_forwarded_to_inventory(monkeypatch):
    provider = FakeProvider([[Chunk(text="ok")]])
    app, sid, seen = await _setup(monkeypatch, provider, servers=["surge", "pypsa"])
    await _read(await _call(app, sid, {"message": "hi", "servers": ["surge"]}))
    assert seen["servers"] == ["surge"]


# ---------------------------------------------------------------- 流式错误路径


async def test_llm_failure_yields_error_event_and_is_recorded(monkeypatch):
    class Boom(FakeProvider):
        async def stream_chat(self, messages, tools=None):
            raise LlmError("LLM 返回 HTTP 401：bad key")
            yield  # pragma: no cover

    app, sid, _ = await _setup(monkeypatch, Boom([]))
    events = _events(await _read(await _call(app, sid, {"message": "hi"})))
    assert _kinds(events) == ["error"]
    assert "401" in events[0][1]["detail"]
    # 失败也要留痕 —— 否则审计里只有"问了"，看不出"为什么没答"
    bus_kinds = [e.kind for e in api_mod._STORE.bus(sid).events()]
    assert "turn_error" in bus_kinds


async def test_inventory_build_failure_yields_error_event(monkeypatch):
    async def boom(cfg, servers):
        raise RuntimeError("配置无法解析")

    monkeypatch.setattr(api_mod, "build_inventory", boom)
    app = create_app(cfg=GatewayConfig.discover(), provider=FakeProvider([]))
    sid = await _new_session(app)
    events = _events(await _read(await _call(app, sid, {"message": "hi"})))
    assert _kinds(events) == ["error"]
    assert "工具清单构建失败" in events[0][1]["detail"]


async def test_multi_turn_history_is_accepted(monkeypatch):
    provider = FakeProvider([[Chunk(text="第三轮回答")]])
    app, sid, _ = await _setup(monkeypatch, provider)
    await _read(await _call(app, sid, {"messages": [
        {"role": "system", "content": "你是电力系统助手"},
        {"role": "user", "content": "第一问"},
        {"role": "assistant", "content": "第一答"},
        {"role": "user", "content": "第二问"},
    ]}))
    sent = provider.calls[0]["messages"]
    assert [m.role for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[0].content == "你是电力系统助手"


# ---------------------------------------------------------------- G-4：模块提示词注入


def _write_prompt_module(root, text: str = "请始终检查单位与判据。") -> None:
    d = root / "demo-mod"
    (d / "prompts").mkdir(parents=True)
    (d / "prompts" / "p.md").write_text(text, encoding="utf-8")
    (d / "module.yaml").write_text(
        "id: demo-mod\nname: 演示\nversion: 0.1.0\nkind: research\nmaturity: L0\n"
        "prompts:\n  - id: p1\n    file: ./prompts/p.md\n",
        encoding="utf-8",
    )


async def test_module_prompts_are_injected_as_system_message(monkeypatch, tmp_path):
    """★ G-4 最小闭环：启用模块的 prompts 进入 LLM 的 system 消息。"""
    from powermcp_gateway.modules import ENV_MODULES_ROOT

    mods = tmp_path / "mods"
    mods.mkdir()
    _write_prompt_module(mods)          # 助手内部会拼 `demo-mod` 目录名
    provider = FakeProvider([[Chunk(text="好的")]])
    app, sid, _ = await _setup(monkeypatch, provider, modules_root=str(mods))
    events = _events(await _read(await _call(app, sid, {"message": "hi"})))
    assert "final" in _kinds(events)
    sent = provider.calls[0]["messages"]
    assert sent[0].role == "system"
    assert "请始终检查单位与判据。" in sent[0].content
    assert sent[1].role == "user" and sent[1].content == "hi"


async def test_no_modules_means_no_injection(monkeypatch, tmp_path):
    """★ 自证条件：无模块时不注入任何 system 消息 —— 内核行为与无模块时一致。"""
    provider = FakeProvider([[Chunk(text="好的")]])
    app, sid, _ = await _setup(monkeypatch, provider)   # 默认空模块根
    await _read(await _call(app, sid, {"message": "hi"}))
    sent = provider.calls[0]["messages"]
    assert [m.role for m in sent] == ["user"]


# ---------------------------------------------------------------- 算例库接线（v4 §4.3）


async def test_registered_cases_are_injected_into_system_message(monkeypatch, tmp_path):
    """★ 算例库接线：用户在界面「登记/解析」的算例，模型必须知道（含路径与解析状态）。"""
    import tempfile as tf
    from powermcp_gateway.cases import ENV_CASES_ROOT

    cases = tmp_path / "cases"; cases.mkdir()
    case_file = tmp_path / "case39.m"
    case_file.write_text("% MATPOWER dummy\n", encoding="utf-8")
    monkeypatch.setenv(ENV_CASES_ROOT, str(cases))

    provider = FakeProvider([[Chunk(text="好的")]])
    app, sid, _ = await _setup(monkeypatch, provider, cases_root=str(cases))

    # 通过真实端点登记算例（与用户在界面上的动作同一条路径）
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/cases", json={"path": str(case_file), "label": "IEEE39 基准"})
    assert r.status_code == 201, r.text

    events = _events(await _read(await _call(app, sid, {"message": "计算潮流"})))
    assert "final" in _kinds(events)
    sent = provider.calls[0]["messages"]
    assert sent[0].role == "system"
    assert "算例库" in sent[0].content
    assert str(case_file) in sent[0].content
    assert "IEEE39 基准" in sent[0].content


async def test_case_context_reports_parsed_state(monkeypatch, tmp_path):
    """登记 + 解析后，system 消息里该算例应标「已解析：是」。"""
    import json as _json
    import tempfile as tf
    from pathlib import Path
    from powermcp_gateway.cases import ENV_CASES_ROOT

    cases = tmp_path / "cases"; cases.mkdir()
    case_file = tmp_path / "case14.m"
    case_file.write_text("% dummy\n", encoding="utf-8")
    monkeypatch.setenv(ENV_CASES_ROOT, str(cases))

    provider = FakeProvider([[Chunk(text="好的")]])
    app, sid, _ = await _setup(monkeypatch, provider, cases_root=str(cases))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        cid = (await c.post("/cases", json={"path": str(case_file)})).json()["case"]["id"]
        # 直接落一个解析产物（不必真拉起 powerio）
        d = cases / cid; d.mkdir()
        (d / "parse.json").write_text(_json.dumps({
            "case_id": cid, "source_path": str(case_file),
            "source_sha256": "x", "value_type": "powerio.BalancedNetwork",
            "ir": "{}", "ir_parsed": True, "parsed_at": "2026-09-25T00:00:00",
        }, ensure_ascii=False), encoding="utf-8")

    await _read(await _call(app, sid, {"message": "hi"}))
    sent = provider.calls[0]["messages"]
    assert sent[0].role == "system"
    assert "已解析：是" in sent[0].content


async def test_case_context_forbids_reparsing(monkeypatch, tmp_path):
    """★ 判据 #1 验收暴露：模型在后续步骤里**重新调了 `powerio.parse`**，
    而附录 A 步骤 4 明确要求「复用同一份 IR，不要重新解析」。

    故上下文必须显式禁止重复 parse，并给出**可执行**的替代路径
    （各引擎的 `*_from_any(file_path=…)` 是引擎自身导入，不算重新解析）。
    """
    import json as _json
    from powermcp_gateway.cases import ENV_CASES_ROOT

    cases = tmp_path / "cases"; cases.mkdir()
    case_file = tmp_path / "case14.m"
    case_file.write_text("% dummy\n", encoding="utf-8")
    monkeypatch.setenv(ENV_CASES_ROOT, str(cases))

    provider = FakeProvider([[Chunk(text="好的")]])
    app, sid, _ = await _setup(monkeypatch, provider, cases_root=str(cases))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        cid = (await c.post("/cases", json={"path": str(case_file)})).json()["case"]["id"]
        d = cases / cid; d.mkdir()
        (d / "parse.json").write_text(_json.dumps({
            "case_id": cid, "source_path": str(case_file),
            "source_sha256": "x", "value_type": "powerio.BalancedNetwork",
            "ir": "{}", "ir_parsed": True, "parsed_at": "2026-09-25T00:00:00",
        }, ensure_ascii=False), encoding="utf-8")

    await _read(await _call(app, sid, {"message": "hi"}))
    ctx = provider.calls[0]["messages"][0].content

    assert "powerio.parse" in ctx, "必须点名要禁的那个工具"
    assert "不要" in ctx and "重新解析" in ctx
    # ★ 不能只说"禁止" —— 还得给出**可执行**的替代（否则模型无从下手，只能照旧重复 parse）
    assert "_from_any" in ctx
    assert "load_network_from_any" in ctx and "import_case_from_any" in ctx
