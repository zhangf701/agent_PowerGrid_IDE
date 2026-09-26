/** ContractCard —— UI 规范 v2 §4.2。
 *
 *  ★ 徽章（§4.1）是**紧凑标注**；需要长文本说明时用本卡片。
 *  ★ `reason` 在 `state === 'unknown'` 时**必填** —— 与徽章同一条约束（§3.8.2）。
 *  ★ `evidence` 是**证据**（工具名 / 参数 / 校验方式），默认折叠 ——
 *    它面向"要下钻的人"，不该挤占"只看结论的人"的视野。
 */
import type { ContractFinding } from "../api";
import { ContractBadge, CONTRACT_NAMES, type ContractState, type UnknownReason } from "./ContractBadge";

export function ContractCard({ finding }: { finding: ContractFinding }) {
  const state = finding.state as ContractState;
  const reason = (finding.reason ?? undefined) as UnknownReason | undefined;
  const evidence = finding.evidence ?? {};
  const hasEvidence = Object.keys(evidence).length > 0;

  return (
    <div
      data-testid="contract-card"
      className="mb-1.5 rounded-md border border-border-subtle bg-surface-raised px-3 py-2"
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <ContractBadge state={state} reason={reason} contractType={finding.contract} />
        <span className="font-mono text-bodySm">{finding.subject}</span>
        <span className="ml-auto text-caption text-text-muted">
          {CONTRACT_NAMES[finding.contract] ?? ""}
        </span>
      </div>

      {/* ★ detail 是给人看的那句话 —— 不省略、不改写 */}
      <div className="mt-1 text-bodySm text-text-secondary">{finding.detail}</div>

      {hasEvidence && (
        <details className="mt-1">
          <summary className="cursor-pointer text-caption text-text-muted">证据</summary>
          <pre className="mt-1 overflow-auto whitespace-pre-wrap break-all rounded-sm bg-code-bg p-2 text-caption text-code-fg">
            {JSON.stringify(evidence, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}
