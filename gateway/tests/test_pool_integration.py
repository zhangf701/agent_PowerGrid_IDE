"""子项目 4 的**集成层**测试：连接池经 HTTP / chat 生效。

★ 两条核心断言：
  1. `/sessions/{sid}/tools/call` 连续两次调用打到**同一个** server 会话
     （假会话计数器递增）—— 有状态工作流经 HTTP 成立；
  2. 连接断裂重连后，`run_turn` 产出 `notice` 事件告知「状态已丢失」。
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import powermcp_gateway.api as api_mod
from powermcp_gateway.agent import run_turn
from powermcp_gateway.api import create_app
from powermcp_gateway.config import GatewayConfig
from powermcp_gateway.inventory import ToolInventory, ToolRecord
from powermcp_gateway.llm import Chunk, ToolCall
from powermcp_gateway.proxy import CallOutcome
from powermcp_gateway.serverpool import ServerPool
from test_serverpool import FakeConnector   # noqa: I001 —— tests 目录非包，平铺导入


@pytest.fixture
def cfg():
    return GatewayConfig.discover()


def _spec(server: str, name: str) -> ToolRecord:
    return ToolRecord(server=server, name=name, description=f"{name} 描述",
                      input_schema={"type": "object", "properties": {}},
                      output_schema=None)


async def test_pool_persists_state_across_http_calls(monkeypatch, cfg):
    """★ 两次 /tools/call 打到同一个 server 会话 —— T6-M5 根治的 HTTP 层证明。"""
    connector = FakeConnector(); connector.add()
    pool = ServerPool(cfg, connector=connector)

    async def fake_inventory(c, servers, **kwargs):
        return ToolInventory(tools=(_spec("surge", "count_call"),),
                             failures=(), requested=tuple(servers))
    monkeypatch.setattr(api_mod, "build_inventory", fake_inventory)

    app = create_app(cfg=cfg, pool=pool)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = (await c.post("/sessions", json={"servers": ["surge"]})).json()["id"]
        body = {"server": "surge", "tool": "count_call", "args": {}}
        r1 = await c.post(f"/sessions/{sid}/tools/call", json=body)
        r2 = await c.post(f"/sessions/{sid}/tools/call", json=body)

    assert r1.status_code == 200 and r2.status_code == 200
    texts = []
    for r in (r1, r2):
        content = r.json().get("result", {}).get("content", [])
        texts += [item.get("text", "") for item in content if item.get("type") == "text"]
    assert texts == ["count=1", "count=2"], f"两次调用必须命中同一会话：{texts}"
    assert pool.stats()["mounted"] == 1


async def test_remounted_outcome_yields_notice():
    """★ 断裂重连的调用必须让用户看见「状态已丢失」—— run_turn 产出 notice。"""
    class P:
        async def stream_chat(self, messages, tools=None):
            class C:
                text = ""
                tool_calls = (ToolCall(id="1", name="surge__t", arguments="{}"),)
            yield C()

    async def execute(server, tool, args):
        return CallOutcome(ok=True, server=server, tool=tool,
                           result={"is_error": False, "content": []},
                           remounted=True)

    events = [ev async for ev in run_turn(P(), [], specs=[_spec("surge", "t")],
                                          execute=execute)]
    kinds = [e.kind for e in events]
    assert "notice" in kinds
    notice = next(e for e in events if e.kind == "notice")
    assert "状态已丢失" in notice.detail
