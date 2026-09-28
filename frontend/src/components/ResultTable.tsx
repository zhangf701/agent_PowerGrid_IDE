/** ResultTable —— 结果表的**完整列**渲染（UI 规范 v2 §4.7.4 · C 组研究视图）。
 *
 *  ★ 为什么必须有它：`ExperimentGrid` 的行内**只显示 4 项**"一眼可见"的指标
 *    （`INLINE_METRIC_LIMIT`），并提示"（共 N 项指标，见结果表）" ——
 *    但此前**这张表并不存在**，于是排在字母序第 5 位之后的指标（如 `metric.results.n_buses`）
 *    在界面上**无处可见**：实测行内只剩 areas.count / base_mva / freq_hz / n_areas。
 *    本组件补上那个"见结果表"的落点。
 *
 *  ★ 列**由网关的 `columns` 决定**（不预设领域列）：V1 出 `metric.*`，
 *    V2 出 `metric.*`（键带命名空间前缀）。本组件只渲染，不发明列、不猜语义。
 *
 *  ★ 状态列走 `Signature`（图标 + 文字 + 颜色三元绑定）—— 颜色不单独承载信息。
 */
import type { ResultColumn, ResultRow } from "../api";

import { Signature } from "./Signature";
import { cellSignature } from "./ExperimentGrid";

function fmtCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Number(v.toFixed(6)));
  return String(v);
}

/** 取某列在某行的值：**先看行顶层，再落到 `metrics`**。
 *
 *  网关的 `columns` 是「保留列（index/case_id/status/ran_at）+ 各格指标并集」，
 *  保留列在行顶层，指标键（`metric.*`）在 `row.metrics` 里 —— 两处都要覆盖。
 */
export function cellValue(row: ResultRow, key: string): unknown {
  if (key in row) return (row as unknown as Record<string, unknown>)[key];
  return row.metrics[key];
}

export function ResultTable({
  columns,
  rows,
}: {
  columns: ResultColumn[];
  rows: ResultRow[];
}) {
  if (!columns.length) return null;

  return (
    <div
      data-testid="result-table"
      className="mt-2 overflow-x-auto rounded-sm border border-border-subtle"
    >
      <table className="w-full border-collapse text-caption">
        <thead>
          <tr className="border-b border-border-subtle bg-surface-sunken text-left text-text-muted">
            {columns.map((c) => (
              <th key={c.key} className="whitespace-nowrap px-2 py-1 font-normal">
                {c.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, rowIdx) => (
            /* ⚠️ key 用「行位置 + cache_key」：单独用 cache_key 在重复格上会撞
               （未引用因子 → 各格 cache_key 相同），单独用 index 在追加行上会撞。 */
            <tr key={`${rowIdx}-${r.cache_key}`} className="border-b border-border-subtle last:border-b-0">
              {columns.map((c) => {
                const value = cellValue(r, c.key);
                return (
                  <td key={c.key} className="whitespace-nowrap px-2 py-1 align-top">
                    {c.type === "state" ? (
                      <Signature sig={cellSignature(String(value)).sig} text={cellSignature(String(value)).label} />
                    ) : (
                      <span className="font-mono">{fmtCell(value)}</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
