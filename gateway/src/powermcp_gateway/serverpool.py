"""会话级持久 MCP server 连接池 —— T6-M5 的根治（子项目 4，2026-09-25）。

## 为什么必须有这一层（张老师首轮真实测试的结论）

`proxy._dispatch` 每次工具调用都**新起 server 子进程、用完即关**。后果：
`load_network` 显示成功后，下一次 `run_power_flow` 是**全新进程**——报
"没有已载入的网络"。有状态工作流（载入 → 分析 → 导出）在旧架构下
**根本不可能完成**。台账原记「慢（T6-M5）」，实测是**功能阻断**。

## 设计

- **一个 `(session_id, server)` 一条持久连接**：由专属 asyncio task 持有
  `stdio_client` + `ClientSession` 的 async 上下文，经队列串行接活。
  ★ 上下文必须在**同一个 task** 里进出（anyio cancel scope 是 task 绑定的，
  跨 task 退出会炸）——这正是不能"直接把 session 存字典里"的原因。
- **懒挂载**：首次用到才起进程；不用不花资源。
- **断裂自愈（重连一次）**：传输层断裂（进程崩溃 / 管道关闭）→ 杀掉旧连接、
  重新挂载并**重跑同一调用一次**。★ 状态因此丢失，必须让调用方知道 ——
  返回值带 `remounted=True`，由上层以 notice 如实告知用户。
- **超时即弃**：一次调用超时后连接处于未知状态（可能仍有调用在跑），
  该连接整体丢弃，下次调用重新挂载 —— 宁可重挂也不复用可疑连接。
- **每会话 LRU 上限**：防长会话把 server 进程数撑爆（默认 6）。
- **连接器可注入**：测试用假连接器（无需真进程），生产走真 stdio。
- **观测面**：`stats()` → `GET /health` 的 `server_pool`。

## 显式不做

- 不做跨进程状态迁移：server 重连后状态就是丢了，**如实上报**而非假装续上。
- 不改 `inventory.fetch_server_tools` 的逐次挂载：列工具是**无状态**操作，
  且它有独立的超时语义；池只管**工具调用**。
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import GatewayConfig

logger = logging.getLogger(__name__)

#: 默认每会话同时挂载的 server 上限（LRU 淘汰最久未用的）
DEFAULT_MAX_PER_SESSION = 6


@dataclass(frozen=True)
class CallResult:
    """一次工具调用的传输层结果（`proxy.call_tool` 再包契约与事件）。"""

    result: dict                 # {"is_error": bool, "content": [...]}
    remounted: bool = False      # True = 用的是「断裂后重连」的连接（此前状态已丢失）


class MountError(RuntimeError):
    """连接挂载失败（initialize 失败 / 进程起不来）。"""


def _is_conn_broken(exc: BaseException) -> bool:
    """判断异常是否为**连接级断裂**（值得重连），而非普通工具失败。

    与 `proxy._is_timeout` 同风格：递归展开 ExceptionGroup，按类型判断。
    覆盖 anyio 的两类传输断裂 + MCP 在 EOF 时的派生形态。
    """
    if isinstance(exc, (asyncio.CancelledError,)):
        return False
    names = {type(exc).__name__}
    if names & {"ClosedResourceError", "BrokenResourceError", "EndOfStream"}:
        return True
    for sub in getattr(exc, "exceptions", ()) or ():
        if _is_conn_broken(sub):
            return True
    return False


class _Conn:
    """一条持久连接：专属 task 持有上下文，队列串行接活。"""

    def __init__(self, key: tuple[str, str], params: StdioServerParameters,
                 connector: Callable[[StdioServerParameters], Any]) -> None:
        self.key = key
        self.params = params
        self._connector = connector
        self._queue: asyncio.Queue = asyncio.Queue()
        self.ready: asyncio.Future = asyncio.get_running_loop().create_future()
        self.broken = False
        self.task = asyncio.create_task(self._run(), name=f"pool-{key[0]}-{key[1]}")

    async def _run(self) -> None:
        """持有连接上下文的一生。上下文的进出都发生在**本 task** 内。"""
        pending: asyncio.Future | None = None
        try:
            async with self._connector(self.params) as session:
                await session.initialize()
                if not self.ready.done():
                    self.ready.set_result(session)
                while True:
                    item = await self._queue.get()
                    if item is None:                       # shutdown 哨兵
                        return
                    fut, tool, args = item
                    pending = fut
                    try:
                        result = await session.call_tool(tool, arguments=args)
                        fut.set_result({
                            "is_error": bool(result.is_error),
                            "content": [c.model_dump() for c in result.content],
                        })
                    except asyncio.CancelledError:
                        raise
                    except BaseException as exc:           # noqa: BLE001
                        fut.set_exception(exc)
                        if _is_conn_broken(exc):
                            self.broken = True
                            raise                          # 退出 → finally 关上下文
                    finally:
                        pending = None
        except asyncio.CancelledError:
            if not self.ready.done():
                self.ready.set_exception(MountError("连接被关闭（池关闭/淘汰）"))
            raise
        except BaseException as exc:                       # noqa: BLE001
            if not self.ready.done():
                self.ready.set_exception(MountError(
                    f"server 连接挂载失败：{type(exc).__name__}: {exc}"[:300]))
            elif pending is not None and not pending.done():
                pending.set_exception(exc)
            if _is_conn_broken(exc):
                self.broken = True
        finally:
            # 队列里尚未处理的调用全部失败（fail-loud，不悬挂）
            while not self._queue.empty():
                item = self._queue.get_nowait()
                if item is not None and not item[0].done():
                    item[0].set_exception(MountError("连接已关闭，调用未执行"))

    async def call(self, tool: str, args: dict, timeout_s: float) -> dict:
        # ★ **首次挂载也要限时** —— server 起不来/握手挂死（opendss 形态）时，
        #   不能让调用无限等 `ready`；挂载与执行共用同一预算。
        if not self.ready.done():
            try:
                await asyncio.wait_for(asyncio.shield(self.ready), timeout_s)
            except TimeoutError:
                raise TimeoutError(
                    f"{self.key[1]} 在 {timeout_s:g}s 内未完成首次挂载（initialize）—— "
                    f"该连接将被丢弃并在下次调用时重新挂载"
                ) from None
        session = self.ready.result()                      # 挂载失败 → MountError
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._queue.put_nowait((fut, tool, args))
        try:
            return await asyncio.wait_for(fut, timeout_s)
        except TimeoutError:
            raise TimeoutError(
                f"{self.key[1]} 在 {timeout_s:g}s 内未完成工具调用 `{tool}` —— "
                f"该连接将被丢弃并在下次调用时重新挂载"
            ) from None

    async def aclose(self) -> None:
        if self.task.done():
            return
        self._queue.put_nowait(None)
        try:
            await asyncio.wait_for(asyncio.shield(self.task), timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            self.task.cancel()
            try:
                await self.task
            except BaseException:                          # noqa: BLE001
                pass


class ServerPool:
    """`(session_id, server)` → 持久连接。见模块 docstring 的设计说明。"""

    def __init__(self, cfg: GatewayConfig, *,
                 connector: Callable[[StdioServerParameters],
                                     Any] | None = None,
                 max_per_session: int = DEFAULT_MAX_PER_SESSION) -> None:
        self._cfg = cfg
        self._connector = connector or self._real_connector
        self._max_per_session = max(1, int(max_per_session))
        self._conns: dict[tuple[str, str], _Conn] = {}
        # sid → 该会话的 key（插入序 = 最近使用序末尾），用于 LRU 淘汰与会话清理
        self._by_sid: dict[str, OrderedDict[tuple[str, str], None]] = {}
        self.calls = 0
        self.remounts = 0
        self.evictions = 0

    @staticmethod
    @asynccontextmanager
    async def _real_connector(params: StdioServerParameters):
        """生产连接器：**包两层**（stdio 传输 + ClientSession），yield 出可用的会话。

        ★ `stdio_client` yield 的是 `(read, write)` 流，不是会话 —— 必须再进
          `ClientSession`；两层都必须由**同一个 task** 进出（anyio cancel scope
          是 task 绑定的）。
        """
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                yield session

    # -- 挂载 ---------------------------------------------------------------

    def _conn_for(self, sid: str, server: str) -> _Conn:
        key = (sid, server)
        conn = self._conns.get(key)
        if conn is None:
            params = StdioServerParameters(
                command=str(self._cfg.python),
                args=["-m", "powermcp.cli", "run", server],
                cwd=str(self._cfg.powermcp_root),
                env=self._server_env(),
            )
            conn = _Conn(key, params, self._connector)
            self._conns[key] = conn
            self._by_sid.setdefault(sid, OrderedDict())[key] = None
            self._evict_lru(sid)
        else:
            order = self._by_sid.get(sid)
            if order is not None and key in order:
                order.move_to_end(key)
        return conn

    def _server_env(self) -> dict[str, str] | None:
        """与 `proxy._server_params` 同源的显式 env（防两处口径漂移）。"""
        from .config import server_env
        return server_env()

    def _evict_lru(self, sid: str) -> None:
        order = self._by_sid.get(sid)
        if order is None or len(order) <= self._max_per_session:
            return
        while len(order) > self._max_per_session:
            key, _ = order.popitem(last=False)             # 最久未用
            conn = self._conns.pop(key, None)
            if conn is not None:
                self.evictions += 1
                logger.info("连接池 LRU 淘汰：%s.%s（每会话上限 %d）",
                            key[0], key[1], self._max_per_session)
                asyncio.create_task(conn.aclose())

    async def _wait_mounted(self, conn: _Conn) -> None:
        await asyncio.shield(conn.ready)

    # -- 调用 ---------------------------------------------------------------

    async def call(self, sid: str, server: str, tool: str, args: dict,
                   *, timeout_s: float | None = None) -> CallResult:
        """经持久连接执行一次工具调用；连接断裂时**重连一次**并重跑。"""
        if timeout_s is None:
            timeout_s = self._cfg.server_timeout_s
        self.calls += 1
        try:
            conn = self._conn_for(sid, server)
            result = await conn.call(tool, args, timeout_s)
            return CallResult(result=result)
        except asyncio.CancelledError:
            raise                                          # 取消信号绝不吞、绝不重试
        except BaseException as first:                     # noqa: BLE001
            if not _is_conn_broken(first) and not isinstance(first, (TimeoutError, MountError)):
                raise            # 普通工具失败（如 is_error / 引擎报错）不重连 —— 那会掩盖真问题
            # 连接级断裂 / 超时 / 挂载失败：丢弃旧连接，重连一次并重跑同一调用。
            # ★ 状态随旧进程丢失 —— remounted=True 让上层如实告知用户。
            await self.drop(sid, server)
            self.remounts += 1
            logger.warning(
                "连接断裂（%s.%s），已重连并重跑 `%s` —— 此前装载的状态已丢失",
                sid, server, tool,
            )
            conn = self._conn_for(sid, server)
            result = await conn.call(tool, args, timeout_s)
            return CallResult(result=result, remounted=True)

    # -- 生命周期 -----------------------------------------------------------

    async def drop(self, sid: str, server: str) -> None:
        key = (sid, server)
        conn = self._conns.pop(key, None)
        order = self._by_sid.get(sid)
        if order is not None:
            order.pop(key, None)
        if conn is not None:
            await conn.aclose()

    async def drop_session(self, sid: str) -> None:
        """会话结束：关闭该会话的全部连接。"""
        order = self._by_sid.pop(sid, None)
        if not order:
            return
        for key in list(order):
            conn = self._conns.pop(key, None)
            if conn is not None:
                await conn.aclose()

    async def aclose(self) -> None:
        """池整体关闭（lifespan shutdown）。"""
        for key in list(self._conns):
            conn = self._conns.pop(key, None)
            if conn is not None:
                await conn.aclose()
        self._by_sid.clear()

    def stats(self) -> dict:
        return {
            "mounted": len(self._conns),
            "calls": self.calls,
            "remounts": self.remounts,
            "evictions": self.evictions,
            "max_per_session": self._max_per_session,
        }
