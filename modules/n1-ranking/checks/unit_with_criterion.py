"""领域自检规则：数值必须与单位同时出现。

★ 这条规则与**契约层无关**（契约层管「接口可靠性」）。它管的是**领域正确性**：
  本选题的结果表里，负载率必须带单位与判据 —— 实测缺陷是
  **用 MW 判据会把 142% 看成 98%**。

★ **契约已冻结**（2026-09-25，G-5 最小闭环）：`check(ctx) -> list[str] | list[dict]`，
  `ctx.rows` 为绑定结果表的数据行（清单 `checks[].result_table`）；空列表 = 通过。
  执行引擎：`gateway/src/powermcp_gateway/checks.py`。

自测：`python modules/n1-ranking/checks/unit_with_criterion.py`
"""

from __future__ import annotations

RULE_ID = "unit-with-criterion"
SEVERITY = "error"

#: 这些列名必须以「带单位」的形式呈现（结果表 schema 里 type=quantity 的列）
QUANTITY_KEYS = ("loading_percent", "flow_mw")

#: 负载率还必须带判据（MVA / MW 判据不同，数值含义不同）
CRITERION_REQUIRED = ("loading_percent",)


def check(ctx) -> list[str]:
    """quantity 列必须带 `unit`，`loading_percent` 还必须带 `criterion`。

    ctx：执行引擎提供的上下文（鸭子类型，本文件只读 `ctx.rows`，不 import 内核）。
    """
    rows: list[dict] = ctx.rows
    problems: list[str] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            problems.append(f"第 {i} 行不是对象，无法判定")
            continue
        for key in QUANTITY_KEYS:
            if key not in row:
                continue
            cell = row[key]
            if not isinstance(cell, dict):
                problems.append(
                    f"第 {i} 行 `{key}` 必须是带单位的单元对象（含 unit），"
                    f"而不是裸值 {cell!r} —— 裸值会让界面无从判断单位"
                )
                continue
            if not cell.get("unit"):
                problems.append(f"第 {i} 行 `{key}` 缺少 `unit`")
            if key in CRITERION_REQUIRED and not cell.get("criterion"):
                problems.append(
                    f"第 {i} 行 `{key}` 缺少 `criterion`（MVA 判据 / MW 判据）—— "
                    "实测：判据不同会把 142% 看成 98%"
                )
    return problems


if __name__ == "__main__":
    import sys
    import types

    good = {"loading_percent": {"value": 161.84, "unit": "%", "criterion": "MVA 判据"}}
    no_unit = {"loading_percent": {"value": 161.84, "criterion": "MVA 判据"}}
    no_crit = {"loading_percent": {"value": 161.84, "unit": "%"}}
    bare = {"loading_percent": 161.84}
    cases = [(good, 0), (no_unit, 1), (no_crit, 1), (bare, 1)]
    bad = 0
    for row, want in cases:
        ctx = types.SimpleNamespace(rows=[row], result_table="n1_results",
                                    module_id="n1-ranking")
        got = len(check(ctx))
        ok = got == want
        bad += not ok
        print(f"  {'✓' if ok else '✗'} {str(row)[:56]:58s} 期望 {want} 实际 {got}")
    sys.exit(1 if bad else 0)
