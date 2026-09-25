"""MCP stdio 客户端与工具清单。

启动方式复用 tools/runtime_tool_census.py 已验证的写法：
    <venv python> -m powermcp.cli run <server>   （cwd = PowerMCP 仓库根）
"""

from __future__ import annotations

import asyncio
import importlib.util
from dataclasses import dataclass
from typing import Any, Iterable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import GatewayConfig

# 依赖缺失类错误的关键词 —— 命中才给安装提示。
# 超时/崩溃时提示 `pip install` 是没有帮助的（方案 §4.4 要的是"可执行"路径）。
_DEP_PATTERNS = (
    "not installed",
    "install it with",
    "no module named",
    "importerror",
    "modulenotfounderror",
)


def _looks_dependency_related(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in _DEP_PATTERNS)


def _probe_importable(probe: str) -> bool:
    """该 linchpin 依赖在当前解释器里是否可导入。网关与 server 共用同一个 venv。"""
    try:
        return importlib.util.find_spec(probe) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def install_hint_for(server: str) -> tuple[str | None, str | None]:
    """从 `powermcp.registry` 取该 server 的可执行安装提示与 linchpin 依赖。

    返回 `(hint, probe)`；registry 不可用或不认识该 server 时返回 `(None, None)`。
    **不解析错误文本** —— 提示来源是 registry 的 `Tool.extra` + `install_hint()`，
    错误文本只用于**判断是否属于依赖缺失**（见 `_looks_dependency_related`）。
    """
    try:
        from powermcp import registry
    except Exception:  # noqa: BLE001 —— 网关可在没有 powermcp 的环境下被导入
        return None, None

    try:
        tool = registry.get_tool(server)
    except Exception:  # noqa: BLE001 —— 未知 server
        return None, None

    try:
        hint = registry.install_hint(tool.extra)
    except Exception:  # noqa: BLE001
        hint = None
    return hint, getattr(tool, "probe", None)


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
    hint: str | None = None           # 可执行安装提示（来自 registry；仅依赖缺失类失败）
    probe_missing: str | None = None  # 缺失的 linchpin 依赖名


@dataclass(frozen=True)
class ToolInventory:
    tools: tuple[ToolRecord, ...]
    failures: tuple[ServerFailure, ...]
    requested: tuple[str, ...] = ()   # 本次请求的 server 全集（含拉起失败的）

    def names(self, server: str) -> tuple[str, ...]:
        return tuple(sorted(t.name for t in self.tools if t.server == server))

    def by_name(self, name: str) -> tuple[ToolRecord, ...]:
        return tuple(sorted((t for t in self.tools if t.name == name), key=lambda t: t.server))

    def servers(self) -> tuple[str, ...]:
        """**成功**返回工具清单的 server。"""
        return tuple(sorted({t.server for t in self.tools}))

    def all_servers(self) -> tuple[str, ...]:
        """本次请求的全部 server，**含拉起失败的**。

        ★ 求值器一律迭代本方法，不要用 `servers()` ——
        否则失败的 server 会从视野里消失，变成**静默跳过**。
        """
        if self.requested:
            return tuple(sorted(self.requested))
        return tuple(sorted({t.server for t in self.tools} | {f.server for f in self.failures}))


async def fetch_server_tools(
    cfg: GatewayConfig, server: str, timeout_s: float | None = None,
    *, sid: str | None = None, pool: Any | None = None,
) -> list[ToolRecord]:
    """拉起单个 server 并取回其工具清单。失败时抛异常，由 build_inventory 归集。

    ★ 传入 `sid` + `pool` 时**复用会话级持久连接**（子项目 4）—— 列工具与
      执行走同一个 server 进程，每轮对话不必重新挂载（T6-M5 的 inventory 侧）。
    """
    if pool is not None and sid is not None:
        try:
            result = await pool.list_tools(sid, server, timeout_s=timeout_s)
            return [ToolRecord.from_sdk(server, t) for t in result.tools]
        except Exception as exc:  # noqa: BLE001 —— 与 legacy 路径同一超时补全口径
            if _is_timeout(exc):
                raise _timeout_error(server, timeout_s if timeout_s is not None
                                     else cfg.server_timeout_s) from exc
            raise

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
    *, sid: str | None = None, pool: Any | None = None,
) -> ToolInventory:
    """并发拉起多个 server；单个失败不影响其余，缺口记入 failures。

    失败时**必须保留可执行信息**：摊平 ExceptionGroup 取真实原因，
    并在**确属依赖缺失**时从 registry 附上安装提示（方案 §4.4 硬要求）。
    传入 `sid` + `pool` 时复用会话级持久连接（见 fetch_server_tools）。
    """
    names = list(servers)

    async def one(server: str) -> tuple[str, list[ToolRecord] | None, ServerFailure | None]:
        try:
            if pool is not None and sid is not None:
                recs = await fetch_server_tools(cfg, server, timeout_s, sid=sid, pool=pool)
            else:
                # 旧路径保持**原签名**调用 —— 测试里 monkeypatch 的假实现签名不变
                recs = await fetch_server_tools(cfg, server, timeout_s)
            return server, recs, None
        except Exception as exc:  # noqa: BLE001 —— 单 server 失败不应拖垮整体
            error = _describe_error(exc)
            hint, probe = install_hint_for(server)

            # 只在"看起来与依赖缺失有关"时才给安装提示，避免误导
            # （超时、崩溃时提示 `pip install` 帮不上忙）
            probe_missing = probe if (probe is not None and not _probe_importable(probe)) else None
            dependency_related = _looks_dependency_related(error) or probe_missing is not None

            return server, None, ServerFailure(
                server=server,
                error=error,
                hint=hint if dependency_related else None,
                probe_missing=probe_missing,
            )

    results = await asyncio.gather(*(one(s) for s in names))

    tools: list[ToolRecord] = []
    failures: list[ServerFailure] = []
    for server, recs, failure in results:
        if failure is not None:
            failures.append(failure)
        else:
            tools.extend(recs or [])

    return ToolInventory(
        tools=tuple(tools),
        failures=tuple(failures),
        requested=tuple(sorted(names)),
    )
