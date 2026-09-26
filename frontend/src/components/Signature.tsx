/** 状态签名 —— UI 规范 v2 §3.8.1。
 *
 *  ★ 「色 + 图标 + 标签」**三元绑定，不拆分**。本组件只收 `sig`（签名键），
 *    不提供 `getContractColor(state)` 之类的 API —— 一旦提供，就会有人只用颜色
 *    （规范 P2/P3 在实现层的强制手段）。
 *  ★ 图标字符 `✔ ▲ ✖ ? !` 五者在**形状**上互不相似：去掉颜色、缩到 12px 仍可区分。
 *    用 `✔ ⚠ ✖` 这类同族符号，灰度打印下会退化成三个相似方块。
 *  ★ `unknown` 与 `incident` 是**同一数据状态（unknown）的两种成因**，不是两个并列状态：
 *    - `unknown`（structural）：引擎级、常态、**不升级** → 标签「未知」
 *    - `incident`（事故性）：本可判定却拿不到 → 标签「事故」，**必须升级**
 *    视觉必须可区分，因为两者的用户动作完全不同（绕开能力 vs 等重启/查网关）。
 */

/** 三种「有判定」的状态 */
export type KnownState = "satisfied" | "degraded" | "violated";

/** 渲染签名键 —— 与 ContractState 的唯一区别是 unknown 按成因分叉 */
export type SignatureKey = KnownState | "unknown" | "incident";

export interface StateSignature {
  readonly key: SignatureKey;
  /** ✔ ▲ ✖ ? ! */
  readonly icon: string;
  /** 满足 / 降级 / 违反 / 未知 / 事故 */
  readonly label: string;
}

/** ★ 签名是**整体** —— 颜色三元组只在这里出现，调用方拿不到单独的颜色 */
const SIGNATURES: Record<SignatureKey, StateSignature & { cls: string }> = {
  satisfied: {
    key: "satisfied",
    icon: "✔",
    label: "满足",
    cls: "bg-contract-satisfied-bg border-contract-satisfied-border text-contract-satisfied-fg",
  },
  degraded: {
    key: "degraded",
    icon: "▲",
    label: "降级",
    cls: "bg-contract-degraded-bg border-contract-degraded-border text-contract-degraded-fg",
  },
  violated: {
    key: "violated",
    icon: "✖",
    label: "违反",
    cls: "bg-contract-violated-bg border-contract-violated-border text-contract-violated-fg",
  },
  unknown: {
    key: "unknown",
    icon: "?",
    label: "未知",
    cls: "bg-contract-unknown-bg border-contract-unknown-border text-contract-unknown-fg",
  },
  incident: {
    key: "incident",
    icon: "!",
    label: "事故",
    cls: "bg-contract-incident-bg border-contract-incident-border text-contract-incident-fg",
  },
};

/** 只读地暴露签名定义（供测试与汇总层取图标/标签，**不含颜色**）。 */
export function signatureOf(key: SignatureKey): StateSignature {
  const { key: k, icon, label } = SIGNATURES[key];
  return { key: k, icon, label };
}

export function Signature({
  sig,
  /** 覆盖默认标签（如技能 kind 徽标用中文名）。缺省用签名自身的标签。 */
  text,
  /** 悬浮说明 —— 承载「为什么是未知」这类上下文 */
  title,
}: {
  sig: SignatureKey;
  text?: string;
  title?: string;
}) {
  const s = SIGNATURES[sig];
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 text-caption font-medium ${s.cls}`}
    >
      {/* ★ 图标 + 文字同时存在 —— 颜色不得单独承载信息（P2） */}
      <span aria-hidden>{s.icon}</span>
      <span>{text ?? s.label}</span>
    </span>
  );
}
