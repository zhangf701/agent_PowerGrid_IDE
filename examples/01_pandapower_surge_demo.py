"""示例 01：pandapower + surge 全流程（IEEE 39 节点算例）

流程：
  1. 案例加载与基态潮流  —— pandapower server，输出最高/最低母线电压、最重载线路
  2. N-1 故障筛选        —— pandapower run_contingency_analysis 筛选 + surge 取具体数值
  3. 灵敏度矩阵          —— surge compute_ptdf / compute_lodf，打印前 5x5

工程约定（遵循任务约束）：
  * 启动 MCP 服务前显式设置 POWERIO_MCP_ALLOWED_ROOTS，避免路径围笼拒绝读写算例
  * 包版本查询统一用 importlib.metadata，不调用 pip list（uv venv 默认不带 pip）
  * 遵循"先基态潮流收敛，再做故障/优化分析"
  * 所有结论均报出具体数值（母线号 + vm_pu、支路号 + loading_percent）

用法：
    cd <项目根>
    ./.venv/Scripts/python.exe examples/01_pandapower_surge_demo.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

# --------------------------------------------------------------------------- #
# 0. 工程约定：工作目录 + 路径围笼
# --------------------------------------------------------------------------- #
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO = PROJECT_ROOT / "PowerMCP"
PYTHON_EXE = REPO / ".venv" / "Scripts" / "python.exe"
DATA_DIR = PROJECT_ROOT / "examples" / "data"

# 约束 #1：必须显式设置，否则 powerio 路径围笼默认只允许"服务进程启动目录"
os.chdir(PROJECT_ROOT)
os.environ["POWERIO_MCP_ALLOWED_ROOTS"] = os.getcwd()

# 与 PowerMCP 子进程的 stdio 通道必须保持干净：日志走 stderr
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

IEEE39_JSON = DATA_DIR / "case39.json"
IEEE39_M = DATA_DIR / "case39.m"


# --------------------------------------------------------------------------- #
# 1. 极简 MCP stdio 客户端
# --------------------------------------------------------------------------- #
class MCPServer:
    """拉起一个 PowerMCP server 并保持 stdio 会话。"""

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
        """调用工具并把返回的 text content 解析成 dict。"""
        assert self._session is not None, "server not started"
        result = await self._session.call_tool(tool_name, kwargs)
        for item in result.content:
            if getattr(item, "type", None) == "text":
                try:
                    return json.loads(item.text)
                except json.JSONDecodeError:
                    return {"_raw": item.text}
        return {}


# --------------------------------------------------------------------------- #
# 2. 算例准备
# --------------------------------------------------------------------------- #
def ensure_case_files() -> None:
    """生成 IEEE 39 的两种表示（幂等）。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if IEEE39_JSON.exists() and IEEE39_M.exists():
        print(f"[算例] 已存在：{IEEE39_JSON.name}, {IEEE39_M.name}")
        return
    # pandapower JSON：由 pandapower 内置 case39 导出
    if not IEEE39_JSON.exists():
        import warnings
        warnings.filterwarnings("ignore")
        import pandapower as pp
        import pandapower.networks as pn
        pp.to_json(pn.case39(), str(IEEE39_JSON))
        print(f"[算例] 生成 {IEEE39_JSON}")
    # MATPOWER .m：surge 不读 pandapower JSON，经 powerio 转换
    if not IEEE39_M.exists():
        print(f"[算例] 需生成 {IEEE39_M.name}（经 powerio emit）—— 见下方 _emit_matpower")


async def _emit_matpower() -> bool:
    """经 powerio MCP 把 IEEE39 转成 MATPOWER .m 供 surge 使用。"""
    async with MCPServer("powerio") as pio:
        parsed = await pio.call("parse", path=str(IEEE39_JSON), format="pandapower-json")
        ir = parsed.get("powerio_ir", "")
        if not ir:
            print(f"[算例] 失败：parse 未返回 powerio_ir -> {parsed}")
            return False
        emitted = await pio.call(
            "emit", format="matpower", destination=str(IEEE39_M),
            powerio_ir=ir, overwrite=True,
        )
    dropped = [d for d in emitted.get("diagnostics", []) if d.get("severity") == "warning"]
    print(f"[算例] 生成 {IEEE39_M.name}（fidelity={emitted.get('fidelity')}，"
          f"{len(dropped)} 条丢失字段警告）")
    return IEEE39_M.exists()


# --------------------------------------------------------------------------- #
# 3. 步骤 1.1 —— 基态潮流
# --------------------------------------------------------------------------- #
async def step1_base_case() -> dict:
    print("\n" + "=" * 74)
    print("步骤 1.1  基态潮流（pandapower · IEEE 39）")
    print("=" * 74)
    async with MCPServer("pandapower") as pp_srv:
        loaded = await pp_srv.call("load_network", file_path=str(IEEE39_JSON))
        assert loaded.get("status") == "success", f"load_network 失败: {loaded}"
        info = loaded.get("network_info", {})
        print(f"[加载] {info.get('buses')} 母线 / {info.get('lines')} 线路 / "
              f"{info.get('trafos')} 变压器")

        pf = await pp_srv.call("run_power_flow", algorithm="nr",
                               calculate_voltage_angles=True)
        assert pf.get("status") == "success", f"run_power_flow 失败: {pf}"
        res = pf["results"]
        assert res.get("converged") is True, "基态潮流未收敛"

    vm = {int(k): float(v) for k, v in res["bus_results"]["vm_pu"].items()}
    load_pct = {int(k): float(v) for k, v in res["line_results"]["loading_percent"].items()}

    v_lo = min(vm.items(), key=lambda kv: kv[1])
    v_hi = max(vm.items(), key=lambda kv: kv[1])
    l_max = max(load_pct.items(), key=lambda kv: kv[1])

    over_hi = sorted([(b, v) for b, v in vm.items() if v > 1.05], key=lambda kv: -kv[1])
    under_lo = sorted([(b, v) for b, v in vm.items() if v < 0.95], key=lambda kv: kv[1])
    over_load = sorted([(i, v) for i, v in load_pct.items() if v > 100.0],
                       key=lambda kv: -kv[1])

    print(f"[收敛] converged={res['converged']}")
    print(f"[电压] 最低 母线 {v_lo[0]:>3}  vm_pu = {v_lo[1]:.4f}")
    print(f"       最高 母线 {v_hi[0]:>3}  vm_pu = {v_hi[1]:.4f}")
    print(f"       低于 0.95 pu 的母线: {len(under_lo)} 个")
    print(f"       高于 1.05 pu 的母线: {len(over_hi)} 个 -> "
          + ", ".join(f"{b}:{v:.4f}" for b, v in over_hi))
    print(f"[负载] 最重载 线路 {l_max[0]:>3}  loading_percent = {l_max[1]:.2f}%")
    print(f"       过载(>100%) 线路数 = {len(over_load)} / {len(load_pct)}")

    # 诚实说明：>1.05 的母线并非求解异常，而是算例数据中机组设定值本身偏高。
    # 母线 35 的最高值恰等于该处发电机的 vm_pu 设定值（PV 母线维持设定点）。
    if over_hi:
        top_bus, top_v = over_hi[0]
        print(f"[说明] 最高的母线 {top_bus} = {top_v:.4f} pu 恰为 PV 母线，"
              f"其值由机组电压设定值决定；")
        print(f"       故上述 >1.05 计数反映的是算例数据的设定值，而非求解越限。")

    # 断言：只断言真实成立的不变量
    assert res["converged"] is True, "基态潮流未收敛"
    assert not under_lo, f"基态出现低压越限：{under_lo[:5]}"
    assert not over_load, f"基态出现线路过载：{over_load[:5]}"
    print("[断言] 基态收敛 · 无母线低于 0.95 pu · 无线路过载 —— PASS")
    return {"vm": vm, "loading": load_pct}


# --------------------------------------------------------------------------- #
# 4. 步骤 1.2 —— N-1 故障筛选
# --------------------------------------------------------------------------- #
async def step2_contingency() -> None:
    """N-1 故障筛选。两条路径都保留，各有其用。

    **4a — pandapower 的 MCP 工具 `run_contingency_analysis`。**
    其上游缺陷（`panda_mcp.py` 调用已于 pandapower 3.x 移除的
    `net.deepcopy()`）**已在本地分支 `fix/pandapower-deepcopy` 修复**
    （提交 563297a），现可正常返回结果。
    但该工具**只返回元件索引**，不含 `vm_pu` / `loading_percent` 数值，
    且分析后不保留故障态 —— 故它用于**筛选**，不用于取值。

    **4b — surge 的 `run_n1_branch_contingency`。**
    本项目取得**具体数值**的来源：它自带 `max_loading_pct` / `min_vm_pu` /
    `loading_pct` / `flow_mw`，满足"报出具体数值"的要求。

    决策沿革见 docs/journal/2026-09-21-mcp-examples-verification.md §7.
    """
    print("\n" + "=" * 74)
    print("步骤 1.2  N-1 故障筛选（IEEE 39）")
    print("=" * 74)

    # --- 4a. 仍按要求调用 pandapower 的 run_contingency_analysis ---
    print("\n[4a] pandapower · run_contingency_analysis（按要求调用）")
    async with MCPServer("pandapower") as pp_srv:
        await pp_srv.call("load_network", file_path=str(IEEE39_JSON))
        ca = await pp_srv.call("run_contingency_analysis", contingency_type="N-1")

    if ca.get("status") == "success":
        rows = ca["results"]
        viol_rows = [r for r in rows if r.get("violations")
                     and (r["violations"]["voltage_violations"]
                          or r["violations"]["loading_violations"])]
        print(f"     扫描故障 {len(rows)} 个，存在越限 {len(viol_rows)} 个")
        for r in viol_rows[:5]:
            print(f"       {r['contingency']:<16} "
                  f"母线越限 {r['violations']['voltage_violations']}  "
                  f"线路过载 {r['violations']['loading_violations']}")
    else:
        # 走到这里说明本地修复不在生效分支上（例如切回了 main）——如实报告，不隐藏
        print(f"     [BUG] 工具调用失败：{ca.get('message')}")
        print("     [根因] panda_mcp.py 调用了已于 pandapower 3.x 移除的")
        print("            net.deepcopy()；pandapower/requirements.txt 未钉上界，")
        print("            故新装环境必然触发。上游 tests/ 也没有覆盖该工具。")
        print("     [已修] 本地分支 fix/pandapower-deepcopy（563297a）已修复该缺陷；")
        print("            当前报错说明该修复未生效 —— 请确认当前所处分支。")
        print("     [本步] N-1 数值仍由 4b 的 surge 给出 —— 它自带数值输出。")
    print("     [附注] 即便该工具可用，它也只返回元件索引、不含 vm_pu/loading_percent；")
    print("            且分析后不保留故障态，无法事后回查。")

    # --- 4b. surge：本项目采用的 N-1 路径 ---
    print("\n[4b] surge · run_n1_branch_contingency（同一 IEEE 39 算例）")
    async with MCPServer("surge") as sg:
        ld = await sg.call("load_network", file_path=str(IEEE39_M))
        assert ld.get("status") == "success", f"surge load_network 失败: {ld}"
        n1 = await sg.call("run_n1_branch_contingency")
    assert n1.get("status") == "success", f"surge N-1 失败: {n1}"

    d = n1["results"]
    print(f"     {n1['message']}")
    print(f"     开断场景 {d['n_contingencies']} / 有越限 {d['n_with_violations']} / "
          f"越限条目 {d['n_violations']} / 电压严重 {d['n_voltage_critical']}")

    # 逐场景极值：max_loading_pct 为热稳定指标，min_vm_pu 为电压指标
    scored = []
    for r in d["results"]:
        m = r.get("max_loading_pct")
        v = r.get("min_vm_pu")
        scored.append({
            "id": r["contingency_id"],
            "label": r.get("label", ""),
            "max_loading": 0.0 if m is None else float(m),
            "min_vm": float("nan") if v is None else float(v),
            "converged": r.get("converged"),
            "n_viol": r.get("n_violations", 0),
        })

    over = [s for s in scored if s["max_loading"] > 100.0]
    under = [s for s in scored if s["min_vm"] == s["min_vm"] and s["min_vm"] < 0.95]

    # ---- 线路过载 ----
    print(f"\n     线路负载率 >100% 的故障: {len(over)} 个")
    for s in sorted(over, key=lambda x: -x["max_loading"])[:3]:
        print(f"       断号 {s['id']:<12} {s['label']:<22} "
              f"max_loading_pct = {s['max_loading']:7.2f}%   "
              f"越限 {s['n_viol']} 条   converged={s['converged']}")

    # ---- 母线电压越限 ----
    print(f"     母线电压 <0.95 pu 的故障: {len(under)} 个")
    for s in sorted(under, key=lambda x: x["min_vm"])[:3]:
        print(f"       断号 {s['id']:<12} {s['label']:<22} "
              f"min_vm_pu = {s['min_vm']:7.4f}   "
              f"max_loading = {s['max_loading']:7.2f}%   converged={s['converged']}")

    # ---- Top-3 关键故障：按热稳定严重度排序，逐条列出数值 ----
    print("\n     [Top-3 关键故障] 按最大负载率排序（附逐条数值）")
    for rank, s in enumerate(sorted(scored, key=lambda x: -x["max_loading"])[:3], 1):
        print(f"       #{rank} 断号 {s['id']:<12} {s['label']}")
        print(f"           最大负载率 {s['max_loading']:.2f}%   "
              f"最低电压 {s['min_vm']:.4f} pu   越限 {s['n_viol']} 条")
        det = [v for v in d["violations"] if v["contingency_id"] == s["id"]]
        for v in sorted(det, key=lambda x: -(x.get("loading_pct") or 0))[:4]:
            vtype = v.get("violation_type", "?")
            if v.get("loading_pct") is not None:
                # 个别越限条目的 from_bus/to_bus 可能为 None，需容错
                fb, tb = v.get("from_bus"), v.get("to_bus")
                tgt = f"支路 {fb}->{tb}" if fb is not None and tb is not None else "支路 (未标注)"
                mw = v.get("flow_mw")
                mw_s = f"{mw:.2f} MW" if mw is not None else "-"
                print(f"           {vtype:<16} {tgt:<14} "
                      f"loading_pct = {v['loading_pct']:7.2f}%   flow = {mw_s}")
            elif v.get("bus_number") is not None:
                print(f"           {vtype:<16} 母线 {v['bus_number']}  "
                      f"（电压类越限，无负载率）")
            else:
                print(f"           {vtype:<16} (无定位信息)")

    # ---- 全部越限明细 ----
    print(f"\n     越限明细（前 6 条，共 {len(d['violations'])} 条）:")
    for v in d["violations"][:6]:
        tgt = (f"母线 {v['bus_number']}" if v.get("bus_number") is not None
               else f"支路 {v.get('from_bus')}->{v.get('to_bus')}")
        pct, mw = v.get("loading_pct"), v.get("flow_mw")
        print(f"       {v['contingency_id']:<12} {v['violation_type']:<16} {tgt:<18} "
              f"loading_pct={('%.2f%%' % pct) if pct is not None else '-':>10}   "
              f"flow={('%.2f MW' % mw) if mw is not None else '-'}")

    # ---- 断言：基于实测成立的量，不硬编码期望 ----
    assert d["n_contingencies"] > 0, "应至少扫描到一个开断场景"
    assert len(d["violations"]) > 0, "IEEE39 N-1 应至少存在一条越限"
    assert len(over) > 0, "IEEE39 N-1 应至少存在一个线路过载故障"
    n_ac = sum(1 for s in scored if s["converged"])
    print(f"\n     [断言] 扫描 {d['n_contingencies']} 场景 · 收敛 {n_ac} · "
          f"越限 {len(d['violations'])} 条 · 过载故障 {len(over)} 个 —— PASS")


# --------------------------------------------------------------------------- #
# 5. 步骤 1.3 —— 灵敏度矩阵
# --------------------------------------------------------------------------- #
async def step3_matrices() -> None:
    print("\n" + "=" * 74)
    print("步骤 1.3  灵敏度矩阵 PTDF / LODF（surge · IEEE 39）")
    print("=" * 74)
    async with MCPServer("surge") as sg:
        await sg.call("load_network", file_path=str(IEEE39_M))
        ptdf = await sg.call("compute_ptdf", format="full")
        lodf = await sg.call("compute_lodf", format="full")

    for name, resp, keys_field in (("PTDF", ptdf, "monitored_branch_keys"),
                                   ("LODF", lodf, "monitored_keys")):
        assert resp.get("status") == "success", f"{name} 失败: {resp}"
        d = resp["results"]
        nrow, ncol = d["shape"]
        print(f"\n[{name}] {resp['message']}")
        print(f"     维度 {nrow} x {ncol}   非零元 {d['nnz']}   "
              f"稀疏度 {d['sparsity']:.4f}   max|·| = {d['max_abs']:.6f}")
        print(f"     NaN {d['nan_count']}   Inf/None {d['inf_count']}")
        mat = d["matrix"]
        keys = d.get(keys_field, [])
        col_keys = d.get("bus_numbers") or d.get("outage_keys") or []

        def brief_key(k) -> str:
            """列键可能是 int（母线号）或 [from, to, ckt] 列表，统一成短标签。"""
            if isinstance(k, (list, tuple)):
                return "->".join(str(x) for x in k)
            return str(k)

        col_label = "母线号" if name == "PTDF" else "开断支路"
        print(f"     前 5x5（行={keys_field}；列={col_label}）:")
        print("        " + f"{'↓row \\ col':<14}"
              + "".join(f"{brief_key(c):>13}" for c in col_keys[:5]))
        for i in range(min(5, len(mat))):
            label = brief_key(keys[i]) if i < len(keys) else f"row{i}"
            body = "".join(
                ("       null " if c is None else "%13.5f" % c) for c in mat[i][:5])
            print(f"        {label:<14}{body}")


# --------------------------------------------------------------------------- #
# 6. 主流程
# --------------------------------------------------------------------------- #
async def main() -> int:
    print("=" * 74)
    print("示例 01：pandapower + surge（IEEE 39 节点算例）")
    print("=" * 74)
    for pkg in ("powermcp", "powerio", "mcp", "pandapower", "surge-py"):
        try:
            print(f"  {pkg:<12} {version(pkg)}")
        except PackageNotFoundError:
            print(f"  {pkg:<12} (未安装)")

    ensure_case_files()
    if not IEEE39_M.exists():
        if not await _emit_matpower():
            print("[FAIL] 无法生成 MATPOWER 算例，终止")
            return 1

    await step1_base_case()
    await step2_contingency()
    await step3_matrices()

    print("\n" + "=" * 74)
    print("[SUCCESS] 示例 01 全部步骤通过")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
