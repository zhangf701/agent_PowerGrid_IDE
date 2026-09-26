/** ResultSummary —— 结构化结果呈现（§4.3「结果呈现」）。
 *
 *  ★ 为什么需要（F-4 实测）：对话里的数值与编号此前**只是模型的自述**，
 *    而模型会把**数组位置当成母线编号**（报「最低电压 0.943 pu @ 母线 78」，
 *    而直接读数组是 `bus_numbers[75] = 76`），且**语气确定**；
 *    只有在被提示"注意编号约定"时才做对 ⇒ **不可靠，且提示词治不了**。
 *
 *  ⇒ 数值与标识符改由**代码**从工具结果里取出，经 `Quantity`（强制单位 + 判据）
 *    与 `Identifier`（强制编号约定）渲染 —— 这是 §4.3 的明文要求。
 *
 *  ⚠️ **诚实边界**：本组件**不阻止**模型继续在正文里写错。它与模型自述**并列呈现**，
 *    标题已明确「由工具结果直接计算，非模型转述」，以便读者知道以哪个为准。
 */
import { Identifier, type Convention } from "./Identifier";
import { Quantity, type Measured } from "./Quantity";

/** 标识符项：`id` + **必须标注**的编号约定 */
export interface ResultId {
  id: number | string;
  convention: Convention;
  kind?: string;
}

export interface ResultItem {
  label: string;
  /** 数值 —— 只能由 `measure()` 构造，由 `Quantity` 渲染（单位与判据强制） */
  value?: Measured;
  /** 标识符 —— 由 `Identifier` 渲染（编号约定强制标注） */
  ref?: ResultId;
  /** 纯文本（计数 / 是-否 / 元件描述）—— **不含单位与编号**，故不走组件 */
  text?: string;
}

export function ResultSummary({ items }: { items: ResultItem[] }) {
  if (!items.length) return null;
  return (
    <div
      data-testid="result-summary"
      className="mt-1 rounded-sm border border-border-subtle px-2 py-1 text-caption"
    >
      <div className="text-text-muted">
        结构化结果（由工具结果直接计算，**非**模型转述）
      </div>
      {items.map((it, i) => (
        <div key={i} className="flex flex-wrap items-baseline gap-2">
          <span className="w-32 flex-none text-text-secondary">{it.label}</span>
          {it.value && <Quantity of={it.value} />}
          {it.ref && <Identifier id={it.ref.id} convention={it.ref.convention} kind={it.ref.kind} />}
          {it.text && <span>{it.text}</span>}
        </div>
      ))}
    </div>
  );
}
