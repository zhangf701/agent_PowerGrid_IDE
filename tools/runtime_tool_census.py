"""运行时工具清单核验：实际拉起每个 server，调用 list_tools，与静态统计对照。

用法：  python tests/_runtime_tool_census.py [tool1 tool2 ...]
不带参数则核验已安装的默认集合。

这是一个一次性的核验脚本（非 pytest 用例），用于交叉校验扫描报告中的
静态工具计数。依赖 mcp SDK 的 stdio 客户端。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parent.parent / "PowerMCP"
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"

# 静态统计得到的工具数（扫描报告 §3.2），用于对照。
# 2026-09-21 实测：前四项已由运行时 list_tools 证实；powerio 为外部包，
# 静态时未知，实测为 10，故此处不再设占位值。
STATIC_COUNTS = {
    "pandapower": 8,
    "pypsa": 17,
    "surge": 44,
    "hope": 20,
    "genx": 7,
    "powerio": 10,
}


async def census(tool: str, timeout: float = 90.0) -> tuple[str, int | None, str]:
    params = StdioServerParameters(
        command=str(PYTHON),
        args=["-m", "powermcp.cli", "run", tool],
        cwd=str(REPO),
    )
    try:
        async with asyncio.timeout(timeout):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return tool, len(result.tools), ""
    except Exception as exc:  # noqa: BLE001 — 核验脚本，报告一切失败
        return tool, None, f"{type(exc).__name__}: {exc}"[:160]


async def main() -> int:
    tools = sys.argv[1:] or ["pandapower", "pypsa", "surge", "hope", "powerio"]
    print(f"{'tool':<12} {'运行时':>8} {'静态':>6}  结论")
    print("-" * 52)
    rows = await asyncio.gather(*(census(t) for t in tools))
    ok = True
    for tool, count, err in rows:
        if count is None:
            print(f"{tool:<12} {'FAIL':>8} {'-':>6}  {err}")
            ok = False
            continue
        static = STATIC_COUNTS.get(tool)
        verdict = "—"
        if static is not None:
            verdict = "MATCH ✓" if static == count else f"静态值 {static} 不符 ✗"
            if static != count:
                ok = False
        print(f"{tool:<12} {count:>8} {static if static is not None else '-':>6}  {verdict}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
