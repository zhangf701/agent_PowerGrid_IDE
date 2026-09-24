"""导出 PowerMCP server 的真实工具 schema（参数名/类型/必填/默认值）。

用途：编写示例脚本前的侦察。避免凭猜测写参数名。

用法：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe ../tools/dump_tool_schemas.py [tool ...]
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent / "PowerMCP"
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def dump(tool: str, timeout: float = 120.0):
    params = StdioServerParameters(
        command=str(PYTHON),
        args=["-m", "powermcp.cli", "run", tool],
        cwd=str(REPO),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    async with asyncio.timeout(timeout):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return result.tools


def render(tools, *, full: bool = False) -> str:
    out = []
    for t in tools:
        out.append(f"\n### {t.name}")
        if t.description and full:
            out.append("    # " + t.description.strip().replace("\n", "\n    # ")[:800])
        elif t.description:
            out.append("    # " + t.description.strip().split("\n")[0][:150])
        schema = t.input_schema or {}
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        if not props:
            out.append("    (无参数)")
        for pname, pspec in props.items():
            ptype = pspec.get("type", "?")
            if ptype == "array":
                ptype = f"array[{pspec.get('items', {}).get('type', '?')}]"
            if pname in required:
                default = "<必填>"
            elif "default" in pspec:
                default = repr(pspec["default"])
            else:
                default = "<可选>"
            desc = (pspec.get("description") or "").strip().split("\n")[0][:70]
            out.append(f"    {pname}: {ptype} = {default}   {desc}")
        # 返回结构（用于写断言）
        outs = (t.output_schema or {}).get("properties", {}).get("result", {})
        if full and outs:
            out.append(f"    [返回] {json.dumps(outs, ensure_ascii=False)[:900]}")
    return "\n".join(out)


async def main() -> int:
    args = sys.argv[1:]
    full = "--full" in args
    args = [a for a in args if not a.startswith("--")]
    for tool in (args or ["pandapower"]):
        try:
            result = await dump(tool)
            print(f"\n{'=' * 78}\n== {tool}  （{len(result)} 个工具）\n{'=' * 78}")
            print(render(result, full=full))
        except Exception as exc:  # noqa: BLE001
            print(f"\n== {tool}: FAIL {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
