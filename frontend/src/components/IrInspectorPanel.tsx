/** IrInspectorPanel —— ⑥ 校验层 · IR 检查器（方案 §5.4）。
 *
 *  ★ 能力范围（2026-09-28 张老师裁决：注释必须写明，与能力矩阵同口径）——
 *
 *  **做什么**：对**算例库**里选定的**一个算例**，检查 PowerIO IR 的解析质量：
 *    ① `GET /cases` 列出算例 → 用户下拉选一个 → `GET /cases/{id}/diagnostics` 现算诊断；
 *    ② 展示 `value_type`、诊断明细（按 severity 排序：错误→警告→备注→提示；
 *       每条含 code / target / message / 建议动作）、counts 摘要
 *       —— 空诊断如实显示网关 status 原文，**不渲染绿灯**（P5：没检查 ≠ 检查过且正常）；
 *    ③ `stale` 陈旧检测：源文件在解析之后又变过 → 结论来自旧数据 → 标「结果已陈旧」
 *       （unknown 签名，不是纯色）。
 *
 *  **不做什么**（§5.4 规划了但网关侧无数据源；现在做 = 对着不存在的数据定型）：
 *    selection 树形展开（IR 全文 ~52 KB 交互树）、fidelity 徽章、edits 编辑轨迹时间线。
 *
 *  **错误路径**：未解析的算例点诊断 → 网关 409 —— 错误原样显示（detail 里带可执行指引），不吞。
 */
import { useCallback, useEffect, useState } from "react";

import {
  CaseDiagnosticsSchema,
  CasesResponseSchema,
  SchemaDriftError,
  apiParsed,
  type CaseDiagnostics,
  type CasesResponse,
} from "../api";
import { Signature } from "./Signature";

/** severity 排序权重 —— error 最先（§5.4：按 severity 排序）。 */
const SEVERITY_RANK: Record<string, number> = { error: 0, warning: 1, remark: 2, note: 3 };
const SEVERITY_LABEL: Record<string, string> = {
  error: "错误",
  warning: "警告",
  remark: "备注",
  note: "提示",
};

function sortedDiagnostics(d: CaseDiagnostics) {
  return [...d.result.diagnostics].sort(
    (a, b) =>
      (SEVERITY_RANK[a.severity] ?? 99) - (SEVERITY_RANK[b.severity] ?? 99) ||
      a.code.localeCompare(b.code),
  );
}

export function IrInspectorPanel() {
  const [cases, setCases] = useState<CasesResponse | null>(null);
  const [caseId, setCaseId] = useState<string>("");
  const [diag, setDiag] = useState<CaseDiagnostics | null>(null);
  const [error, setError] = useState<{ message: string; incident: boolean } | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const c = await apiParsed("/cases", CasesResponseSchema);
        if (!alive) return;
        setCases(c);
        setError(null);
      } catch (err) {
        if (!alive) return;
        setError({ message: (err as Error).message, incident: err instanceof SchemaDriftError });
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const runDiagnostics = useCallback(async (id: string) => {
    if (!id) return;
    setLoading(true);
    setDiag(null);
    try {
      const d = await apiParsed(`/cases/${id}/diagnostics`, CaseDiagnosticsSchema);
      setDiag(d);
      setError(null);
    } catch (err) {
      setError({ message: (err as Error).message, incident: err instanceof SchemaDriftError });
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div data-testid="ir-inspector">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="选择算例"
          value={caseId}
          onChange={(e) => setCaseId(e.target.value)}
          className="rounded-sm border border-border-subtle bg-surface-raised px-2 py-1 text-bodySm"
        >
          <option value="">— 选择算例 —</option>
          {cases?.cases.map((c) => (
            <option key={c.id} value={c.id}>
              {c.label}（{c.id}）
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={!caseId || loading}
          onClick={() => void runDiagnostics(caseId)}
          className="rounded-sm border border-border-subtle px-2 py-1 text-bodySm hover:bg-interactive-subtle disabled:opacity-50"
        >
          {loading ? "诊断中…" : "跑诊断"}
        </button>
      </div>

      {error && (
        <div className="mt-2 text-bodySm">
          <span className={error.incident ? "text-contract-incident-fg" : "text-contract-violated-fg"}>
            {error.incident ? "! 事故" : "✖ 失败"}
          </span>{" "}
          {error.message}
        </div>
      )}

      {diag && (
        <div className="mt-2 text-bodySm">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="font-mono">{diag.value_type ?? "?"}</span>
            {diag.stale && (
              <span title="源文件在解析后又变过 —— 诊断结论来自旧数据，请重新解析">
                <SignatureUnknownStale />
              </span>
            )}
            <span className="text-caption text-text-muted">
              解析于 {diag.parsed_at ?? "?"}
            </span>
          </div>

          {/* counts 摘要 —— 空诊断 ≠ 「没问题也显示绿 ✔」：如实写 status 原文 */}
          <div className="mt-1 text-text-secondary">
            {diag.result.summary.text}
            {"（"}
            错误 {diag.result.summary.counts.error} · 警告 {diag.result.summary.counts.warning} ·
            备注 {diag.result.summary.counts.remark} · 提示 {diag.result.summary.counts.note}
            {"）"}
          </div>

          {sortedDiagnostics(diag).map((it, i) => (
            <div
              key={i}
              data-testid="ir-diagnostic"
              className="mt-1.5 rounded-md border border-border-subtle bg-surface-raised px-3 py-2"
            >
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="font-medium">{SEVERITY_LABEL[it.severity] ?? it.severity}</span>
                <span className="font-mono text-caption">{it.code}</span>
                <span className="font-mono text-caption text-text-muted">{it.target}</span>
              </div>
              <div className="mt-1 text-text-secondary">{it.message}</div>
              {it.suggested_action && (
                <div className="mt-1 text-text-secondary">
                  <span className="text-text-muted">建议：</span>
                  {it.suggested_action}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="mt-2 text-caption text-text-muted">
        本面板当前覆盖 value_type / 诊断 / 陈旧标记；selection 树、fidelity 徽章与 edits
        时间线需要网关侧数据源，尚未实现（如实标注，不假装）。
      </div>
    </div>
  );
}

/** 陈旧标记 —— 用 unknown 签名（? + 文字），不用纯色（P2）。 */
function SignatureUnknownStale() {
  return <Signature sig="unknown" text="结果已陈旧" title="源文件在解析后又被修改 —— 请重新解析" />;
}
