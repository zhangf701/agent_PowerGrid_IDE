"""`serverpool.py`（子项目 4 / T6-M5 根治）的测试。

★ 本文件最重要的不变式：
  1. **同一 (session, server) 的多次调用复用同一会话对象** —— 这是「有状态工作流」
     成立的全部理由（用假会话的内部计数器证明）；
  2. **连接断裂 → 重连一次并重跑同一调用**，且 `remounted=True` 如实上报；
  3. **普通工具失败（is_error / 引擎报错）绝不触发重连** —— 那会掩盖真问题；
  4. LRU 上限、会话清理、池关闭都要真正杀掉连接 task（不泄漏）。

全部离线：`FakeConnector` 提供有状态假会话，不拉起任何真进程。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from anyio import BrokenResourceError

from powermcp_gateway.config import GatewayConfig
from powermcp_gateway.serverpool import MountError, ServerPool

CFG = GatewayConfig.discover()


class FakeSession:
    """有状态假会话：`count_call` 调用返回**本会话**累计次数 —— 跨调用一致即证明复用。"""

    def __init__(self, *, fail_calls: int = 0, hang_calls: int = 0,
                 init_fails: bool = False,
                 exc_on_call: Exception | None = None) -> None:
        self.counter = 0
        self.calls = 0
        self.fail_calls = fail_calls      # 前 N 次 call_tool 抛连接断裂
        self.hang_calls = hang_calls      # 前 N 次 call_tool 永久悬挂
        self.init_fails = init_fails
        self.exc_on_call = exc_on_call    # 每次调用都抛该异常（引擎级失败，连接没断）
        self.closed = False

    async def initialize(self):
        if self.init_fails:
            raise RuntimeError("server 起不来（模拟）")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()
        return False

    async def call_tool(self, tool, arguments=None):
        self.calls += 1
        if self.hang_calls >= self.calls:
            await asyncio.sleep(3600)               # 永久悬挂（触发超时丢弃）
        if self.calls <= self.fail_calls:
            raise BrokenResourceError("管道断了（模拟）")
        if self.exc_on_call is not None:
            raise self.exc_on_call
        self.counter += 1
        return _FakeResult(content=[_FakeText(f"count={self.counter}")])


    async def aclose(self):
        self.closed = True


class _FakeText:
    def __init__(self, text): self.text = text
    def model_dump(self): return {"type": "text", "text": self.text}


class _FakeResult:
    def __init__(self, content): self.content = content
    is_error = False


class FakeConnector:
    """每次挂载产出一个 FakeSession。

    - `_pending`：预配置的会话队列（按序消费）；
    - `created`：**所有**产出过的会话（含自动补位的）—— 测试断言用它，不会被 pop 走。
    """

    def __init__(self, sessions: list[FakeSession] | None = None):
        self._pending: list[FakeSession] = list(sessions or [])
        self.created: list[FakeSession] = []

    def add(self, **kw) -> FakeSession:
        s = FakeSession(**kw)
        self._pending.append(s)
        return s

    @asynccontextmanager
    async def __call__(self, params):
        s = self._pending.pop(0) if self._pending else FakeSession()
        self.created.append(s)
        async with s:
            yield s


@pytest.fixture
def cfg():
    return CFG


# ---------------------------------------------------------------- 状态持久


async def test_same_session_is_reused_across_calls(cfg):
    """★ 核心不变式：同 (sid, server) 多次调用 = 同一会话对象，状态延续。"""
    conn = FakeConnector(); conn.add()
    pool = ServerPool(cfg, connector=conn)
    r1 = await pool.call("s1", "surge", "load_network", {})
    r2 = await pool.call("s1", "surge", "run_power_flow", {})
    assert not r1.remounted and not r2.remounted
    assert "count=1" in str(r1.result["content"])
    assert "count=2" in str(r2.result["content"]), "第二次调用拿到的是**同一会话**的计数"
    assert len(conn.created) == 1


async def test_different_sessions_get_different_connections(cfg):
    """不同会话各自有独立连接 —— 各自的计数器都从 1 开始。"""
    conn = FakeConnector(); conn.add(); conn.add()
    pool = ServerPool(cfg, connector=conn)
    r1 = await pool.call("s1", "surge", "noop", {})
    r2 = await pool.call("s2", "surge", "noop", {})
    assert "count=1" in str(r1.result["content"])
    assert "count=1" in str(r2.result["content"]), "s2 是**另一个**会话，计数独立"
    assert pool.stats()["mounted"] == 2


# ---------------------------------------------------------------- 断裂与重连


async def test_broken_connection_remounts_once_and_reruns(cfg):
    """★ 连接断裂 → 重连一次并重跑同一调用；remounted=True 如实上报。"""
    conn = FakeConnector()
    conn.add(fail_calls=1)          # 第 1 个会话：第一次调用就断
    conn.add()                      # 重连后用的会话
    pool = ServerPool(cfg, connector=conn)
    r = await pool.call("s1", "surge", "load_network", {})
    assert r.remounted is True
    assert "count=1" in str(r.result["content"])
    assert pool.remounts == 1 and len(conn.created) == 2


async def test_tool_failure_does_not_remount(cfg):
    """★ 引擎级失败（连接没断）**不重连** —— 重连会掩盖真问题。"""
    conn = FakeConnector()
    conn.add(exc_on_call=ValueError("solver diverged（引擎报错，连接没断）"))
    pool = ServerPool(cfg, connector=conn)
    with pytest.raises(ValueError):
        await pool.call("s1", "surge", "run_power_flow", {})
    assert pool.remounts == 0 and len(conn.created) == 1


async def test_hung_call_times_out_and_connection_is_dropped(cfg):
    """★ 超时的连接处于未知状态 —— 自动丢弃并重连重跑（宁可重挂也不复用可疑连接）。"""
    conn = FakeConnector(); conn.add(hang_calls=1); conn.add()
    pool = ServerPool(cfg, connector=conn)
    r = await pool.call("s1", "surge", "hang", {}, timeout_s=0.2)
    assert r.remounted is True and "count=1" in str(r.result["content"])
    assert len(conn.created) == 2 and conn.created[0].closed
    assert pool.remounts == 1


async def test_mount_failure_is_mounterror(cfg):
    """挂载失败重试一次后仍失败 → MountError 上抛（不无限重试）。"""
    conn = FakeConnector(); conn.add(init_fails=True); conn.add(init_fails=True)
    pool = ServerPool(cfg, connector=conn)
    with pytest.raises(MountError):
        await pool.call("s1", "surge", "x", {})
    assert pool.remounts == 1 and len(conn.created) == 2


# ---------------------------------------------------------------- 生命周期


async def test_lru_eviction_drops_oldest(cfg):
    conn = FakeConnector()
    pool = ServerPool(cfg, connector=conn, max_per_session=2)
    for server in ("a", "b", "c"):
        await pool.call("s1", server, "x", {})
    assert pool.stats()["mounted"] == 2 and pool.stats()["evictions"] == 1
    # 被淘汰的是最久未用的 "a"：再用它要重新挂载 → 新会话
    await pool.call("s1", "a", "x", {})
    assert pool.stats()["evictions"] == 2


async def test_drop_session_closes_its_connections(cfg):
    conn = FakeConnector(); conn.add(); conn.add()
    pool = ServerPool(cfg, connector=conn)
    await pool.call("s1", "surge", "x", {})
    await pool.call("s1", "pypsa", "x", {})
    await pool.call("s2", "surge", "x", {})
    assert pool.stats()["mounted"] == 3
    await pool.drop_session("s1")
    assert pool.stats()["mounted"] == 1
    assert conn.created[0].closed and conn.created[1].closed


async def test_aclose_closes_everything(cfg):
    conn = FakeConnector(); conn.add(); conn.add()
    pool = ServerPool(cfg, connector=conn)
    await pool.call("s1", "surge", "x", {})
    await pool.call("s2", "surge", "x", {})
    await pool.aclose()
    assert pool.stats()["mounted"] == 0
    assert all(s.closed for s in conn.created)
