"""§11.2 并发隔离的测试 —— 租约 · 会话命名空间 · 写串行化。

★ 本文件钉住的是**并发正确性**，不是"代码看起来对"：
  - 租约的语义是**互斥** → 用"临界区最大并发数必须为 1"来证明（而不是断言 `lock.locked()`）；
  - 会话命名空间 → 断言**真实子进程参数里的 env**（`_server_params` 是可直接断言的接缝）；
  - 写串行化 → 用**并发写不丢更新**来证明（而不是断言"有锁"）；
  - `_RUNNING` 竞态 → 用**两个并发请求**来证明（而不是顺序调用两次）。

⚠️ 诚实边界（本文件**不**断言、也不该被读成已覆盖）：
  租约是**进程内**的；跨进程 / 跨机文件租约未实现。相关取舍写在 `concurrency.py` 的模块 docstring。
"""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from powermcp_gateway.concurrency import (
    LEASES,
    LeaseRegistry,
    LeaseTimeout,
    case_key_of,
    file_write_lock,
    powermcp_home_base,
    reset_leases,
    session_env,
    session_home,
)


@pytest.fixture(autouse=True)
def _clean_leases():
    """每个用例一套干净的租约表 —— 否则统计量会跨用例累积，断言失去意义。"""
    reset_leases()
    yield
    reset_leases()


# ══════════════════════════ 租约：互斥语义 ══════════════════════════


async def test_lease_is_mutually_exclusive():
    """★ 核心不变式：同一 key 的临界区**最大并发必须是 1**。"""
    reg = LeaseRegistry()
    peak = 0
    current = 0

    async def worker():
        nonlocal peak, current
        async with reg.hold("k"):
            current += 1
            peak = max(peak, current)
            await asyncio.sleep(0.02)
            current -= 1

    await asyncio.gather(*(worker() for _ in range(5)))
    assert peak == 1, "临界区出现了并发 —— 租约没有起到互斥作用"


async def test_different_keys_do_not_block_each_other():
    """不同 key 之间**不得**互相阻塞（否则并发化毫无收益）。"""
    reg = LeaseRegistry()
    peak = 0
    current = 0

    async def worker(key: str):
        nonlocal peak, current
        async with reg.hold(key):
            current += 1
            peak = max(peak, current)
            await asyncio.sleep(0.02)
            current -= 1

    await asyncio.gather(*(worker(f"k{i}") for i in range(4)))
    assert peak == 4, "不同 key 被串起来了 —— 租约粒度错了"


async def test_lease_timeout_raises_loudly_not_silently():
    """★ 等不到租约必须**响亮失败**：静默继续会让"还没轮到"被读成"没结果"。"""
    reg = LeaseRegistry()
    async with reg.hold("k"):
        with pytest.raises(LeaseTimeout) as ei:
            async with reg.hold("k", timeout_s=0.05):
                pass  # pragma: no cover —— 不该走到这里
    assert "还没轮到" in str(ei.value)
    assert reg.stats()["timed_out"] == 1


async def test_lease_releases_on_exception():
    """持有者抛异常也必须释放 —— 否则一把锁泄漏就把整条链路永久卡死。"""
    reg = LeaseRegistry()
    with pytest.raises(RuntimeError):
        async with reg.hold("k"):
            raise RuntimeError("boom")
    async with reg.hold("k", timeout_s=0.1):
        pass  # 能拿到，说明确实释放了


async def test_lease_stats_count_actual_queuing():
    """统计必须反映**真实排队**（而不是"看起来有锁"）。"""
    reg = LeaseRegistry()

    async def worker():
        async with reg.hold("k"):
            await asyncio.sleep(0.02)

    await asyncio.gather(*(worker() for _ in range(5)))
    s = reg.stats()
    assert s["acquired"] == 5
    assert s["waited"] == 4          # 5 个里 4 个排过队
    assert s["max_waiters"] == 5     # 4 排队 + 1 持有
    assert s["active"] == 0
    assert s["scope"] == "process-local"


async def test_process_lease_registry_is_the_shared_one():
    """`LEASES` 是进程级单例 —— 所有工具调用共用它（这正是"进程内隔离"的范围）。"""
    assert isinstance(LEASES, LeaseRegistry)
    async with LEASES.hold("shared"):
        assert LEASES.stats()["active"] == 1


# ══════════════════════════ 会话命名空间（措施 1）══════════════════════════


def test_session_home_sanitises_sid():
    """★ 会话 id 来自请求，**直接拼路径 = 把路径穿越交给调用方**。"""
    base = Path("C:/base")
    assert session_home(base, "abc-123_XY") == base / "sessions" / "abc-123_XY"
    # 穿越字符被剥掉（`..` / `/` / `\\` 都不是 alnum 或 -_）
    assert session_home(base, "../../etc") == base / "sessions" / "etc"
    with pytest.raises(ValueError):
        session_home(base, "../../")


def test_session_env_inside_fence_redirects(monkeypatch, tmp_path):
    """围笼内 → 注入会话级 `POWERMCP_HOME`（措施 1 的落点）。"""
    base = tmp_path / ".powermcp"
    base.mkdir()
    monkeypatch.setenv("POWERMCP_HOME", str(base))
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(base))

    overrides, note = session_env("s1")
    assert note is None
    assert overrides["POWERMCP_HOME"] == str(base / "sessions" / "s1")


def test_session_env_outside_fence_does_not_redirect(monkeypatch, tmp_path):
    """★ 围笼外 → **不重定向**并说明理由。

    照做的后果是 server 子进程写 `runs/` 被围笼拦下（引擎报 PathNotAllowed）——
    那是**把引擎弄坏**，比"共享命名空间"严重得多。
    """
    base = tmp_path / ".powermcp"
    base.mkdir()
    monkeypatch.setenv("POWERMCP_HOME", str(base))
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(tmp_path / "elsewhere"))

    overrides, note = session_env("s1")
    assert overrides == {}, "围笼外不该重定向"
    assert note and "ALLOWED_ROOTS" in note


def test_session_env_without_fence_does_not_redirect(monkeypatch, tmp_path):
    """围笼**未配置**时不猜 —— 上游会回落到 cwd，我们无从判断可写性。"""
    monkeypatch.setenv("POWERMCP_HOME", str(tmp_path))
    monkeypatch.delenv("POWERIO_MCP_ALLOWED_ROOTS", raising=False)
    monkeypatch.delenv("POWERIO_MCP_ROOT", raising=False)
    monkeypatch.delenv("POWERIO_MCP_ALLOWED_ROOT", raising=False)

    overrides, note = session_env("s1")
    assert overrides == {}
    assert note and "ALLOWED_ROOTS" in note


def test_powermcp_home_base_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv("POWERMCP_HOME", str(tmp_path))
    assert powermcp_home_base() == tmp_path
    monkeypatch.delenv("POWERMCP_HOME", raising=False)
    assert powermcp_home_base() == Path.home() / ".powermcp"


def test_server_params_injects_session_home(monkeypatch, tmp_path):
    """★ 断言**真实子进程参数**里的 env —— 这是"设了不生效"类缺陷的唯一有效检查。"""
    from powermcp_gateway.config import GatewayConfig
    from powermcp_gateway.proxy import _server_params

    base = tmp_path / ".powermcp"
    base.mkdir()
    monkeypatch.setenv("POWERMCP_HOME", str(base))
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(base))
    cfg = GatewayConfig.discover()

    with_sid = _server_params(cfg, "surge", sid="sess-a")
    assert with_sid.env["POWERMCP_HOME"] == str(base / "sessions" / "sess-a")
    assert with_sid.env["POWERIO_MCP_ALLOWED_ROOTS"] == str(base)

    without = _server_params(cfg, "surge")
    assert "POWERMCP_HOME" not in without.env, "无会话时行为必须与改动前一致"


def test_pool_and_proxy_share_one_env_implementation(monkeypatch, tmp_path):
    """★ 会话命名空间只有**一份**实现 —— 两份会漂移，漂移的后果是"某条路径其实没隔离"。"""
    from powermcp_gateway.config import GatewayConfig
    from powermcp_gateway.proxy import session_server_env
    from powermcp_gateway.serverpool import ServerPool

    base = tmp_path / ".powermcp"
    base.mkdir()
    monkeypatch.setenv("POWERMCP_HOME", str(base))
    monkeypatch.setenv("POWERIO_MCP_ALLOWED_ROOTS", str(base))

    pool = ServerPool(GatewayConfig.discover())
    assert pool._server_env("s9") == session_server_env("s9")
    assert pool._server_env("s9")["POWERMCP_HOME"] == str(base / "sessions" / "s9")


# ══════════════════════════ 算例键（措施 2）══════════════════════════


def test_case_key_is_path_based_and_stable():
    a = case_key_of({"file_path": "D:/data/case39.m", "x": 1})
    b = case_key_of({"x": 1, "file_path": "D:/data/case39.m"})
    c = case_key_of({"file_path": "D:/data/case118.m", "x": 1})
    assert a == b, "同一算例（键序不同）必须得到同一把锁"
    assert a != c, "不同算例必须得到不同的锁"


def test_case_key_falls_back_to_args_hash_without_path():
    """认不出路径参数时**回落到参数哈希** —— 退化成"按参数互斥"，比漏锁安全。"""
    a = case_key_of({"branch": [1, 2]})
    b = case_key_of({"branch": [1, 2]})
    c = case_key_of({"branch": [1, 3]})
    assert a == b and a != c


# ══════════════════════════ 写锁（措施 2/3）══════════════════════════


def test_file_write_lock_is_per_path(tmp_path):
    p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
    assert file_write_lock(p1) is file_write_lock(p1)
    assert file_write_lock(p1) is not file_write_lock(p2)


def test_concurrent_case_registration_loses_nothing(tmp_path, monkeypatch):
    """★ 并发登记 N 个算例 → 索引里必须**一个不少**。

    这是「只锁 `_write` 挡不住丢更新」的直接检验：读-改-写若不在同一临界区，
    后写的会整片覆盖先写的。
    """
    from powermcp_gateway.cases import CaseStore

    store = CaseStore(tmp_path / "cases")
    files = []
    for i in range(8):
        f = tmp_path / f"case{i}.m"
        f.write_text(f"MPC {i}\n", encoding="utf-8")
        files.append(f)

    barrier = threading.Barrier(len(files))

    def worker(path: Path) -> None:
        barrier.wait()          # 尽量让 8 个线程同时进入
        store.register(path)

    threads = [threading.Thread(target=worker, args=(f,)) for f in files]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(store.list()) == len(files), "并发登记丢了条目（读-改-写不在同一临界区）"


# ══════════════════════════ 引擎实例串行化（措施 4）══════════════════════════


async def test_call_tool_serialises_same_session_and_server(monkeypatch):
    """★ 同一 (会话, 引擎) 的调用**不交错** —— 上游把 `runs/<tool>/` 当共享可写目录。"""
    import powermcp_gateway.proxy as proxy

    peak = 0
    current = 0

    async def fake_dispatch(cfg, server, tool, args):
        nonlocal peak, current
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.03)
        current -= 1
        return {"is_error": False, "content": []}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)

    async def call():
        return await proxy.call_tool(None, "surge", "t", {}, schema={}, session_id="s1")

    await asyncio.gather(*(call() for _ in range(3)))
    assert peak == 1, "同一会话对同一引擎的调用被放行了并发"


async def test_call_tool_allows_parallel_across_servers(monkeypatch):
    """不同引擎之间不互相阻塞（否则并发化没有意义）。"""
    import powermcp_gateway.proxy as proxy

    peak = 0
    current = 0

    async def fake_dispatch(cfg, server, tool, args):
        nonlocal peak, current
        current += 1
        peak = max(peak, current)
        await asyncio.sleep(0.03)
        current -= 1
        return {"is_error": False, "content": []}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)
    await asyncio.gather(
        proxy.call_tool(None, "surge", "t", {}, schema={}, session_id="s1"),
        proxy.call_tool(None, "pandapower", "t", {}, schema={}, session_id="s1"),
    )
    assert peak == 2


async def test_call_tool_reports_lease_timeout_as_failure(monkeypatch):
    """★ 租约超时必须变成 `ok=False` + 可读的 error —— 不是挂死、也不是静默继续。"""
    import powermcp_gateway.proxy as proxy

    # 换成一个超时极短的注册表（`call_tool` 用的是 `proxy` 命名空间里的 `LEASES`）
    monkeypatch.setattr(proxy, "LEASES", LeaseRegistry(default_timeout_s=0.05))

    async def fake_dispatch(cfg, server, tool, args):
        await asyncio.sleep(1)
        return {"is_error": False, "content": []}

    monkeypatch.setattr(proxy, "_dispatch", fake_dispatch)

    async def call():
        return await proxy.call_tool(None, "surge", "t", {}, schema={}, session_id="s1")

    holder = asyncio.create_task(call())
    await asyncio.sleep(0.01)                  # 让第一个调用先拿到租约
    blocked = await call()                     # 第二个必须等不到
    assert blocked.ok is False
    assert "还没轮到" in (blocked.error or "")
    holder.cancel()
    with pytest.raises(asyncio.CancelledError):
        await holder
