"""MCP stdio 客户端与工具清单。

启动方式复用 tools/runtime_tool_census.py 已验证的写法：
    <venv python> -m powermcp.cli run <server>   （cwd = PowerMCP 仓库根）
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Iterable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import GatewayConfig


@dataclass(frozen=True)
class ToolRecord:
    server: str
    name: str
    description: str | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None

    @classmethod
    def from_sdk(cls, server: str, tool: Any) -> "ToolRecord":
        # ⚠️ SDK 用 snake_case：input_schema / output_schema
        return cls(
            server=server,
            name=tool.name,
            description=getattr(tool, "description", None),
            input_schema=dict(getattr(tool, "input_schema", None) or {}),
            output_schema=getattr(tool, "output_schema", None),
        )


@dataclass(frozen=True)
class ServerFailure:
    server: str
    error: str


@dataclass(frozen=True)
class ToolInventory:
    tools: tuple[ToolRecord, ...]
    failures: tuple[ServerFailure, ...]

    def names(self, server: str) -> tuple[str, ...]:
        return tuple(sorted(t.name for t in self.tools if t.server == server))

    def by_name(self, name: str) -> tuple[ToolRecord, ...]:
        return tuple(sorted((t for t in self.tools if t.name == name), key=lambda t: t.server))

    def servers(self) -> tuple[str, ...]:
        return tuple(sorted({t.server for t in self.tools}))


async def fetch_server_tools(
    cfg: GatewayConfig, server: str, timeout_s: float | None = None
) -> list[ToolRecord]:
    """拉起单个 server 并取回其工具清单。失败时抛异常，由 build_inventory 归集。"""
    params = StdioServerParameters(
        command=str(cfg.python),
        args=["-m", "powermcp.cli", "run", server],
        cwd=str(cfg.powermcp_root),
    )
    timeout = timeout_s if timeout_s is not None else cfg.server_timeout_s

    try:
        async with asyncio.timeout(timeout):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return [ToolRecord.from_sdk(server, t) for t in result.tools]
    except Exception as exc:  # noqa: BLE001 —— 见下：超时需补上下文后重抛，其余原样上抛
        if _is_timeout(exc):
            raise _timeout_error(server, timeout) from exc
        raise


def _describe_error(exc: BaseException) -> str:
    """把异常展开为**可执行的叶子原因**。

    anyio 会把子进程的 `LaunchError` 包在 `ExceptionGroup` 里。直接 `str(exc)`
    只能得到 `"unhandled errors in a TaskGroup (1 sub-exception)"` ——
    真正可执行的信息（如 `pip install powermcp[opendss]`）会被吞掉，
    使契约 8 的 detail 变得不可读。

    方案 §4.4 要求 ⚠️/❌ 必须给出**可执行修复路径**，故此处必须递归展开，
    并把空白折叠为单行（detail 会渲染成徽章/卡片，多行不便展示）。
    """
    leaves: list[str] = []

    def walk(e: BaseException) -> None:
        subs = getattr(e, "exceptions", None)  # ExceptionGroup / BaseExceptionGroup
        if subs:
            for sub in subs:
                walk(sub)
            return
        leaves.append(f"{type(e).__name__}: {e}")

    walk(exc)

    seen: list[str] = []
    for leaf in leaves:
        flat = " ".join(leaf.split())  # 折叠换行与连续空白
        if flat not in seen:
            seen.append(flat)
    return " | ".join(seen)[:400]


def _is_timeout(exc: BaseException) -> bool:
    """判断异常（含 ExceptionGroup 嵌套）是否由超时引起。"""
    if isinstance(exc, TimeoutError):
        return True
    for sub in getattr(exc, "exceptions", ()) or ():
        if _is_timeout(sub):
            return True
    return False


def _timeout_error(server: str, timeout: float) -> TimeoutError:
    """构造**带上下文**的超时异常。

    `asyncio.timeout` 原生抛出的 `TimeoutError` **消息为空** —— 契约 8 的 detail
    会退化成 `"TimeoutError:"`，既不说明是哪个 server、等了多久，也不说明卡在哪一步，
    同样违反方案 §4.4「⚠️/❌ 必须给出可执行修复路径」。
    """
    return TimeoutError(
        f"{server} 在 {timeout:g}s 内未完成 MCP 握手（initialize / list_tools 无响应）"
        f" —— 进程可能已启动但不响应，需单独排查该 server 的 stdio 管道"
    )


async def build_inventory(
    cfg: GatewayConfig,
    servers: Iterable[str],
    timeout_s: float | None = None,
) -> ToolInventory:
    """并发拉起多个 server；单个失败不影响其余，缺口记入 failures。"""
    names = list(servers)

    async def one(server: str) -> tuple[str, list[ToolRecord] | None, str]:
        try:
            return server, await fetch_server_tools(cfg, server, timeout_s), ""
        except Exception as exc:  # noqa: BLE001 —— 单 server 失败不应拖垮整体
            return server, None, _describe_error(exc)

    results = await asyncio.gather(*(one(s) for s in names))

    tools: list[ToolRecord] = []
    failures: list[ServerFailure] = []
    for server, recs, err in results:
        if recs is None:
            failures.append(ServerFailure(server=server, error=err))
        else:
            tools.extend(recs)

    return ToolInventory(tools=tuple(tools), failures=tuple(failures))
