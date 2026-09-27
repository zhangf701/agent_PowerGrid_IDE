"""示例 04：AC / DC 最优潮流（OPF）—— pandapower 侧实现

⚠️ **本脚本的定位与 01/02/03 不同，必须如实声明**：

  01/02/03 全部经由 **MCP 工具调用**（`powermcp run <server>` + stdio）。
  本脚本的 OPF 部分**不是 MCP 调用**，而是在 Skill 侧直接调用 pandapower 的
  `runopp` / `rundcopp`。这是**有意为之的破例**，原因：

    * PowerMCP 的 pandapower server **没有 OPF 工具**（其 8 个工具中无 OPF）；
    * PowerMCP 的 PyPSA server 虽有 `optimize_network`，但对经 PowerIO IR
      导入的算例返回 `infeasible`，成因经 13 项假设排查后仍未定位
      （见 docs/journal/2026-09-21-mcp-examples-verification.md §3.5）；
    * pandapower 自带的 `runopp` / `rundcopp` **实测可用**，且与已验证的
      `runpp` 同引擎、同网络对象、同索引约定 —— 没有新的数据契约或失败模式。

  因此本脚本采取「MCP 取基准 + 本地做 OPF」的混合模式，并用步骤 4.2 的
  一致性闸门确保本地网络与 MCP 载入的网络**确实是同一个**。

流程：
  4.1  MCP pandapower 载入 + 基态潮流      —— 建立基准数值
  4.2  本地从同一 JSON 重建 + 校验         —— 🔒 闸门：必须与 4.1 吻合
  4.3  AC OPF（runopp）                    —— 目标值 / 机组出力 / 电压 / 负载率
  4.4  DC OPF（rundcopp）                  —— 与 AC 对比
  4.5  三方对比 + 守恒律校验

工程约定（遵循任务约束）：
  * 启动 MCP 服务前显式设置 POWERIO_MCP_ALLOWED_ROOTS
  * 包版本查询用 importlib.metadata，不用 pip list
  * 先基态潮流收敛，再做优化
  * 输出具体数值（机组编号 + p_mw、母线编号 + vm_pu、支路编号 + loading_percent）

用法：
    cd <项目根>
    ./.venv/Scripts/python.exe examples/04_pandapower_opf_demo.py
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import sys
import warnings
from contextlib import AsyncExitStack
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO = PROJECT_ROOT / "PowerMCP"
PYTHON_EXE = REPO / ".venv" / "Scripts" / "python.exe"
DATA_DIR = PROJECT_ROOT / "examples" / "data"

os.chdir(PROJECT_ROOT)
os.environ["POWERIO_MCP_ALLOWED_ROOTS"] = os.getcwd()   # 约束 #1

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

IEEE39_JSON = DATA_DIR / "case39.json"
TOL_VM = 1e-6          # 闸门阈值：两侧电压应一致到此量级（pu）
TOL_MVA = 1e-6


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


def run_quiet(func, *args, **kwargs) -> str:
    """执行并捕获 pandapower 写到 stdout/stderr 的提示，返回其文本。

    动机：pandapower 会把「gen vm_pu > bus max_vm_pu for gens [5]」这类
    自动修正提示直接打印出来。这些提示必须被**捕获并如实报告**，而不是
    任其混入输出或被静默吞掉。
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        result = func(*args, **kwargs)
    return buf.getvalue().strip(), result


# --------------------------------------------------------------------------- #
# 步骤 4.1 —— MCP 基准
# --------------------------------------------------------------------------- #
async def step1_mcp_baseline() -> dict:
    print("\n" + "=" * 74)
    print("步骤 4.1  基态潮流（MCP · powermcp_pandapower）—— 建立基准")
    print("=" * 74)
    async with MCPServer("pandapower") as srv:
        loaded = await srv.call("load_network", file_path=str(IEEE39_JSON))
        assert loaded.get("status") == "success", f"load_network 失败: {loaded}"
        info = loaded.get("network_info", {})
        print(f"     [MCP] 载入 {info.get('buses')} 母线 / {info.get('lines')} 线路 "
              f"/ {info.get('trafos')} 变压器")

        pf = await srv.call("run_power_flow", algorithm="nr")
        assert pf.get("status") == "success", f"run_power_flow 失败: {pf}"
        res = pf["results"]
        assert res.get("converged") is True, "MCP 基态潮流未收敛"

    vm = {int(k): float(v) for k, v in res["bus_results"]["vm_pu"].items()}
    lp = {int(k): float(v) for k, v in res["line_results"]["loading_percent"].items()}
    lo, hi = min(vm.items(), key=lambda kv: kv[1]), max(vm.items(), key=lambda kv: kv[1])
    lmax = max(lp.items(), key=lambda kv: kv[1])
    print(f"     [MCP] 收敛，母线 {lo[0]} vm_pu={lo[1]:.6f} (最低) / "
          f"母线 {hi[0]} vm_pu={hi[1]:.6f} (最高)")
    print(f"     [MCP] 线路 {lmax[0]} loading_percent={lmax[1]:.2f}% (最重载)")
    return {"vm": vm, "loading": lp}


# --------------------------------------------------------------------------- #
# 步骤 4.2 —— 本地重建 + 闸门
# --------------------------------------------------------------------------- #
def step2_local_gate(mcp_vm: dict) -> "pp.pandapowerNet":
    print("\n" + "=" * 74)
    print("步骤 4.2  本地重建同一算例并校验 —— 🔒 一致性闸门")
    print("=" * 74)
    import pandapower as pp

    print(f"     从与 MCP 相同的文件重建: {IEEE39_JSON.name}")
    net = pp.from_json(str(IEEE39_JSON))
    print(f"     本地网络: {len(net.bus)} 母线 / {len(net.line)} 线路 / "
          f"{len(net.trafo)} 变压器 / {len(net.gen)} 机组 / {len(net.ext_grid)} 平衡机")

    pp.runpp(net)
    assert net.converged, "本地基态潮流未收敛"

    loc_vm = {int(k): float(v) for k, v in net.res_bus.vm_pu.items()}
    common = sorted(set(mcp_vm) & set(loc_vm))
    assert common, "两侧无共同母线键"
    diffs = [(b, loc_vm[b] - mcp_vm[b]) for b in common]
    worst = max(diffs, key=lambda d: abs(d[1]))
    print(f"\n     [闸门] 与 MCP 结果对比（{len(common)} 个母线）")
    print(f"            最大偏差 |Δ| = {abs(worst[1]):.3e} pu  (母线 {worst[0]})")
    assert abs(worst[1]) < TOL_VM, (
        f"本地网络与 MCP 载入的网络不一致（Δ={abs(worst[1]):.3e} pu > {TOL_VM}）——"
        f"后续 OPF 结论无效，必须先修正本地重建"
    )
    print(f"            ✅ 一致（阈值 {TOL_VM:g} pu）—— 本地网络与 MCP 网络是同一个")
    print(f"            ⇒ 后续 OPF 在同一网络上进行，结论对 MCP 侧成立")

    base = {
        "vm_min": (min(loc_vm.items(), key=lambda kv: kv[1])),
        "vm_max": (max(loc_vm.items(), key=lambda kv: kv[1])),
        "line_max": float(net.res_line.loading_percent.max()),
        "line_max_idx": int(net.res_line.loading_percent.idxmax()),
        "trafo_max": float(net.res_trafo.loading_percent.max()),
        "loss_mw": float(net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum()),
        "load_mw": float(net.load.p_mw.sum()),
        "gen_mw": float(net.res_gen.p_mw.sum() + net.res_ext_grid.p_mw.sum()),
    }
    print(f"\n     [基态基准] 线路 {base['line_max_idx']} 最重载 "
          f"{base['line_max']:.2f}% · 变压器最重载 {base['trafo_max']:.2f}%")
    print(f"                网损 {base['loss_mw']:.2f} MW · 总负荷 {base['load_mw']:.2f} MW "
          f"· 总发电 {base['gen_mw']:.2f} MW")
    # 守恒律校验：发电 = 负荷 + 网损
    residual = base["gen_mw"] - (base["load_mw"] + base["loss_mw"])
    print(f"                [守恒校验] 发电 - (负荷 + 网损) = {residual:+.4f} MW")
    assert abs(residual) < 0.05, f"功率不平衡 {residual} MW"
    base["_net"] = net
    return base


# --------------------------------------------------------------------------- #
# 步骤 4.3 —— AC OPF
# --------------------------------------------------------------------------- #
def step3_ac_opf(base: dict) -> dict:
    print("\n" + "=" * 74)
    print("步骤 4.3  AC OPF —— pandapower.runopp()")
    print("=" * 74)
    import pandapower as pp

    net = pp.from_json(str(IEEE39_JSON))     # 干净副本，避免受基态影响
    pp.runpp(net)
    msg, _ = run_quiet(pp.runopp, net, verbose=False)

    assert net.OPF_converged, "AC OPF 未收敛"
    if msg:
        print(f"     [pandapower 提示] {msg}")
        print("     [说明] 该提示指出机组 5 的电压设定值高于其母线上限，")
        print("            pandapower **自动放宽**该母线限值后继续求解。")
        print("            这是算例数据自身的不自洽，被求解器容错处理 ——")
        print("            对比之下，PyPSA 在同一数据上直接判 infeasible。")

    cost = float(net.res_cost)
    gen_mw = float(net.res_gen.p_mw.sum())
    slack_mw = float(net.res_ext_grid.p_mw.sum())
    loss = float(net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum())
    load = float(net.load.p_mw.sum())

    print(f"\n     收敛: {net.OPF_converged}   目标函数值: {cost:,.2f}")
    print(f"     机组出力合计 {gen_mw:.2f} MW + 平衡机 {slack_mw:.2f} MW "
          f"= {gen_mw + slack_mw:.2f} MW")
    print(f"     负荷 {load:.2f} MW + 网损 {loss:.2f} MW = {load + loss:.2f} MW")
    residual = (gen_mw + slack_mw) - (load + loss)
    print(f"     [守恒校验] 发电 - (负荷 + 网损) = {residual:+.4f} MW")
    assert abs(residual) < 0.05, f"AC OPF 功率不平衡 {residual} MW"

    print(f"\n     [机组最优出力] 静默标注 —— 达上限者显式标出，便于核对")
    print(f"       {'机组':<8}{'p_mw':>10}{'max_p_mw':>11}{'q_mvar':>10}{'vm_pu':>9}   状态")
    for i, r in net.res_gen.iterrows():
        max_p = float(net.gen.at[i, "max_p_mw"])
        tag = "← 达上限" if abs(r.p_mw - max_p) < 0.5 else ""
        print(f"       gen_{i:<4}{r.p_mw:>10.4f}{max_p:>11.1f}"
              f"{r.q_mvar:>10.4f}{r.vm_pu:>9.4f}   {tag}")
    print(f"       ext_grid {net.res_ext_grid.p_mw.iloc[0]:>7.4f} MW  "
          f"{net.res_ext_grid.q_mvar.iloc[0]:>8.4f} MVAr   ← 平衡机")

    vm = net.res_bus.vm_pu
    print(f"\n     [电压] 范围 {vm.min():.4f} ~ {vm.max():.4f} pu")
    print(f"            最低 母线 {int(vm.idxmin())} = {vm.min():.4f}   "
          f"最高 母线 {int(vm.idxmax())} = {vm.max():.4f}")
    print(f"     [负载率] 线路 {net.res_line.loading_percent.max():.2f}% (线路 "
          f"{int(net.res_line.loading_percent.idxmax())}) · "
          f"变压器 {net.res_trafo.loading_percent.max():.2f}%")

    print(f"\n     [节点边际电价 lam_p] 前 5 高（可用于容量规划论述）")
    lam = net.res_bus.lam_p.sort_values(ascending=False)
    for b, v in lam.head(5).items():
        print(f"       母线 {int(b):<4} lam_p = {float(v):.4f}")

    return {"cost": cost, "gen_mw": gen_mw + slack_mw, "loss_mw": loss,
            "vm_min": float(vm.min()), "vm_max": float(vm.max()),
            "line_max": float(net.res_line.loading_percent.max()),
            "res_gen": {int(i): float(r.p_mw) for i, r in net.res_gen.iterrows()},
            "slack": slack_mw}


# --------------------------------------------------------------------------- #
# 步骤 4.4 —— DC OPF
# --------------------------------------------------------------------------- #
def step4_dc_opf() -> dict:
    print("\n" + "=" * 74)
    print("步骤 4.4  DC OPF —— pandapower.rundcopp()")
    print("=" * 74)
    import pandapower as pp

    net = pp.from_json(str(IEEE39_JSON))
    pp.runpp(net)
    msg, _ = run_quiet(pp.rundcopp, net, verbose=False)
    if msg:
        print(f"     [pandapower 提示] {msg}")

    assert net.OPF_converged, "DC OPF 未收敛"
    cost = float(net.res_cost)
    gen_mw = float(net.res_gen.p_mw.sum())
    slack_mw = float(net.res_ext_grid.p_mw.sum())
    load = float(net.load.p_mw.sum())
    loss = float(net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum())

    print(f"     收敛: {net.OPF_converged}   目标函数值: {cost:,.2f}")
    print(f"     机组出力合计 {gen_mw:.2f} MW + 平衡机 {slack_mw:.2f} MW "
          f"= {gen_mw + slack_mw:.2f} MW   负荷 {load:.2f} MW")
    # DC OPF 是无网损模型：发电应精确等于负荷
    residual = (gen_mw + slack_mw) - load
    print(f"     [守恒校验] 发电 - 负荷 = {residual:+.4f} MW  "
          f"(DC 模型无网损假设下应≈0)")
    assert abs(residual) < 0.05, f"DC OPF 功率不平衡 {residual} MW"

    print(f"\n     [机组最优出力]")
    for i, r in net.res_gen.iterrows():
        print(f"       gen_{i:<3}{r.p_mw:>11.4f}")
    print(f"       ext_grid {net.res_ext_grid.p_mw.iloc[0]:>7.4f} MW   ← 平衡机")
    print(f"     [负载率] 线路 {net.res_line.loading_percent.max():.2f}%")
    return {"cost": cost, "gen_mw": gen_mw + slack_mw, "loss_mw": loss,
            "res_gen": {int(i): float(r.p_mw) for i, r in net.res_gen.iterrows()},
            "slack": slack_mw}


# --------------------------------------------------------------------------- #
# 步骤 4.5 —— 三方对比
# --------------------------------------------------------------------------- #
def step5_compare(base: dict, ac: dict, dc: dict) -> None:
    print("\n" + "=" * 74)
    print("步骤 4.5  基态潮流 vs AC OPF vs DC OPF")
    print("=" * 74)
    print(f"\n     {'指标':<26}{'基态潮流':>14}{'AC OPF':>14}{'DC OPF':>14}")
    print("     " + "-" * 68)
    rows = [
        ("发电合计 (MW)", base["gen_mw"], ac["gen_mw"], dc["gen_mw"]),
        ("网损 (MW)", base["loss_mw"], ac["loss_mw"], dc["loss_mw"]),
        ("最低电压 (pu)", base["vm_min"][1], ac["vm_min"], None),
        ("最高电压 (pu)", base["vm_max"][1], ac["vm_max"], None),
        ("线路最大负载率 (%)", base["line_max"], ac["line_max"], None),
    ]
    for name, a, b, c in rows:
        bs = f"{b:>14.4f}" if b is not None else f"{'-':>14}"
        cs = f"{c:>14.4f}" if c is not None else f"{'-':>14}"
        print(f"     {name:<26}{a:>14.4f}{bs}{cs}")
    print(f"     {'目标函数值':<26}{'(未优化)':>14}{ac['cost']:>14,.2f}{dc['cost']:>14,.2f}")

    print(f"\n     [AC vs DC] 目标值差 = {ac['cost'] - dc['cost']:,.2f} "
          f"({(ac['cost'] / dc['cost'] - 1) * 100:+.3f}%)")
    print(f"                AC 计及网损（{ac['loss_mw']:.2f} MW），DC 不计网损，"
          f"故 DC 目标值更低属预期。")

    print(f"\n     [逐机组出力对照]")
    print(f"       {'机组':<8}{'AC OPF':>12}{'DC OPF':>12}{'Δ':>12}")
    for i in sorted(set(ac["res_gen"]) & set(dc["res_gen"])):
        a, d = ac["res_gen"][i], dc["res_gen"][i]
        print(f"       gen_{i:<4}{a:>12.4f}{d:>12.4f}{d - a:>+12.4f}")
    print(f"       {'ext_grid':<8}{ac['slack']:>12.4f}{dc['slack']:>12.4f}"
          f"{dc['slack'] - ac['slack']:>+12.4f}")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
async def main() -> int:
    warnings.filterwarnings("ignore")

    print("=" * 74)
    print("示例 04：AC / DC 最优潮流（OPF）")
    print("=" * 74)
    for pkg in ("powermcp", "powerio", "mcp", "pandapower"):
        try:
            print(f"  {pkg:<12} {version(pkg)}")
        except PackageNotFoundError:
            print(f"  {pkg:<12} (未安装)")

    print("\n  ⚠️ 定位声明：OPF 部分**不是 MCP 调用**，而是 Skill 侧直接调用")
    print("     pandapower 的 runopp/rundcopp。原因见本文件头部说明。")
    print("     步骤 4.2 的一致性闸门确保本地网络与 MCP 网络是同一个。")

    assert IEEE39_JSON.exists(), f"缺少算例 {IEEE39_JSON}，请先运行示例 01"

    mcp = await step1_mcp_baseline()
    base = step2_local_gate(mcp["vm"])
    ac = step3_ac_opf(base)
    dc = step4_dc_opf()
    step5_compare(base, ac, dc)

    print("\n" + "=" * 74)
    print("[SUCCESS] 示例 04 全部步骤通过")
    print("=" * 74)
    print("  交付能力：AC OPF（含节点边际电价）与 DC OPF，均取得具体数值。")
    print("  已知例外：该能力不经由 MCP 工具，而是 Skill 侧的 Python 调用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
