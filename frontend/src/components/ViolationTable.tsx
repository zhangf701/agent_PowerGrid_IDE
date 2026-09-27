/** ViolationTable —— N-1 违规的结构化表格（§6.1 图型判据：逐位核对的数值**必须用表**）。
 *
 *  ★ 数据来源：`extractViolations()`（数据适配层）—— 数值经 `measure()`（单位 + 判据强制）、
 *    位置经 `Identifier`（编号约定强制），**不是模型转述**（同 F-4 的理由：实测模型会把
 *    数组位置当成母线编号）。
 *
 *  ★ 两条硬规则：
 *    ① **排序在数据层做死**（热越限按负载率降序 → 电压按越限幅度降序）—— 本组件只按
 *      给定顺序渲染，不自行排序（单一职责：排序逻辑可单测）。
 *    ② **截断必须可见**：违规常几十条（case118 实测 52 条），全渲染会把对话流撑爆；
 *      只显示严重度前 N 条时**必须**写明「共 X 条 · 显示前 N」—— 静默截断 = 让读者
 *      以为看到的就是全部（fail-open 的呈现层变体）。
 *
 *  ★ §7.2「阈值必须写出」：热越限同时给出 `flow / limit MVA`；电压同时给出限值。
 *  ★ 颜色不单独承载信息：越限行用 `Quantity` 的 `alarm`（文字「超限」），不用纯色块。
 */
import { Identifier } from "./Identifier";
import { Quantity } from "./Quantity";
import { VIOLATION_TYPE_LABEL, type ViolationItem } from "../results";

/** 默认显示条数 —— 真实样本 case118 有 52 条；前 10 条已覆盖全部热越限 Top 场景。 */
export const DEFAULT_MAX_ROWS = 10;

export function ViolationTable({
  items,
  maxRows = DEFAULT_MAX_ROWS,
}: {
  items: ViolationItem[];
  maxRows?: number;
}) {
  if (!items.length) return null;
  const shown = items.slice(0, maxRows);
  const truncated = items.length > shown.length;

  return (
    <div
      data-testid="violation-table"
      className="mt-1 overflow-x-auto rounded-sm border border-border-subtle"
    >
      <table className="w-full border-collapse text-caption">
        <thead>
          <tr className="border-b border-border-subtle bg-surface-sunken text-left text-text-muted">
            <th className="px-2 py-1 font-normal">场景</th>
            <th className="px-2 py-1 font-normal">类型</th>
            <th className="px-2 py-1 font-normal">位置</th>
            <th className="px-2 py-1 font-normal">负载率</th>
            <th className="px-2 py-1 font-normal">视在功率 / 限值</th>
            <th className="px-2 py-1 font-normal">电压 / 限值</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((it, i) => (
            <tr key={i} className="border-b border-border-subtle last:border-b-0">
              <td className="px-2 py-1 font-mono">{it.contingencyId}</td>
              <td className="px-2 py-1 whitespace-nowrap">
                {VIOLATION_TYPE_LABEL[it.type] ?? "?"}
                <span className="ml-1 text-text-muted">{it.type}</span>
              </td>
              <td className="px-2 py-1 whitespace-nowrap">
                {it.bus && (
                  <Identifier id={it.bus.id} convention={it.bus.convention} kind="母线" />
                )}
                {it.branch && (
                  <span className="whitespace-nowrap">
                    <Identifier id={it.branch.from} convention={it.branch.convention} kind="母线" />
                    <span className="mx-0.5 text-text-muted">→</span>
                    <Identifier id={it.branch.to} convention={it.branch.convention} kind="母线" />
                  </span>
                )}
                {!it.bus && !it.branch && <span className="text-text-muted">—</span>}
              </td>
              <td className="px-2 py-1">
                {it.loading && (
                  <Quantity of={it.loading} alarm={it.loading.value > 100 ? { level: "over" } : undefined} />
                )}
              </td>
              <td className="px-2 py-1 whitespace-nowrap">
                {it.flowMva && it.limitMva ? (
                  <span className="whitespace-nowrap">
                    <Quantity of={it.flowMva} />
                    <span className="font-mono text-text-muted"> / 限 {it.limitMva.value.toFixed(1)} MVA</span>
                  </span>
                ) : (
                  <span className="text-text-muted">—</span>
                )}
              </td>
              <td className="px-2 py-1 whitespace-nowrap">
                {it.vm ? (
                  <span className="font-mono">
                    <Quantity of={it.vm} />
                    {it.vmLimit != null && <span className="text-text-muted"> / 限 {it.vmLimit} pu</span>}
                  </span>
                ) : (
                  <span className="text-text-muted">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {truncated && (
        <div className="bg-surface-sunken px-2 py-1 text-caption text-text-muted">
          共 {items.length} 条 · 以上为严重度前 {shown.length} 条（完整清单见原始工具结果）
        </div>
      )}
    </div>
  );
}
