"""模块 checks 执行引擎（G-4 最小闭环的一半 + G-5 契约落地，2026-09-25）。

## 背景（modules/README.md §四 的 G-4 / G-5）

此前模块可以声明 `checks`，装配期也校验了文件存在，但**没有任何东西执行它们** ——
`/modules` 显示 `enabled: 2` 不等于"这两个模块已经能干活"。本模块把 checks 变成
**有行为**的扩展点：加载 → 构造 ctx → 执行 → 归一为 Finding。

## ★ G-5 契约（2026-09-25 张老师裁决"最小闭环"后冻结的第一版）

**check 文件**是一个 Python 模块，必须导出：

| 名字 | 类型 | 说明 |
|---|---|---|
| `check` | 可调用 | `check(ctx) -> list[str]` 或 `list[dict]`，见下 |
| `RULE_ID` | 非空 str | 规则标识（进 Finding，供前端/审计归因） |
| `SEVERITY` | str | `info` / `warning` / `error` 之一（该规则的**默认**严重级） |

**ctx**（`CheckContext`）字段：`rows`（绑定的结果表数据行，list[dict]）、
`result_table`（表 id）、`module_id`、`case`（可选 dict，调用方自带的算例快照）、
`case_id`（可选 str）。缺什么 ctx 就有什么 —— 不假装拿得到引擎状态。

**返回值**两种都收（显式兼容既有 4 个 check 的 `check(rows) -> list[str]` 写法）：
- `list[str]`：每项是一条问题描述，severity 用模块级 `SEVERITY` 默认值；
- `list[dict]`：`{message: 非空str, severity?: 覆盖默认}`。
- **空列表 = 通过**。返回其它类型 = 该 check 失败（如实上报，不猜）。

**绑定**（清单侧）：`checks[].result_table: <本模块的 result_table id>` —— 必须指向
**本模块已声明**的结果表（装配失败尺度，见 `modules.parse_manifest`）。
★ 绑定键不叫提案里的 `on`：YAML 1.1 把裸键 `on` 解析成布尔值 True（本仓库在
`id: on` 上踩过），`on: rt1` 实际是 {True: 'rt1'}，绑定会**静默失效**。
**未绑定的 check 被引擎跳过并如实上报**（`skipped`），**不会**拿空行去跑 ——
空行跑出的"通过"是 §7.4 说的那种虚假安心。

**隔离**：单个 check 加载/执行失败 → 该 check 产出一条 `severity=error` 的 Finding
（fail-loud），**不影响**同一模块的其它 check，更不影响其它模块。

⚠️ check 以 `importlib` 在**网关进程内**执行 —— 与模块文件同源（仓库内、清单声明、
  装配期校验过），自用工具可接受；若将来开放第三方模块，必须换成子进程沙箱。
"""

from __future__ import annotations

import dataclasses
import importlib.util
import logging
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import GatewayConfig
from .modules import Module, modules_root, load_modules

logger = logging.getLogger(__name__)

SEVERITIES = ("info", "warning", "error")


class CheckError(RuntimeError):
    """check 模块不符合契约（缺 RULE_ID / SEVERITY 非法 / check 不可调用）。"""


@dataclass(frozen=True)
class Finding:
    """一条领域自检结论（区别于 8 类**接口**契约的 `ContractFinding`）。"""

    module_id: str
    check_id: str
    rule_id: str
    severity: str          # info | warning | error
    message: str
    result_table: str = ""


@dataclass(frozen=True)
class CheckContext:
    """传给 check 的运行时上下文。**有什么给什么**，不假装拿得到引擎状态。"""

    rows: list[dict]              # 绑定结果表的数据行（可为空列表）
    result_table: str             # 绑定的结果表 id
    module_id: str
    case: dict | None = None      # 调用方自带的算例快照（可选）
    case_id: str | None = None


@dataclass(frozen=True)
class CheckOutcome:
    """单个 check 的执行结果（含失败与跳过，全部如实上报）。"""

    module_id: str
    check_id: str
    rule_id: str = ""
    severity_default: str = ""
    bound_table: str = ""
    findings: tuple[Finding, ...] = ()
    error: str = ""               # 非空 = 该 check 加载/执行失败


def load_check_module(path: Path) -> tuple[str, str, Any]:
    """加载一个 check 文件，返回 `(rule_id, severity, check_fn)`。

    Raises:
        CheckError: 缺 `RULE_ID` / `SEVERITY` 非法 / `check` 不可调用 / 文件无法执行。
    """
    try:
        spec = importlib.util.spec_from_file_location(
            f"powermcp_module_check_{abs(hash(str(path)))}", path,
        )
        if spec is None or spec.loader is None:
            raise CheckError(f"无法从 {path} 构造导入 spec")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except CheckError:
        raise
    except Exception as exc:
        raise CheckError(f"check 文件执行失败：{type(exc).__name__}: {exc}") from exc

    rule_id = getattr(mod, "RULE_ID", None)
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise CheckError("check 文件缺少非空 `RULE_ID`（str）—— 这是归因的唯一依据")
    severity = getattr(mod, "SEVERITY", None)
    if severity not in SEVERITIES:
        raise CheckError(
            f"`SEVERITY` 必须是 {list(SEVERITIES)} 之一，收到 {severity!r}"
        )
    fn = getattr(mod, "check", None)
    if not callable(fn):
        raise CheckError("check 文件缺少可调用的 `check(ctx)`")
    return rule_id.strip(), severity, fn


def _normalize(message: Any, default_severity: str, ctx_module: str,
               ctx_check: str, rule_id: str, table: str) -> Finding:
    """把 check 的单条返回值归一为 Finding（非法条目 → error 级并说明原因）。"""
    if isinstance(message, str) and message.strip():
        return Finding(module_id=ctx_module, check_id=ctx_check, rule_id=rule_id,
                       severity=default_severity, message=message.strip(),
                       result_table=table)
    if isinstance(message, dict):
        msg = message.get("message")
        if isinstance(msg, str) and msg.strip():
            sev = message.get("severity", default_severity)
            if sev not in SEVERITIES:
                sev = "error"
            return Finding(module_id=ctx_module, check_id=ctx_check, rule_id=rule_id,
                           severity=sev, message=msg.strip(), result_table=table)
        return Finding(module_id=ctx_module, check_id=ctx_check, rule_id=rule_id,
                       severity="error",
                       message="check 返回的 dict 条目缺少非空 `message`",
                       result_table=table)
    return Finding(module_id=ctx_module, check_id=ctx_check, rule_id=rule_id,
                   severity="error",
                   message=f"check 返回了不支持的条目类型 {type(message).__name__}",
                   result_table=table)


def run_module_checks(mod: Module, root: Path, *, rows_by_table: dict[str, list[dict]],
                      case: dict | None = None, case_id: str | None = None,
                      ) -> tuple[list[CheckOutcome], list[dict]]:
    """跑一个模块的全部 checks。返回 `(outcomes, skipped)`。

    - 绑定了 `result_table` → 用 `rows_by_table[绑定表]`（缺该表的行 → 跳过并注明）；
    - **未绑定 → 跳过**（`skipped`，带原因）—— 不拿空行跑出虚假的"通过"。
    """
    outcomes: list[CheckOutcome] = []
    skipped: list[dict] = []
    base = root / mod.path
    for decl in mod.checks:
        on = decl.detail.get("result_table")
        if not isinstance(on, str) or not on.strip():
            skipped.append({
                "module_id": mod.id, "check_id": decl.id,
                "reason": "清单未声明 `result_table`（绑定的结果表）—— "
                          "引擎不会拿空行去跑出虚假的『通过』；请补 `result_table` 后重跑",
            })
            continue
        table = on.strip()
        rows = rows_by_table.get(table)
        if rows is None:
            skipped.append({
                "module_id": mod.id, "check_id": decl.id,
                "reason": f"请求未提供结果表 `{table}` 的数据行（rows_by_table 缺该键）",
            })
            continue
        file_ref = decl.detail.get("file")
        if not isinstance(file_ref, str) or not file_ref.strip():
            outcomes.append(CheckOutcome(
                module_id=mod.id, check_id=decl.id, bound_table=table,
                error="清单未声明 `file`（装配期不应放行 —— 请检查清单）",
            ))
            continue
        try:
            rule_id, severity, fn = load_check_module(base / file_ref)
        except CheckError as exc:
            outcomes.append(CheckOutcome(
                module_id=mod.id, check_id=decl.id, bound_table=table,
                error=str(exc),
            ))
            continue

        ctx = CheckContext(rows=list(rows), result_table=table, module_id=mod.id,
                           case=case, case_id=case_id)
        try:
            raw = fn(ctx)
        except Exception as exc:
            # check 自身崩溃 ≠ 通过 —— 记一条 error 级 Finding，其它 check 不受影响
            outcomes.append(CheckOutcome(
                module_id=mod.id, check_id=decl.id, rule_id=rule_id,
                severity_default=severity, bound_table=table,
                findings=(Finding(
                    module_id=mod.id, check_id=decl.id, rule_id=rule_id,
                    severity="error",
                    message=f"check 执行异常：{type(exc).__name__}: {exc}",
                    result_table=table,
                ),),
            ))
            continue

        if not isinstance(raw, (list, tuple)):
            outcomes.append(CheckOutcome(
                module_id=mod.id, check_id=decl.id, rule_id=rule_id,
                severity_default=severity, bound_table=table,
                error=f"check 返回了 {type(raw).__name__}，契约要求 list[str] 或 list[dict]",
            ))
            continue
        findings = tuple(
            _normalize(item, severity, mod.id, decl.id, rule_id, table)
            for item in raw
        )
        outcomes.append(CheckOutcome(
            module_id=mod.id, check_id=decl.id, rule_id=rule_id,
            severity_default=severity, bound_table=table, findings=findings,
        ))
    return outcomes, skipped


def run_checks(cfg: GatewayConfig, *, module_id: str,
               rows_by_table: dict[str, list[dict]],
               case: dict | None = None, case_id: str | None = None) -> dict:
    """`POST /checks/run` 的实现体：跑指定模块的全部 checks。

    Raises:
        KeyError: 模块 id 不存在（端点映射 404）。
        RuntimeError: 模块被显式禁用（端点映射 409）。
    """
    root = modules_root(cfg)
    rep = load_modules(root)
    mod = next((m for m in rep.modules if m.id == module_id), None)
    if mod is None:
        # 区分「不存在」与「装配失败」—— 后者也能在 failures 里找到，如实转述
        failed = next((f for f in rep.failures if f.module_id == module_id), None)
        if failed is not None:
            raise KeyError(f"模块 `{module_id}` 装配失败，无法执行 checks：{failed.error}")
        raise KeyError(f"模块 `{module_id}` 不存在（已知：{[m.id for m in rep.modules]}）")
    if not mod.enabled:
        raise RuntimeError(f"模块 `{module_id}` 已被禁用（enabled: false）—— 先启用再跑 checks")

    outcomes, skipped = run_module_checks(
        mod, root, rows_by_table=rows_by_table, case=case, case_id=case_id,
    )
    all_findings = [f for o in outcomes for f in o.findings]
    summary = {
        "checks_run": len(outcomes),
        "checks_skipped": len(skipped),
        "check_errors": sum(1 for o in outcomes if o.error),
        "findings_total": len(all_findings),
        "by_severity": {
            s: sum(1 for f in all_findings if f.severity == s)
            for s in SEVERITIES
        },
    }
    return {
        "module_id": mod.id,
        "summary": summary,
        "results": [dataclasses.asdict(o) for o in outcomes],
        "skipped": skipped,
        "notes": [
            "findings 是**领域正确性**结论，与 8 类接口契约（ContractFinding）相互独立；"
            "空 findings 只代表『这些 check 没发现问题』，不代表『没跑 check』"
            "（skipped / check_errors 单列）。",
        ],
    }
