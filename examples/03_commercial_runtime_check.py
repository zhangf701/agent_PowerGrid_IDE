"""示例 03：商业与高依赖 Server 的预检与优雅探查

覆盖：
  1. PowerWorld —— 软件安装 / SimAuto COM 注册 / esa 桥接包 三级探查；
     三级皆备才尝试 open_case + run_powerflow，否则输出 [SKIP] 且不阻断
  2. HOPE  —— Julia 运行时 + HOPE 仓库/配置探查
  3. GenX  —— Julia 运行时 + GenX.jl checkout 探查
  4. 其余商业 Server（PSSE / PSLF / PowerFactory / PSCAD / LTSpice / PLEXOSDB）状态汇总

设计原则：**本脚本永不因商业组件缺失而失败**。缺失的组件一律给出
         [SKIP] + 具体原因 + 修复指引，最后退出码仍为 0。

工程约定（遵循任务约束）：
  * 启动 MCP 服务前显式设置 POWERIO_MCP_ALLOWED_ROOTS
  * 包版本查询用 importlib.metadata，不用 pip list

用法：
    cd <项目根>
    ./.venv/Scripts/python.exe examples/03_commercial_runtime_check.py
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from contextlib import AsyncExitStack
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO = PROJECT_ROOT / "PowerMCP"
PYTHON_EXE = REPO / ".venv" / "Scripts" / "python.exe"

os.chdir(PROJECT_ROOT)
os.environ["POWERIO_MCP_ALLOWED_ROOTS"] = os.getcwd()   # 约束 #1

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

SKIP = "[SKIP]"
OK = "[ OK ]"
INFO = "[INFO]"
FAIL = "[FAIL]"

# registry.py 声明为 windows_only 的工具
WINDOWS_ONLY = {"powerworld", "psse", "pslf", "powerfactory", "pscad"}


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def pkg(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def first_existing(paths) -> str | None:
    for p in paths:
        if p and Path(p).exists():
            return str(p)
    return None


def com_class_registered(prog_id: str) -> bool:
    """检查 COM ProgID 是否在注册表中注册（Windows）。"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
    except ImportError:
        return False
    for hive, sub in (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Classes"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Classes"),
    ):
        try:
            with winreg.OpenKey(hive, rf"{sub}\{prog_id}"):
                return True
        except OSError:
            continue
    return False


def read_powermcp_config() -> dict:
    """读取 ~/.powermcp/config.toml（若存在）。"""
    try:
        cfg_dir = Path(os.environ.get("POWERMCP_HOME", Path.home() / ".powermcp"))
        path = cfg_dir / "config.toml"
        if not path.exists():
            return {}
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib  # type: ignore
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except Exception:  # noqa: BLE001
        return {}


class MCPServer:
    def __init__(self, tool: str):
        self.tool = tool
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self.params = StdioServerParameters(
            command=str(PYTHON_EXE),
            args=["-m", "powermcp.cli", "run", tool],
            cwd=str(REPO),
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

    async def __aenter__(self) -> "MCPServer":
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(self.params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc) -> None:
        assert self._stack is not None
        await self._stack.aclose()

    async def call(self, tool_name: str, **kwargs) -> dict:
        assert self._session is not None
        result = await self._session.call_tool(tool_name, kwargs)
        for item in result.content:
            if getattr(item, "type", None) == "text":
                try:
                    return json.loads(item.text)
                except json.JSONDecodeError:
                    return {"_raw": item.text}
        return {}


def preflight(tool: str) -> tuple[bool, str]:
    """复用 PowerMCP 自己的 preflight 逻辑判定可用性 —— 不启动任何进程。

    动机：直接 spawn `powermcp run <tool>` 再捕获异常并不稳妥 —— 当子进程
    立即退出时，`mcp.client.stdio` 的 anyio task group 会在退出阶段抛出
    `RuntimeError: Attempted to exit cancel scope in a different task`，
    穿透普通 try/except。而 runner._preflight 在任何进程创建**之前**就已
    判定并抛出可操作错误，直接调用它既准确又无副作用。

    返回 (可用, 说明)。
    """
    try:
        from powermcp.registry import get_tool, install_hint
        from powermcp.runner import probe_installed
    except ImportError as exc:
        return False, f"无法导入 powermcp 判定模块: {exc}"

    t = get_tool(tool)

    # 1) 平台限制
    if t.windows_only and sys.platform != "win32":
        return False, f"{t.display} 仅支持 Windows"

    # 2) MCP SDK
    if not probe_installed("mcp"):
        return False, "MCP SDK 未安装"

    # 3) 探测项（pip 提供的关键依赖）
    #    probe=None 的厂商引擎（PSSE/PSLF/PowerFactory）从配置路径加载，
    #    这里不做导入探测，改查其配置项是否齐备。
    if t.probe is None:
        missing = []
        for ck in t.config_keys:
            if not ck.required:
                continue
            try:
                import powermcp.config as pcfg
                pcfg.get_path(t.name, ck.key)
            except Exception:  # noqa: BLE001
                missing.append(f"{t.name}.{ck.key}")
        if missing:
            return False, f"厂商引擎，未配置: {', '.join(missing)}"
        return True, f"厂商引擎，路径已配置（{len(t.config_keys)} 项）"

    if not probe_installed(t.probe):
        return False, (f"缺少包 '{t.probe.split('.')[0]}'；"
                       f"安装: {install_hint(t.extra)}")

    # 4) 版本下界（与 doctor 一致）
    try:
        import powermcp.doctor as doc
        stale = doc._version_status(t.probe)  # noqa: SLF001
        if stale:
            return False, stale[1]
    except Exception:  # noqa: BLE001
        pass

    return True, "依赖齐备"


async def try_launch(tool: str, timeout: float = 45.0) -> tuple[bool, str]:
    """判定工具是否可用。先用 preflight（无副作用），齐备时才真正拉起。"""
    ok, detail = preflight(tool)
    if not ok:
        return False, detail

    # preflight 已通过 —— 仅对已知可用的开源 server 做一次真实握手
    try:
        async with MCPServer(tool) as srv:
            tools = await srv._session.list_tools()  # noqa: SLF001
            return True, f"{len(tools.tools)} 个工具"
    except BaseException as exc:  # noqa: BLE001 — 含 anyio 的 BaseExceptionGroup
        return False, f"依赖齐备但握手失败: {str(exc)[:100]}"


# --------------------------------------------------------------------------- #
# 1. PowerWorld 三级探查
# --------------------------------------------------------------------------- #
async def check_powerworld() -> dict:
    print("\n" + "=" * 74)
    print("步骤 3.1  PowerWorld —— 三级条件探查")
    print("=" * 74)

    result = {"tool": "powerworld", "launched": False}

    # --- 第一级：软件本体 ---
    print("\n[一级] PowerWorld Simulator 软件")
    exe = first_existing([
        r"C:\Program Files\PowerWorld\Simulator GOS Education 23\pwrworld.exe",
        r"C:\Program Files (x86)\PowerWorld\Simulator 23\pwrworld.exe",
    ])
    if exe:
        print(f"       {OK} 找到: {exe}")
        # 判定版本/许可类型
        edition = "Education" if "Education" in exe or "GOS" in exe else "商业版"
        print(f"       {INFO} 许可类型推断: {edition}")
        result["exe"] = exe
        result["edition"] = edition
    else:
        print(f"       {FAIL} 未在标准路径找到 PowerWorld Simulator")
        result["exe"] = None

    # --- 第二级：SimAuto COM 组件 ---
    print("\n[二级] SimAuto COM 组件注册")
    saw_registered = com_class_registered("PowerWorld.SimulatorAuto")
    assoc = [p for p in ("PowerWorld.pwbfile", "PowerWorld.pwpfile")
             if com_class_registered(p)]
    if saw_registered:
        print(f"       {OK} PowerWorld.SimulatorAuto 已注册")
    else:
        print(f"       {FAIL} PowerWorld.SimulatorAuto 未注册")
        print(f"       {INFO} 仅存在文件关联 ProgID: {assoc or '（无）'}")
        print(f"       {INFO} 说明: SimAuto（自动化接口）是 esa 驱动的对象；")
        print(f"              Education/GOS 版通常不注册该类，故无法自动化。")
    result["simauto"] = saw_registered

    # --- 第三级：esa 桥接包 ---
    print("\n[三级] esa (Easy SimAuto) 桥接包")
    esa_v = pkg("esa")
    if esa_v:
        print(f"       {OK} esa {esa_v}")
    else:
        print(f"       {FAIL} esa 未安装")
        print(f"       {INFO} 安装: pip install powermcp[powerworld]")
    result["esa"] = esa_v

    # --- 案例文件 ---
    print("\n[案例] 仓库内 PWB 算例")
    pwb = REPO / "PowerWorld" / "IEEE 39 bus.pwb"
    print(f"       {OK if pwb.exists() else FAIL} {pwb.name}"
          f"{f'  ({pwb.stat().st_size:,} bytes)' if pwb.exists() else '  不存在'}")
    result["case"] = str(pwb) if pwb.exists() else None

    # --- 实操：仅在必备条件齐备时尝试 ---
    print("\n[实操] open_case + run_powerflow")
    if not (result["exe"] and result["simauto"] and result["esa"]):
        missing = [n for n, ok in
                   (("PowerWorld 软件", result["exe"]),
                    ("SimAuto COM 注册", result["simauto"]),
                    ("esa 包", result["esa"])) if not ok]
        print(f"       {SKIP} PowerWorld COM/License unavailable")
        print(f"              缺失项: {', '.join(missing)}")
        print(f"       {INFO} 该跳过不阻断脚本；其余检查继续。")
        return result

    # 条件齐备（本环境到不了这里，但保留完整路径以保证脚本通用）
    try:
        async with MCPServer("powerworld") as pw:
            opened = await pw.call("open_case", file_path=result["case"])
            print(f"       open_case: {opened.get('status')} {opened.get('message', '')}")
            if opened.get("status") != "success":
                print(f"       {SKIP} PowerWorld COM/License unavailable")
                return result
            pf = await pw.call("run_powerflow")
            print(f"       run_powerflow: {pf.get('status')}")
            res = pf.get("results") or pf.get("bus_results") or {}
            vm = res.get("bus_results", {}).get("vm_pu") or {}
            if vm:
                items = sorted((float(v), k) for k, v in vm.items())
                print(f"       [数值] vm_pu 最低 bus {items[0][1]} = {items[0][0]:.4f}")
                print(f"       [数值] vm_pu 最高 bus {items[-1][1]} = {items[-1][0]:.4f}")
            result["launched"] = True
    except Exception as exc:  # noqa: BLE001
        print(f"       {SKIP} PowerWorld COM/License unavailable")
        print(f"              捕获异常: {type(exc).__name__}: {str(exc)[:140]}")
    return result


# --------------------------------------------------------------------------- #
# 2. HOPE / Julia
# --------------------------------------------------------------------------- #
async def check_hope() -> dict:
    print("\n" + "=" * 74)
    print("步骤 3.2  HOPE —— Julia 运行时与仓库探查")
    print("=" * 74)
    cfg = read_powermcp_config()
    hope_cfg = cfg.get("hope", {})

    julia = shutil.which("julia")
    cfg_julia = hope_cfg.get("julia_bin")
    repo_root = hope_cfg.get("repo_root")

    print(f"     Julia 可执行文件（PATH）: {julia or '未找到'}")
    print(f"     配置 hope.julia_bin      : {cfg_julia or '未设置'}")
    print(f"     配置 hope.repo_root      : {repo_root or '未设置'}")
    print(f"     包 PyYAML                : {pkg('PyYAML') or '未安装'}")
    print(f"     包配置目录               : "
          f"{Path(os.environ.get('POWERMCP_HOME', Path.home() / '.powermcp'))}")

    has_julia = bool(julia or (cfg_julia and Path(cfg_julia).exists()))
    has_repo = bool(repo_root and Path(repo_root).exists())

    if not has_julia:
        print(f"\n     {SKIP} Julia runtime missing for HOPE")
        print(f"            修复: 安装 Julia 并加入 PATH，或")
        print(f"                  powermcp config set hope.julia_bin <julia.exe 路径>")
        if not has_repo:
            print(f"            另需: powermcp config set hope.repo_root <HOPE 仓库路径>")
        print(f"     {INFO} 注意: HOPE 的 Python 包（PyYAML）在本 venv 中已装，")
        print(f"            但 HOPE 真正求解需调用 Julia 侧求解器，故仍不可用。")
        return {"tool": "hope", "ok": False, "reason": "julia missing"}

    print(f"\n     {OK} Julia 运行时可用")
    if not has_repo:
        print(f"     {SKIP} HOPE repo_root 未配置")
        return {"tool": "hope", "ok": False, "reason": "repo_root missing"}

    ok, detail = await try_launch("hope")
    print(f"     {'启动成功: ' + detail if ok else '启动失败: ' + detail}")
    return {"tool": "hope", "ok": ok, "reason": detail}


# --------------------------------------------------------------------------- #
# 3. GenX / Julia
# --------------------------------------------------------------------------- #
async def check_genx() -> dict:
    print("\n" + "=" * 74)
    print("步骤 3.3  GenX —— Julia 与 GenX.jl checkout 探查")
    print("=" * 74)
    cfg = read_powermcp_config()
    genx_cfg = cfg.get("genx", {})
    env_dir = os.environ.get("GENX_DIR")

    repo_root = genx_cfg.get("repo_root") or env_dir
    julia = shutil.which("julia")
    print(f"     配置 genx.repo_root : {genx_cfg.get('repo_root') or '未设置'}")
    print(f"     环境变量 GENX_DIR   : {env_dir or '未设置'}")
    print(f"     Julia（PATH）       : {julia or '未找到'}")
    print(f"     包 matplotlib/pandas: {pkg('matplotlib')} / {pkg('pandas')}  (核心传递带入)")

    if not repo_root:
        print(f"\n     {SKIP} GenX.jl checkout 未配置")
        print(f"            修复: powermcp config set genx.repo_root <GenX.jl 路径>")
        return {"tool": "genx", "ok": False, "reason": "repo_root missing"}
    if not Path(repo_root).exists():
        print(f"\n     {SKIP} 配置的 genx.repo_root 不存在: {repo_root}")
        return {"tool": "genx", "ok": False, "reason": "repo_root 不存在"}
    if not julia:
        print(f"\n     {SKIP} Julia runtime missing for GenX")
        return {"tool": "genx", "ok": False, "reason": "julia missing"}

    ok, detail = await try_launch("genx")
    print(f"\n     {'启动成功: ' + detail if ok else '启动失败: ' + detail}")
    return {"tool": "genx", "ok": ok, "reason": detail}


# --------------------------------------------------------------------------- #
# 4. 其余商业 Server 汇总
# --------------------------------------------------------------------------- #
async def check_others() -> list[dict]:
    print("\n" + "=" * 74)
    print("步骤 3.4  其余商业 / 高依赖 Server 状态汇总")
    print("=" * 74)
    cfg = read_powermcp_config()

    # 各工具的：pip 包 / 本机软件路径 / 配置项
    targets = [
        ("psse", "psspy", [r"C:\Program Files\PTI"], ("psse.python_lib", "psse.bin")),
        ("pslf", "PSLF_PYTHON", [r"C:\Program Files\GE PSLF"], ("pslf.python_lib",)),
        ("powerfactory", "powerfactory", [r"C:\Program Files\DIgSILENT"], ("powerfactory.python_path",)),
        ("pscad", "mhi.pscad", [r"C:\Program Files (x86)\PSCAD", r"C:\Program Files\PSCAD"], ()),
        ("ltspice", "PyLTSpice", [r"C:\Program Files\ADI\LTspice", r"C:\Program Files\LTC"], ("ltspice.exe",)),
        ("plexosdb", "plexosdb_mcp", [], ()),
        # PowerWorld 软件本体确实存在（见步骤 3.1），此处如实列出；
        # 其不可用的原因是 SimAuto COM 未注册 + esa 包缺失，而非软件缺失。
        ("powerworld", "esa",
         [r"C:\Program Files\PowerWorld", r"C:\Program Files (x86)\PowerWorld"], ()),
    ]

    rows = []
    print(f"\n     {'tool':<15}{'pip':<22}{'software':<11}{'status'}")
    print("     " + "-" * 68)
    for tool, module, paths, cfg_keys in targets:
        dist = {"psspy": "psspy", "PSLF_PYTHON": "PSLF_PYTHON",
                "powerfactory": "powerfactory", "mhi.pscad": "mhi-pscad",
                "PyLTSpice": "PyLTSpice", "plexosdb_mcp": "plexosdb-mcp",
                "esa": "esa"}.get(module, module)
        pv = pkg(dist)
        sw = first_existing(paths) if paths else None
        tool_cfg = cfg.get(tool, {})
        cfg_set = [k for k in cfg_keys if tool_cfg.get(k.split(".")[-1])]

        ok, detail = await try_launch(tool, timeout=40.0)
        rows.append({"tool": tool, "pip": pv, "sw": sw, "cfg": cfg_set,
                     "ok": ok, "detail": detail})
        print(f"     {tool:<15}{(pv if pv else '(未装)'):<22}"
              f"{('有' if sw else '-'):<11}{'可用' if ok else '不可用'}")

    # 逐项给出不可用的具体原因与修复命令 —— 表格放不下的信息放这里
    print("\n     不可用原因与修复:")
    for r in rows:
        if r["ok"]:
            continue
        print(f"       {r['tool']:<15}{r['detail']}")
    return rows


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
async def main() -> int:
    print("=" * 74)
    print("示例 03：商业与高依赖 Server 预检与优雅探查")
    print("=" * 74)
    print(f"  Python       {sys.version.split()[0]}   ({sys.executable})")
    print(f"  平台         {sys.platform}")
    for p in ("powermcp", "powerio", "mcp", "pandapower", "pypsa", "surge-py"):
        print(f"  {p:<12} {pkg(p) or '(未安装)'}")

    pw = await check_powerworld()
    hope = await check_hope()
    genx = await check_genx()
    others = await check_others()

    # --- 总结 ---
    print("\n" + "=" * 74)
    print("总结")
    print("=" * 74)
    print(f"  {'PowerWorld':<14}{'可用' if pw['launched'] else '不可用（已优雅跳过）'}")
    for name, r in (("HOPE", hope), ("GenX", genx)):
        verdict = "可用" if r["ok"] else f"不可用 — {r['reason']}"
        print(f"  {name:<14}{verdict}")
    avail = [r["tool"] for r in others if r["ok"]]
    unavail = [r["tool"] for r in others if not r["ok"]]
    print(f"  其余商业工具   可用: {avail or '（无）'}")
    print(f"                 不可用: {unavail}")

    print(f"\n  本节所有不可用项均以 {SKIP} 报告，未中断脚本。")
    print("  开源部分（示例 01 / 02）不受影响。")

    print("\n" + "=" * 74)
    print("[SUCCESS] 示例 03 完成（商业组件缺失为预期结果，非失败）")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
