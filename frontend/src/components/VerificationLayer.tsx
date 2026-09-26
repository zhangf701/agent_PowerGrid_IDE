/** VerificationLayer —— UI 规范 v2 §4.7.1。
 *
 *  ★ 为什么需要：v4 §4.3 **废除**了「契约状态先于图表渲染」。若契约面板仍常驻，
 *    「研究流程」就永远让位于「契约审计」—— 那是 v1–v3 的定位。
 *    但**能力一个不丢**：折叠的是**呈现层级**，不是能力。
 *
 *  ★★ 三条硬规则（缺一即违约）：
 *    ① **折叠 ≠ 隐藏**：`open=false` 时**顶部状态条仍必须渲染**，且含完整状态签名；
 *    ② **`incident` 未知态必须升至状态条** —— 把它降级为折叠面板里的次级标记，
 *       就是 P5 禁止的**静默 fail-open 的另一种形式**；
 *    ③ **`structural` 未知态不参与主徽标竞争** —— 它长期存在、无信息量，
 *       抢主徽章只会造成告警疲劳，让真正偶发的告警被淹没。
 *
 *  ★ 空集汇总 = `unknown`，**不是** `satisfied` —— 自然的 `reduce(…, 'satisfied')`
 *    会把「没检查」渲染成「检查过且正常」（假绿灯，违反 P5）。
 */
import type { ReactNode } from "react";

import type { ContractFinding } from "../api";
import { Signature, type SignatureKey } from "./Signature";

export interface ContractSummary {
  satisfied: number;
  degraded: number;
  violated: number;
  unknown: number;
}

/** 主徽标的竞争顺序 —— `unknown` **不在其中**（结构未知不参与，见硬规则 ③） */
const RANK: Record<string, number> = { satisfied: 1, degraded: 2, violated: 3, incident: 4 };

export function summarizeFindings(findings: ContractFinding[]): {
  summary: ContractSummary;
  /** 主徽标状态；**无任何可判定项时是 `unknown`**（空集 ≠ satisfied） */
  worst: SignatureKey;
  /** 事故性未知计数 —— 必须升到状态条（硬规则 ②） */
  incidentUnknown: number;
} {
  const summary: ContractSummary = { satisfied: 0, degraded: 0, violated: 0, unknown: 0 };
  let incidentUnknown = 0;
  const ranked: string[] = [];

  for (const f of findings) {
    if (f.state === "unknown") {
      summary.unknown += 1;
      if (f.reason === "incident") {
        incidentUnknown += 1;
        ranked.push("incident"); // ★ 事故参与主徽标竞争
      }
      // structural：计入 summary.unknown，但**不 push**（硬规则 ③）
    } else if (f.state in summary) {
      summary[f.state as keyof ContractSummary] += 1;
      ranked.push(f.state);
    }
  }

  // ★ 空集 / 只有结构未知 → `unknown`，不是 `satisfied`
  const worst: SignatureKey = ranked.length
    ? (ranked.reduce((a, b) => (RANK[b] > RANK[a] ? b : a)) as SignatureKey)
    : "unknown";

  return { summary, worst, incidentUnknown };
}

export function VerificationLayer({
  open,
  summary,
  worst,
  incidentUnknown,
  onToggle,
  disabled = false,
  onEnable,
  onDisable,
  children,
}: {
  open: boolean;
  summary: ContractSummary;
  worst: SignatureKey;
  incidentUnknown: number;
  onToggle: () => void;
  /** 用户**显式**整体关闭校验层 */
  disabled?: boolean;
  onEnable?: () => void;
  onDisable?: () => void;
  /** 展开后的详情（契约卡片列表等） */
  children?: ReactNode;
}) {
  if (disabled) {
    // 用户显式关闭 ≠ 系统静默隐藏：必须留下可恢复的入口与状态说明
    return (
      <div className="flex items-center gap-2 border-b border-border-subtle bg-surface-sunken px-4 py-1.5 text-caption text-text-muted">
        <span>校验层已关闭（用户选择）—— 契约状态当前不可见</span>
        {onEnable && (
          <button type="button" onClick={onEnable} className="underline">
            重新开启
          </button>
        )}
      </div>
    );
  }

  const structuralUnknown = summary.unknown - incidentUnknown;

  return (
    <div className="border-b border-border-subtle bg-surface-sunken">
      {/* ★ 硬规则 ①：状态条**常驻**，折叠时也在 */}
      <div className="flex flex-wrap items-center gap-3 px-4 py-1.5 text-caption">
        <Signature sig={worst} />
        <span className="text-text-secondary">
          ✔ {summary.satisfied} · ▲ {summary.degraded} · ✖ {summary.violated}
        </span>

        {/* ★ 硬规则 ③：结构未知是**次级标记**，不抢主徽章 */}
        {structuralUnknown > 0 && (
          <span className="text-text-muted" title="结构性未知：引擎级、常态、不升级">
            +?{structuralUnknown}
          </span>
        )}

        {/* ★ 硬规则 ②：事故性未知必须**升到状态条**，不得只藏在折叠里 */}
        {incidentUnknown > 0 && (
          <Signature
            sig="incident"
            text={`${incidentUnknown} 项事故`}
            title="本可判定却拿不到 —— 需要等重启 / 查网关"
          />
        )}

        <button type="button" onClick={onToggle} className="ml-auto underline">
          {open ? "收起 ▴" : "展开 ▾"}
        </button>
        {onDisable && (
          <button type="button" onClick={onDisable} className="underline">
            关闭校验层
          </button>
        )}
      </div>

      {open && <div className="max-h-72 overflow-auto px-4 pb-2">{children}</div>}
    </div>
  );
}
