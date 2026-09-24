"""契约 4：状态映射可信度。

## 判据的来历（不是照抄方案）

方案 §2.2 写的是「求解器返回码 vs 引擎实际状态」，§11.1 又自陈「若返回码语义不明
则需额外探测 → 降级为未知」—— 含糊且不可判定。

实测得到的**可判定等价命题**：

    求解型工具若报告"成功"，但**从未读取引擎的真实状态字段**，
    则存在"求解失败被报成成功"的风险。

实测（2026-09-24，8 个 server）产出 6 条，且对照组正确：
  pandapower.run_power_flow         读 net.converged            → 不报
  pandapower.run_contingency_analysis 读 contingency_net.converged → 不报
  andes.run_power_flow              读 ss.PFlow.converged        → 不报
  andes.run_time_domain_simulation  读 "completed" if success else "failed" → 不报
  pypsa.run_power_flow              无读取                        → 报
  pypsa.run_contingency_analysis    无读取                        → 报
  andes.run_eigenvalue_analysis     无读取                        → 报
  egret.solve_unit_commitment_problem / solve_ac_opf / solve_dc_opf 无读取 → 报

⚠️ 判据必须区分「分层设计」与「以成功掩盖失败」：pandapower 的 `status: "success"`
   是**传输层**语义，物理结果在 `converged` 字段 —— 那是正确设计，不得误报。

## 工具注册有两种形态，只认一种会漏掉整个 server

实测发现 `PowerMCP/` 里 MCP 工具的注册**不只有装饰器**：

| 形态 | 写法 | 使用者 |
|---|---|---|
| (a) 装饰器 | `@mcp.tool()` / `@mcp.tool` | pandapower / pypsa / surge / andes / egret / hope / genx |
| (b) 函数式 | `mcp.tool()(fn)`，包在 `register_*_tools(mcp)` 里 | **OpenDSS（55 个工具全靠这种）** |

只认 (a) 时 OpenDSS 的 55 个工具**全部漏检**（`tools=0`），于是 `checked == 0`，
在旧口径下报 `satisfied`，理由是「0 个求解型工具均读取了引擎状态字段」——
这是一条**假绿灯**：网关根本没看到 OpenDSS 的任何工具。其中 `solve_snapshot`
名字含 `solve`，本应被本契约检查。

修正后实测：OpenDSS 识别出 55 个工具、`solve_checked=1`，其余 7 个 server 的
工具数**逐个不变**（无新误报），risky 总数仍为 6。

## `checked == 0` 不得报 satisfied

`checked == 0` 有两种成因，旧口径无法区分却一律报 satisfied：

1. 该 server 确无求解型工具（判据不适用）—— 报 satisfied 尚可接受
2. **工具定义形态未被识别**（判据失效）—— 报 satisfied 是假绿灯

与 UI 规范 P5「禁止静默 fail-open」一致的处理：**`checked == 0` → `unknown / structural`**，
并在 detail 里带上已识别的工具总数，让"看不到"与"确实没有"可诊断。

修正后实测：仅 `genx` 落在此分支（识别 7 个工具、无一匹配求解型命名）。

## 为什么是 T0 而不是 T2

本判据**纯静态可判定**，无需逐调用求值。方案把它标为 T2 是过度设计 ——
本计划有意修正为 T0。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ..config import GatewayConfig
from ..inventory import ToolInventory
from .model import ContractFinding
# 目录映射取自单一真源（Task 2）—— 本模块**不再自带副本**
from .server_dirs import SERVER_DIRS

#: 求解型工具的命名特征
SOLVE_NAME = re.compile(
    r"solve|run_|opf|optim|contingency|power_flow|sced|scuc|simulation|eigenvalue",
    re.IGNORECASE,
)

#: 表达"结果状态"的字段名
STATUS_KEYS = frozenset({"status", "converged", "success", "succeeded", "ok"})

#: 视为"报告成功"的字面量
_SUCCESS_LITERALS = ("success", "completed", True)


def analyse_tool_fn(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[bool, tuple[str, ...]]:
    """返回 (是否报告成功, 引擎状态读取的表达式文本)。

    「报告成功」= 返回的 dict 里有状态类字段被赋成成功字面量。
    「引擎状态读取」= 同一 dict 里状态类字段的值是属性访问或条件表达式
    （即值不是编译期常量 —— 它来自运行时，也就是引擎）。
    """
    reports_success = False
    reads: list[str] = []

    for node in ast.walk(fn):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            if key.value.lower() not in STATUS_KEYS:
                continue

            if isinstance(value, ast.Constant):
                if value.value in _SUCCESS_LITERALS:
                    reports_success = True
            elif isinstance(value, ast.Attribute):
                reads.append(ast.unparse(value))
            elif isinstance(value, ast.IfExp):
                reads.append(ast.unparse(value)[:80])

    return reports_success, tuple(dict.fromkeys(reads))


def _tool_functions(tree: ast.Module):
    """产出被注册为 MCP 工具的函数定义 —— 识别两种形态。

    (a) 装饰器：``@mcp.tool()`` / ``@mcp.tool``
    (b) 函数式：``mcp.tool()(fn)`` —— OpenDSS 的 55 个工具全靠这种

    只认 (a) 会让 OpenDSS 整站漏检，见模块 docstring。
    """
    funcs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.setdefault(node.name, node)

    seen: set[int] = set()

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            f = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(f, ast.Attribute) and f.attr == "tool":
                if id(node) not in seen:
                    seen.add(id(node))
                    yield node
                break

    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        inner = call.func
        if not isinstance(inner, ast.Call):
            continue
        inner_f = inner.func
        if not (isinstance(inner_f, ast.Attribute) and inner_f.attr == "tool"):
            continue
        for arg in call.args:
            if isinstance(arg, ast.Name) and arg.id in funcs:
                target = funcs[arg.id]
                if id(target) not in seen:
                    seen.add(id(target))
                    yield target


class StatusMappingEvaluator:
    contract = 4
    name = "状态映射契约"
    timeframe = "T0"

    def __init__(self, source_dirs: dict[str, str] | None = None) -> None:
        self._dirs = dict(source_dirs) if source_dirs is not None else dict(SERVER_DIRS)

    def evaluate(self, inv: ToolInventory, cfg: GatewayConfig) -> list[ContractFinding]:
        findings: list[ContractFinding] = []

        for server, dirname in sorted(self._dirs.items()):
            server_dir = cfg.powermcp_root / dirname
            if not server_dir.is_dir():
                findings.append(ContractFinding(
                    contract=4, state="unknown", reason="structural", subject=server,
                    detail=f"未找到 {server} 的源码目录 {server_dir}，无法扫描状态映射。",
                    evidence={"server": server, "dir": str(server_dir)},
                ))
                continue

            risky: list[str] = []
            checked = 0
            recognised = 0
            unparseable: list[str] = []
            for py in sorted(server_dir.rglob("*.py")):
                try:
                    tree = ast.parse(py.read_text(encoding="utf-8"))
                except (SyntaxError, UnicodeDecodeError):
                    unparseable.append(str(py.relative_to(server_dir)))
                    continue
                for fn in _tool_functions(tree):
                    recognised += 1
                    if not SOLVE_NAME.search(fn.name):
                        continue
                    checked += 1
                    hard_success, reads = analyse_tool_fn(fn)
                    if hard_success and not reads:
                        risky.append(fn.name)

            base_evidence = {
                "server": server,
                "tools_recognised": recognised,
                "solve_tools_checked": checked,
                "unparseable": unparseable,
                "method": "static-ast",
            }

            if risky:
                findings.append(ContractFinding(
                    contract=4, state="degraded", reason=None, subject=server,
                    detail=(
                        f"{len(risky)} 个求解型工具报告成功但**从不读取引擎状态**："
                        f"{'、'.join(risky)}。求解失败可能被报成成功。"
                    ),
                    evidence={**base_evidence, "risky_tools": risky},
                ))
            elif checked == 0:
                findings.append(ContractFinding(
                    contract=4, state="unknown", reason="structural", subject=server,
                    detail=(
                        f"已识别 {recognised} 个工具，但无一匹配求解型命名 —— 本判据对该 server "
                        f"无适用对象。**不报 satisfied**：无法区分「确无求解型工具」与"
                        f"「工具定义形态未被识别」。"
                    ),
                    evidence=base_evidence,
                ))
            else:
                findings.append(ContractFinding(
                    contract=4, state="satisfied", reason=None, subject=server,
                    detail=f"求解型工具均读取了引擎状态字段（共 {checked} 个）。",
                    evidence=base_evidence,
                ))

        return findings
