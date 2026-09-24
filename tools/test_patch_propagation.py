"""决定性实验：客户端进程的 monkey patch 能否影响 MCP server 子进程？

背景：方案 1 提议在验证脚本开头补 `pp.pandapowerNet.deepcopy`。
但 `powermcp run pandapower` 会 spawn 一个**独立 Python 进程**运行 server，
补丁是否随之生效，必须实测而非推断。

本脚本做三组对照：
  A. 不打补丁                       -> 预期失败
  B. 仅在客户端进程打补丁            -> 若仍失败，证明补丁不跨进程
  C. 经 PYTHONPATH + sitecustomize 注入 -> 若成功，说明这是可行的注入点
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from contextlib import AsyncExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT / "PowerMCP"
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"
CASE = ROOT / "examples" / "data" / "case39.json"

os.chdir(ROOT)
os.environ["POWERIO_MCP_ALLOWED_ROOTS"] = os.getcwd()

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SHIM_DIR = ROOT / "tools" / "_shim"
SHIM = SHIM_DIR / "sitecustomize.py"


def write_shim() -> None:
    SHIM_DIR.mkdir(parents=True, exist_ok=True)
    SHIM.write_text(
        '"""由 sitecustomize 机制自动加载，为子进程补上 pandapowerNet.deepcopy。"""\n'
        "import copy\n"
        "try:\n"
        "    import pandapower as _pp\n"
        "    if not hasattr(_pp.pandapowerNet, 'deepcopy'):\n"
        "        _pp.pandapowerNet.deepcopy = lambda self: copy.deepcopy(self)\n"
        "except Exception:\n"
        "    pass\n",
        encoding="utf-8",
    )


async def call_tool(env_extra: dict) -> dict:
    params = StdioServerParameters(
        command=str(PYTHON), args=["-m", "powermcp.cli", "run", "pandapower"],
        cwd=str(REPO), env={**os.environ, "PYTHONIOENCODING": "utf-8", **env_extra},
    )
    async with AsyncExitStack() as stack:
        r, w = await stack.enter_async_context(stdio_client(params))
        s = await stack.enter_async_context(ClientSession(r, w))
        await s.initialize()
        res = await s.call_tool("load_network", {"file_path": str(CASE)})
        for c in res.content:
            if getattr(c, "type", None) == "text":
                pass
        res2 = await s.call_tool("run_contingency_analysis", {"contingency_type": "N-1"})
        for c in res2.content:
            if getattr(c, "type", None) == "text":
                return json.loads(c.text)
    return {}


async def main() -> int:
    # --- A. 不打补丁 ---
    print("=" * 70)
    print("A. 不打补丁（基线）")
    print("=" * 70)
    a = await call_tool({})
    print(f"   status = {a.get('status')}")
    print(f"   message = {str(a.get('message'))[:110]}")
    a_ok = a.get("status") == "success"

    # --- B. 仅在客户端进程打补丁 ---
    print()
    print("=" * 70)
    print("B. 仅在【客户端进程】打补丁（方案 1 的写法）")
    print("=" * 70)
    import copy
    import pandapower as pp
    if not hasattr(pp.pandapowerNet, "deepcopy"):
        pp.pandapowerNet.deepcopy = lambda self: copy.deepcopy(self)
    print(f"   本进程已补丁: hasattr(pandapowerNet,'deepcopy') = "
          f"{hasattr(pp.pandapowerNet, 'deepcopy')}")
    b = await call_tool({})
    print(f"   status = {b.get('status')}")
    print(f"   message = {str(b.get('message'))[:110]}")
    b_ok = b.get("status") == "success"

    # --- C. 经 PYTHONPATH + sitecustomize 注入子进程 ---
    print()
    print("=" * 70)
    print("C. 经 PYTHONPATH + sitecustomize 注入【子进程】")
    print("=" * 70)
    write_shim()
    print(f"   shim 已写入: {SHIM}")
    c = await call_tool({"PYTHONPATH": str(SHIM_DIR)})
    print(f"   status = {c.get('status')}")
    print(f"   message = {str(c.get('message'))[:110]}")
    if c.get("status") == "success":
        rows = c.get("results", [])
        nviol = sum(1 for r in rows if r.get("violations") and
                    (r["violations"]["voltage_violations"] or
                     r["violations"]["loading_violations"]))
        print(f"   扫描 {len(rows)} 个故障，存在越限 {nviol} 个")
    c_ok = c.get("status") == "success"

    print()
    print("=" * 70)
    print("结论")
    print("=" * 70)
    print(f"   A 无补丁              : {'成功' if a_ok else '失败'}")
    print(f"   B 客户端进程补丁      : {'成功' if b_ok else '失败'}"
          f"   -> {'补丁跨进程生效' if b_ok else '补丁【不】跨进程，方案 1 若只写在客户端无效'}")
    print(f"   C PYTHONPATH 注入     : {'成功' if c_ok else '失败'}"
          f"   -> {'该注入方式有效' if c_ok else '该注入方式无效'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
