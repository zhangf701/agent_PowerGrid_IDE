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

    async with asyncio.timeout(timeout):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [ToolRecord.from_sdk(server, t) for t in result.tools]


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
            return server, None, f"{type(exc).__name__}: {exc}"[:200]

    results = await asyncio.gather(*(one(s) for s in names))

    tools: list[ToolRecord] = []
    failures: list[ServerFailure] = []
    for server, recs, err in results:
        if recs is None:
            failures.append(ServerFailure(server=server, error=err))
        else:
            tools.extend(recs)

    return ToolInventory(tools=tuple(tools), failures=tuple(failures))
