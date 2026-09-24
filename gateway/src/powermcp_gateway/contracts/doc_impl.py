r"""契约 2：文档-实现一致性。

比对 server 的 README.md 所声明的工具面 vs `list_tools` 实际返回。

## 提取口径 v2（2026-09-24 重写）

v1 的口径是"全文任意被反引号包裹的 snake_case 标识符"。实测在 8 个引擎上
产生**大量误报** —— pypsa 36 条、andes 13 条、genx 3 条、hope 3 条、surge 2 条，
全部是 README 里的 **API 方法名 / 参数名 / 响应字段名**，而不是工具名。
（例：pypsa 的 `add_constraint`、andes 的 `dyr_path`、surge 的 `summary`。）
更糟的是：真正的已知证据 opendss 因拉不起来而未进入 inventory，
契约 2 根本没检查到它 —— 即 v1 是"误报满屏、真证据漏检"。

v2 改为**结构化提取**：只在"工具清单区块"内、只认"工具名位置"的标识符。
实测自 8 个引擎的 README，共 5 种写法，全部覆盖：

| 引擎 | 写法 |
|---|---|
| pandapower · ANDES · Egret | ``- **name(params)**: 说明`` |
| surge | ``- `name(params)` — 说明`` |
| PyPSA · GenX | ``- [x] `name` - 说明`` |
| OpenDSS | ``\| **name** \| 用途 \|``（表格首列） |
| HOPE | `## Tool split` 下的 ``- `name` `` |

提取规则（三者取并集）：
1. **列 0 列表项**的第一个粗体/反引号标识符（`- ` 或 `- [x] `）
2. **表格行**的第一个粗体/反引号标识符
3. **续行**：缩进且**直接以**粗体/反引号标识符开头的行（surge 的多工具枚举）

并施加两道排除：
- **必须含下划线** —— 工具名一律带 `_`；`summary` / `sparse` / `full` 这类参数取值被排除
- **缩进子项（以 `- ` 开头）不算** —— 那是 ANDES 式的参数/字段说明

## 已知局限（如实记录，不掩盖）

- **行内提及的 helper 提取不到**：GenX 的 `` `plot_capacity` `` 后跟
  "(with helpers `check_capacity_setting` and `summarize_capacity`)"，
  后两个会被判为"未声明"。当前仅 genx 命中，表现为 `degraded` 而非 `violated`。
- **判定为 `violated` 需要"声明的工具名在运行时不存在"**。v2 在 8 个引擎上
  **未产生任何 `violated`**（v1 曾产生 5 条，经逐条核实全部为误报）。
- 本口径是**启发式**，不是解析器。README 写法若再新增第 6 种，需同步扩展。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..config import GatewayConfig
from ..inventory import ToolInventory
from .model import ContractFinding

# server id -> PowerMCP 仓库内的目录名（大小写敏感，实测自仓库结构）
SERVER_DOC_DIRS: dict[str, str] = {
    "pandapower": "pandapower",
    "pypsa": "PyPSA",
    "surge": "surge",
    "andes": "ANDES",
    "egret": "Egret",
    "opendss": "OpenDSS",
    "hope": "HOPE",
    "genx": "GenX",
}

# 实测自 8 个引擎 README 的工具清单标题（大小写不敏感）
TOOL_SECTIONS: tuple[str, ...] = ("Available Tools", "Tools", "Tool split")

_SECTION = re.compile(
    r"^#{1,2}\s+(?:" + "|".join(re.escape(s) for s in TOOL_SECTIONS) + r")\s*$",
    re.IGNORECASE,
)
_ANY_H12 = re.compile(r"^#{1,2}\s+")
_LIST_ITEM = re.compile(r"^-\s+(?:\[[ xX]\]\s+)?(?:\*\*|`)([A-Za-z_][A-Za-z0-9_]*)")
_TABLE_ROW = re.compile(r"^\|\s*(?:\*\*|`)([A-Za-z_][A-Za-z0-9_]*)")
_CONTINUATION = re.compile(r"^\s+(?:\*\*|`)([A-Za-z_][A-Za-z0-9_]*)")


def extract_declared_tool_names(markdown: str) -> set[str]:
    """从 README 的工具清单区块提取「声明的工具名」。

    只在清单区块内、只认工具名位置（列 0 列表项 / 表格首列 / 续行），
    并要求含下划线 —— 见模块 docstring 的口径说明与已知局限。
    """
    names: set[str] = set()
    inside = False

    for line in markdown.splitlines():
        if _SECTION.match(line):
            inside = True
            continue
        if inside and _ANY_H12.match(line):
            break  # 下一个同级或更高级标题 → 清单区块结束
        if not inside:
            continue

        m = _LIST_ITEM.match(line) or _TABLE_ROW.match(line) or _CONTINUATION.match(line)
        if m is None:
            continue

        name = m.group(1)
        if "_" in name:  # 工具名一律含下划线；参数取值/包名被排除
            names.add(name)

    return names


class DocImplEvaluator:
    contract = 2
    name = "文档-实现一致性"
    timeframe = "T0"

    def __init__(self, doc_dirs: dict[str, str] | None = None) -> None:
        self._doc_dirs = dict(doc_dirs) if doc_dirs is not None else dict(SERVER_DOC_DIRS)

    def evaluate(self, inv: ToolInventory, cfg: GatewayConfig) -> list[ContractFinding]:
        findings: list[ContractFinding] = []
        mounted = set(inv.servers())

        # ★ 迭代 all_servers() 而非 servers()：拉起失败的 server 也要被检查到。
        #   首版用 servers() 时，失败的 server 从视野里消失 —— 契约 2 变成"静默跳过"，
        #   看起来"没问题"，实际是"没检查"。
        for server in inv.all_servers():
            dirname = self._doc_dirs.get(server)
            readme = (cfg.powermcp_root / dirname / "README.md") if dirname else None

            if readme is None or not readme.is_file():
                findings.append(
                    ContractFinding(
                        contract=2, state="unknown", reason="structural", subject=server,
                        detail=f"未找到 {server} 的 README.md，无法比对文档与实现。",
                        evidence={"server": server, "readme": str(readme) if readme else None},
                    )
                )
                continue

            if server not in mounted:
                # 拿不到运行时工具清单 → **无法比对**。
                # 报 violated 会是误报（README 里的名字并非"不存在"，而是"无从核对"）。
                findings.append(
                    ContractFinding(
                        contract=2, state="unknown", reason="structural", subject=server,
                        detail=(
                            f"`{server}` 未能拉起，拿不到运行时工具清单，**无法比对**文档与实现。"
                            f"（该失败本身记在**契约 8**）"
                        ),
                        evidence={"server": server, "readme": str(readme), "mounted": False},
                    )
                )
                continue

            actual = set(inv.names(server))

            declared = extract_declared_tool_names(readme.read_text(encoding="utf-8"))
            declared_missing = sorted(declared - actual)
            undocumented = sorted(actual - declared)

            if declared_missing:
                findings.append(
                    ContractFinding(
                        contract=2, state="violated", reason=None, subject=server,
                        detail=(
                            f"README 声明的 {len(declared_missing)} 个工具在运行时不存在："
                            f"{'、'.join(declared_missing)}。"
                        ),
                        evidence={"server": server, "declared_missing": declared_missing,
                                  "readme": str(readme), "method": "structured-v2"},
                    )
                )
            if undocumented:
                findings.append(
                    ContractFinding(
                        contract=2, state="degraded", reason=None, subject=server,
                        detail=(
                            f"{len(undocumented)} 个工具未在 README 中声明："
                            f"{'、'.join(undocumented)}。"
                        ),
                        evidence={"server": server, "undocumented": undocumented},
                    )
                )
            if not declared_missing and not undocumented:
                findings.append(
                    ContractFinding(
                        contract=2, state="satisfied", reason=None, subject=server,
                        detail=f"{server} 的 README 与运行时工具面一致（{len(actual)} 个）。",
                        evidence={"server": server, "tool_count": len(actual)},
                    )
                )

        return findings
