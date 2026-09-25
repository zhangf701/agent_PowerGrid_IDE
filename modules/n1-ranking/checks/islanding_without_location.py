"""领域自检规则：Islanding 类型的越限必须单独标注。

★ **契约已冻结**（2026-09-25，G-5 最小闭环）：`check(ctx) -> list[str] | list[dict]`。
  `ctx.rows` 是绑定结果表（清单 `checks[].result_table`）的数据行；**空列表 = 通过**，
  也可返回 `{message, severity?}` 字典列表。执行引擎：`gateway/src/powermcp_gateway/checks.py`。

之所以先写实：接线时能立刻发现契约是否够用（例如是否需要 ctx / severity / 定位信息）。

来源：`能力与场景总结` 科研场景 1 的「注意事项」——
**`Islanding` 类型无支路定位信息，需容错处理而非崩溃**。

自测：`python modules/n1-ranking/checks/islanding_without_location.py`
"""

from __future__ import annotations

RULE_ID = "islanding-without-location"
SEVERITY = "warning"

#: 孤岛标记列名（与 `schema/n1_columns.json` 的 `is_islanding` 一致）
ISLAND_FLAG = "is_islanding"


def check(ctx) -> list[str]:
    """孤岛行必须带标记 —— 否则会被误当成「元件越限」。

    规则：**既没有越限元件、又没有孤岛标记**的行即为问题。
    （有元件名 = 正常越限；无元件名 + 有孤岛标记 = 已知的孤岛情形。）

    ctx：执行引擎提供的上下文（鸭子类型，本文件只读 `ctx.rows`，不 import 内核）。
    """
    rows: list[dict] = ctx.rows
    problems: list[str] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            problems.append(f"第 {i} 行不是对象，无法判定")
            continue
        if row.get("violating_element") or row.get(ISLAND_FLAG):
            continue
        problems.append(
            f"第 {i} 行既没有越限元件、也没有孤岛标记 —— "
            "Islanding 类型无支路定位信息，必须显式标为孤岛"
        )
    return problems


if __name__ == "__main__":
    import sys
    import types

    cases = [
        ([{"violating_element": "branch_26", "is_islanding": False}], 0, "正常越限"),
        ([{"violating_element": "", "is_islanding": True}], 0, "孤岛已标记"),
        ([{"violating_element": "", "is_islanding": False}], 1, "孤岛未标记 ← 应报"),
        ([{"violating_element": None, "is_islanding": None}], 1, "两者皆空 ← 应报"),
        ([], 0, "空表"),
    ]
    bad = 0
    for rows, want, label in cases:
        ctx = types.SimpleNamespace(rows=rows, result_table="n1_results",
                                    module_id="n1-ranking")
        got = len(check(ctx))
        ok = got == want
        bad += not ok
        print(f"  {'✓' if ok else '✗'} {label}: 期望 {want} 条问题，实际 {got}")
    sys.exit(1 if bad else 0)
