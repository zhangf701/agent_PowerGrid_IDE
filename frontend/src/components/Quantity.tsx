/** Quantity —— UI 规范 v2 §4.4。
 *
 *  ★ 为什么需要（实测缺陷）：过载判据用 MW 而非 MVA，会把 `142.47%` 看成 `98.16%`，
 *    进而**误判为正常**。故「数值必须与单位同时出现」被做成**类型约束**：裸数值写不出来。
 *
 *  ★ 修法的关键：数值由**数据适配层**构造（`measure()` 是唯一入口），组件只渲染。
 *    判别联合挡得住「忘写判据」，但挡不住「判据写错」——
 *    `<Quantity value={98.16} unit="%" criterion="MW" />` 编译通过，且渲染成
 *    「98.16% (MW 判据)」，**比裸值更可信**。把判据从 N 个渲染点收敛到 1 个适配点，
 *    才能变成一处可审计、可加运行时校验、可写单测的地方。
 *
 *  ⚠️ **必须如实说明的边界**：类型系统**仍不能验证判据是否正确**。它只保证判据来自一个
 *    显式声明且集中的来源。本组件**不宣称「判据错误不可表达」**。
 *
 *  ❌ 规范 v1.0 草案的 `state` 属性已删除：它只做着色、没有图标与标签（正是 P2 禁止的
 *    「颜色单独承载信息」）；且 `142%` 超载是**物理越限**，不是**契约违反**，不该共用
 *    `ContractState`。需要同时表达契约状态时，在 `Quantity` **旁边**挂 `<ContractBadge>`。
 */
import type { ReactNode } from "react";

/** 有量纲单位。`%` 单列，因为它脱离判据无意义。 */
export type Unit = "MW" | "MVA" | "MVar" | "kV" | "A" | "pu" | "MW·h" | "%";

/** 判据 —— 关于数值**物理来源**的断言，不是展示属性。 */
export type Criterion = "MVA" | "MW" | "pu";

/** 单位与判据的约束：有量纲时单位即判据；比值型必须给判据。 */
export type UnitSpec =
  | { readonly unit: Exclude<Unit, "%">; readonly criterion?: never }
  | { readonly unit: "%"; readonly criterion: Criterion };

/** 运行时品牌 —— 使 `Measured` **无法用对象字面量伪造**。 */
const MEASURED: unique symbol = Symbol("powermcp.measured");

/** 已测得的数值对象。**只能由 `measure()` 构造**。 */
export type Measured = UnitSpec & {
  readonly value: number;
  /** 回到产生它的那次工具调用（CallId）—— 「证据可下钻」的落点 */
  readonly source: string;
  readonly [MEASURED]: true;
};

export class MeasureError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MeasureError";
  }
}

/** ★ 唯一构造入口 —— 只在数据适配层调用（工具结果 / SSE 事件 → 可渲染对象）。 */
export function measure(raw: unknown, spec: UnitSpec, source: string): Measured {
  if (spec.unit === "%" && !(spec as { criterion?: Criterion }).criterion) {
    throw new MeasureError(
      "比值型数值（%）必须给出判据 criterion —— 脱离判据的百分比无意义（`%` 无判据即落 unknown）",
    );
  }
  if (typeof raw !== "number" || !Number.isFinite(raw)) {
    throw new MeasureError(
      `measure() 只接受有限数值，收到 ${raw === null ? "null" : typeof raw}：${String(raw)}`,
    );
  }
  return Object.freeze({ ...spec, value: raw, source, [MEASURED]: true }) as Measured;
}

/** 等宽 —— §3.3.1 要求数值与单位均为等宽。
 *  ★ 用 Tailwind 的 `font-mono`（走 `tailwindTheme.fontFamily.mono` → `var(--p-font-mono)`）。
 *    2026-09-26 之前这里只能写内联 `style`：生成的 `fontFamily` 令牌是坏的
 *    （`tools/build_design_tokens.py` 前缀过度匹配 + 二次 `var()` 包裹），`font-mono` 会
 *    产出无效 CSS 被浏览器丢弃。**F-2 已修**，故改回令牌类。 */
const MONO = "font-mono";

function formatNumber(v: number, precision?: number): string {
  if (precision != null) return v.toFixed(precision);
  if (v === 0) return "0";
  // 6 位有效数字：142.47→"142.47" · 958.49→"958.49" · 0.982→"0.982" · 6.98e-11→"6.98e-11"
  return String(Number(v.toPrecision(6)));
}

export function Quantity({
  of,
  precision,
  /** 渲染为 `Δ = ...` 形式 */
  delta = false,
  /** **物理越限**（非契约）—— 必须渲染文字标签，不得只改颜色 */
  alarm,
}: {
  of: Measured;
  precision?: number;
  delta?: boolean;
  alarm?: { level: "warn" | "over" };
}): ReactNode {
  const num = formatNumber(of.value, precision);
  const unit = of.unit === "%" ? "%" : ` ${of.unit}`;
  const criterion =
    of.unit === "%" && of.criterion ? ` (${of.criterion} 判据)` : "";

  return (
    <span className="whitespace-nowrap" title={`来源：${of.source}`}>
      <span className={MONO}>
        {delta ? "Δ = " : ""}
        {num}
        {unit}
      </span>
      {criterion && <span className="text-text-muted">{criterion}</span>}
      {alarm && (
        <span
          className={`ml-1 ${
            alarm.level === "over" ? "text-contract-violated-fg" : "text-contract-degraded-fg"
          }`}
        >
          {alarm.level === "over" ? "超限" : "接近限值"}
        </span>
      )}
    </span>
  );
}
