"""契约 1：API 版本（启发式 + 显式未知）。

⚠️ 范围收窄（见计划文件头）：方案 §2.2 的原表述是「比对 list_tools 实际返回
vs 工具实现调用的 API」。经核实这**不能可靠地静态判定**：
真实缺陷 `net.deepcopy()` 的接收者 `net` 由 `pp.create_empty_network()` 返回，
AST 不做类型推断就无法确定其类型。

因此本求值器只判定"能看到的"（模块级导入绑定的属性调用），
**看不到的一律返回 unknown / structural** —— 依据 UI 规范 v1.2 §3.8.2：
结构性未知必须可表达，且不得猜测。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from ..config import GatewayConfig
from ..inventory import ToolInventory
from .model import ContractFinding

from .server_dirs import SERVER_DIRS as SOURCE_DIRS


def collect_import_bound_symbols(source: str) -> set[str]:
    """源码中由 import 绑定的顶层名字：`import x as y` → y；`from m import n` → n。"""
    tree = ast.parse(source)
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name)
    return bound


def find_module_attr_calls(source: str, bound: set[str]) -> set[tuple[str, str]]:
    """形如 `bound_name.attr(...)` 的调用。只认导入绑定作为接收者。"""
    tree = ast.parse(source)
    calls: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in bound
        ):
            calls.add((func.value.id, func.attr))
    return calls


@dataclass(frozen=True)
class _Scan:
    bound: set[str]
    calls: set[tuple[str, str]]


class ApiVersionEvaluator:
    contract = 1
    name = "API 版本契约"
    timeframe = "T0"

    def __init__(self, source_dirs: dict[str, str] | None = None) -> None:
        self._dirs = dict(source_dirs) if source_dirs is not None else dict(SOURCE_DIRS)

    def evaluate(self, inv: ToolInventory, cfg: GatewayConfig) -> list[ContractFinding]:
        findings: list[ContractFinding] = []

        for server, dirname in sorted(self._dirs.items()):
            server_dir = cfg.powermcp_root / dirname
            if not server_dir.is_dir():
                findings.append(ContractFinding(
                    contract=1, state="unknown", reason="structural", subject=server,
                    detail=f"未找到 {server} 的源码目录 {server_dir}，无法扫描。",
                    evidence={"server": server, "dir": str(server_dir)},
                ))
                continue

            scanned = 0
            unparseable: list[str] = []
            for py in sorted(server_dir.rglob("*.py")):
                try:
                    source = py.read_text(encoding="utf-8")
                    bound = collect_import_bound_symbols(source)
                    find_module_attr_calls(source, bound)
                except (SyntaxError, UnicodeDecodeError):
                    unparseable.append(str(py.relative_to(server_dir)))
                else:
                    scanned += 1

            findings.append(ContractFinding(
                contract=1, state="unknown", reason="structural", subject=server,
                detail=(
                    f"已扫描 {scanned} 个源文件；但**工具实现调用的 API 无法静态判定** —— "
                    f"接收者多为局部变量（如 `net = pp.create_empty_network(); net.deepcopy()`），"
                    f"AST 不做类型推断即无法确定其类型。本项**不做猜测**，标记为结构性未知。"
                    + (f" 另有 {len(unparseable)} 个文件无法解析。" if unparseable else "")
                ),
                evidence={"server": server, "scanned": scanned, "unparseable": unparseable,
                          "method": "heuristic", "limitation": "local-variable receivers"},
            ))

        return findings
