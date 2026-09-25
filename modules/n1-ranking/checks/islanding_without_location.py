"""领域自检规则：Islanding 类型的越限必须单独标注。

⚠️ **契约尚未冻结**：本模块声明了 `checks`，但网关**还没有执行引擎**
（`modules.py` 只校验文件存在，不加载也不调用）。
本文件按下面这个**提议的**契约书写，接线时若调整，需同步改这里：

    check(rows: list[dict]) -> list[str]
        返回问题描述列表；**空列表 = 通过**。

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


def check(rows: list[dict]) -> list[str]:
    """孤岛行必须带标记 —— 否则会被误当成「元件越限」。

    规则：**既没有越限元件、又没有孤岛标记**的行即为问题。
    （有元件名 = 正常越限；无元件名 + 有孤岛标记 = 已知的孤岛情形。）
    """
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

    cases = [
        ([{"violating_element": "branch_26", "is_islanding": False}], 0, "正常越限"),
        ([{"violating_element": "", "is_islanding": True}], 0, "孤岛已标记"),
        ([{"violating_element": "", "is_islanding": False}], 1, "孤岛未标记 ← 应报"),
        ([{"violating_element": None, "is_islanding": None}], 1, "两者皆空 ← 应报"),
        ([], 0, "空表"),
    ]
    bad = 0
    for rows, want, label in cases:
        got = len(check(rows))
        ok = got == want
        bad += not ok
        print(f"  {'✓' if ok else '✗'} {label}: 期望 {want} 条问题，实际 {got}")
    sys.exit(1 if bad else 0)
