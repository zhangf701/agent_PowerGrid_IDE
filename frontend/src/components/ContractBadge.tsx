/** ContractBadge —— UI 规范 v2 §4.1。
 *
 *  ★ 它是整个界面里**契约语义的最小载体**，出现在聊天内联、审计行、契约卡片、导出报告中。
 *    方案 §三 要求五个视图**共享同一组件库** —— 「同一个契约徽章在聊天内联、契约面板、
 *    导出报告中渲染完全一致」。各自实现会让同一条契约在不同位置图标或措辞不同。
 *
 *  ★ 关键约束：
 *    - **标签在任何尺寸下都不可省** —— `size="sm"` 只缩小字号与内边距，
 *      **不隐藏文字**（隐藏文字即违反 P2「颜色不得单独承载信息」）；
 *    - `state === 'unknown'` 时 `reason` **必填** —— 它决定渲染 `? 未知` 还是 `! 事故`（§3.8.2）；
 *    - 未知两分的用户动作完全不同：**结构未知**要「绕开该能力」，**事故**要「等重启 / 查网关」。
 */
import { Signature, signatureOf, type SignatureKey } from "./Signature";

/** 契约状态四值（不含 null / undefined） */
export type ContractState = "satisfied" | "degraded" | "violated" | "unknown";
/** 未知的两分 —— 决定它是否升级为主徽章 */
export type UnknownReason = "structural" | "incident";

/** 契约编号 → 名称（与后端 `contracts/CONTRACT_NAMES` 同源语义，仅用于展示） */
export const CONTRACT_NAMES: Record<number, string> = {
  1: "接口存在",
  2: "能力可核",
  3: "参数可验",
  4: "状态可读",
  5: "命名可辨",
  6: "单位可归",
  7: "量纲契约",
  8: "运行时依赖契约",
};

/** `ContractState` + `reason` → 渲染签名键（唯一的分叉点） */
export function signatureKeyOf(state: ContractState, reason?: UnknownReason | null): SignatureKey {
  if (state !== "unknown") return state;
  return reason === "incident" ? "incident" : "unknown";
}

export function ContractBadge({
  state,
  reason,
  contractType,
  size = "md",
  title,
}: {
  state: ContractState;
  /** ★ `state === 'unknown'` 时**必填** */
  reason?: UnknownReason | null;
  contractType?: number;
  size?: "sm" | "md";
  title?: string;
}) {
  if (state === "unknown" && !reason) {
    // 未知态不给成因 → 无法决定渲染「未知」还是「事故」，那是静默 fail-open 的温床
    throw new Error(
      "ContractBadge: state='unknown' 时必须给出 reason（structural / incident）—— 见 §4.1 / §3.8.2",
    );
  }

  const sig = signatureKeyOf(state, reason);
  // ★ 传入契约编号时显示「契约 N · 标签」——**任何尺寸下标签都不可省**（§4.1）
  const text = contractType ? `契约 ${contractType} · ${signatureOf(sig).label}` : undefined;

  return (
    <span className={size === "sm" ? "text-caption" : undefined}>
      <Signature sig={sig} text={text} title={title ?? (contractType ? CONTRACT_NAMES[contractType] : undefined)} />
    </span>
  );
}
