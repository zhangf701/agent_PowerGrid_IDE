"""领域自检规则：一致性结论必须给出 **Δ 值**。

★ 与契约层无关，管**领域正确性**：跨引擎比对若只给「一致 / 不一致」而不给 Δ，
  读者无法判断"差多少算一致"。实测参考量级：Δ = 6.98e−11 pu（机器精度）。

⚠️ 契约尚未冻结（见 n1-ranking/checks 的同名说明）。

自测：`python modules/cross-engine-consistency/checks/delta_must_be_shown.py`
"""

from __future__ import annotations

RULE_ID = "delta-must-be-shown"
SEVERITY = "error"


def check(rows: list[dict]) -> list[str]:
    """同一 `metric` 若出现在多个引擎行里，**每行都必须给 `delta`**。"""
    seen: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        if isinstance(row, dict) and row.get("metric"):
            seen.setdefault(str(row["metric"]), []).append(i)

    problems: list[str] = []
    for metric, idxs in seen.items():
        if len(idxs) < 2:
            continue                      # 只有一个引擎，无所谓一致性
        for i in idxs:
            if rows[i].get("delta") in (None, ""):
                problems.append(
                    f"`{metric}` 有 {len(idxs)} 个引擎行，但第 {i} 行没有 `delta` —— "
                    "一致性结论必须给出 Δ 值，否则无法判断差多少算一致"
                )
    return problems


if __name__ == "__main__":
    import sys

    ok_rows = [
        {"metric": "min_vm_pu", "engine": "pandapower", "delta": {"value": 7e-11, "unit": "pu"}},
        {"metric": "min_vm_pu", "engine": "pypsa", "delta": {"value": 7e-11, "unit": "pu"}},
    ]
    missing = [
        {"metric": "min_vm_pu", "engine": "pandapower"},
        {"metric": "min_vm_pu", "engine": "pypsa"},
    ]
    single = [{"metric": "min_vm_pu", "engine": "pandapower"}]
    cases = [(ok_rows, 0, "两个引擎且都有 Δ"), (missing, 2, "两个引擎但都缺 Δ ← 应报"),
             (single, 0, "单引擎，不适用")]
    bad = 0
    for rows, want, label in cases:
        got = len(check(rows))
        ok = got == want
        bad += not ok
        print(f"  {'✓' if ok else '✗'} {label}: 期望 {want} 实际 {got}")
    sys.exit(1 if bad else 0)
