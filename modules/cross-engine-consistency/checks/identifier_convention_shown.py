"""领域自检规则：多引擎比对行必须标注**标识符编号约定**。

★ 这条规则与契约层无关（契约层管「接口可靠性」）。它管**领域正确性**：
  实测缺陷 —— 字面键比对拿错物理元件，**首次误报 0.068 pu**；
  跨引擎编号约定不一致会把偏差**放大 3.1 亿倍**。

★ **契约已冻结**（2026-09-25，G-5 最小闭环）：`check(ctx) -> list[str] | list[dict]`，
  `ctx.rows` 为绑定结果表的数据行（清单 `checks[].result_table`）；空列表 = 通过。
  执行引擎：`gateway/src/powermcp_gateway/checks.py`。

自测：`python modules/cross-engine-consistency/checks/identifier_convention_shown.py`
"""

from __future__ import annotations

RULE_ID = "identifier-convention-shown"
SEVERITY = "error"

ALLOWED = ("0-based", "1-based")


def check(ctx) -> list[str]:
    """含 `engine` 的行必须给出该引擎的编号约定，且取值合法。

    ctx：执行引擎提供的上下文（鸭子类型，本文件只读 `ctx.rows`，不 import 内核）。
    """
    rows: list[dict] = ctx.rows
    problems: list[str] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            problems.append(f"第 {i} 行不是对象，无法判定")
            continue
        engine = row.get("engine")
        if not engine:
            continue                      # 非多引擎行，本规则不管
        conv = row.get("identifier_convention")
        if conv is None:
            problems.append(
                f"第 {i} 行（引擎 {engine}）缺少 `identifier_convention` —— "
                "跨引擎比对必须标注 0-based / 1-based，否则会张冠李戴"
            )
        elif conv not in ALLOWED:
            problems.append(
                f"第 {i} 行（引擎 {engine}）的 `identifier_convention` 为 {conv!r}，"
                f"合法取值为 {ALLOWED} —— **不得猜**，拿不到就报 unknown"
            )
    return problems


if __name__ == "__main__":
    import sys
    import types

    cases = [
        ([{"engine": "pypsa", "identifier_convention": "1-based"}], 0, "合规"),
        ([{"engine": "pypsa"}], 1, "缺约定 ← 应报"),
        ([{"engine": "pypsa", "identifier_convention": "1based"}], 1, "取值非法 ← 应报"),
        ([{"metric": "min_vm_pu"}], 0, "非多引擎行，不适用"),
        ([], 0, "空表"),
    ]
    bad = 0
    for rows, want, label in cases:
        ctx = types.SimpleNamespace(rows=rows, result_table="delta_results",
                                    module_id="cross-engine-consistency")
        got = len(check(ctx))
        ok = got == want
        bad += not ok
        print(f"  {'✓' if ok else '✗'} {label}: 期望 {want} 实际 {got}")
    sys.exit(1 if bad else 0)
