import { useCallback, useEffect, useState } from "react";

import {
  V2CommitResponseSchema,
  V2ProposalDeleteResponseSchema,
  V2ProposalResponseSchema,
  V2ProposalsListSchema,
  apiParsed,
  type Case,
  type V2ProposalResponse,
  type V2ProposalSummary,
} from "../api";
import { Button } from "./Button";
import { EmptyState } from "./states";

/** 新建提案表单的**中性**模板 —— 不含任何引擎/模块专属内容（界面不替用户声称能力）。 */
const DEFAULT_STEPS = JSON.stringify(
  [{ server: "<server>", tool: "<tool>", args_template: {} }],
  null,
  2,
);

export function ExperimentProposalCard({
  cases,
  onCommitted,
  onError,
}: {
  cases: Case[];
  /** `reused=true` 表示**同一提案**重复提交（同一实验，幂等复用，不重复建） */
  onCommitted: (eid: string, reused: boolean) => void;
  onError: (error: unknown) => void;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("研究实验提案");
  const [question, setQuestion] = useState("");
  const [hypothesis, setHypothesis] = useState("");
  const [selectedCases, setSelectedCases] = useState<string[]>([]);
  const [steps, setSteps] = useState(DEFAULT_STEPS);
  const [factors, setFactors] = useState("[]");
  const [proposal, setProposal] = useState<V2ProposalResponse | null>(null);
  const [busy, setBusy] = useState(false);
  /** ★ 已有提案清单 —— 没有它，「一次只能看到一个提案」就成了系统的硬限制。 */
  const [items, setItems] = useState<V2ProposalSummary[]>([]);

  const load = useCallback(async () => {
    try {
      const response = await apiParsed("/experiment-proposals", V2ProposalsListSchema);
      setItems(response.proposals);
    } catch (error) {
      onError(error);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  /** ★ commit 后把表单**重置**，否则再点「生成并校验」会因内容未变而命中同一个提案
   *  （`proposal_id = H(payload)`），用户会以为「建不出新的」。 */
  function resetForm() {
    setTitle("研究实验提案");
    setQuestion("");
    setHypothesis("");
    setSelectedCases([]);
    setSteps(DEFAULT_STEPS);
    setFactors("[]");
    setProposal(null);
  }

  async function propose() {
    if (!selectedCases.length || !question.trim() || !hypothesis.trim()) return;
    let parsedSteps: unknown;
    let parsedFactors: unknown;
    try {
      parsedSteps = JSON.parse(steps);
      parsedFactors = JSON.parse(factors || "[]");
    } catch (error) {
      onError(error);
      return;
    }
    setBusy(true);
    try {
      const response = await apiParsed("/experiment-proposals", V2ProposalResponseSchema, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title,
          research_question: { id: "rq-ui", statement: question },
          hypothesis: { id: "hyp-ui", statement: hypothesis },
          design: { cases: selectedCases, factors: parsedFactors },
          execution: { steps: parsedSteps },
          observables: { metrics: [] },
          analysis: { methods: ["summary", "extreme_cases", "boundary_cases"] },
          origin: { source: "ui" },
        }),
      });
      setProposal(response);
      await load();
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }

  async function commitOne(proposalId: string) {
    setBusy(true);
    try {
      const response = await apiParsed(
        `/experiment-proposals/${proposalId}/commit`,
        V2CommitResponseSchema,
        { method: "POST" },
      );
      onCommitted(response.experiment.eid, response.reused === true);
      resetForm();
      await load();
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }

  async function removeOne(proposalId: string) {
    setBusy(true);
    try {
      await apiParsed(`/experiment-proposals/${proposalId}`, V2ProposalDeleteResponseSchema, {
        method: "DELETE",
      });
      await load();
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 rounded-md border border-border-subtle p-3">
      <div className="flex items-center gap-2">
        <strong className="text-bodySm">研究实验提案（V2）</strong>
        <span className="text-caption text-text-muted">Agent 可探索，commit 后定义不可变</span>
        <Button onClick={() => setOpen((value) => !value)}>{open ? "收起" : "新建提案"}</Button>
      </div>

      {open && (
        <div className="mt-2 space-y-2">
          <label className="block text-bodySm">
            标题
            <input
              aria-label="提案标题"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="mt-1 w-full rounded-sm border border-border-subtle bg-surface-sunken px-2 py-1"
            />
          </label>
          <label className="block text-bodySm">
            研究问题
            <textarea
              aria-label="研究问题"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              rows={2}
              className="mt-1 w-full rounded-sm border border-border-subtle bg-surface-sunken p-2"
            />
          </label>
          <label className="block text-bodySm">
            假设
            <textarea
              aria-label="假设"
              value={hypothesis}
              onChange={(event) => setHypothesis(event.target.value)}
              rows={2}
              className="mt-1 w-full rounded-sm border border-border-subtle bg-surface-sunken p-2"
            />
          </label>
          <div className="text-bodySm">算例</div>
          {cases.length ? (
            <div className="max-h-24 overflow-auto rounded-sm border border-border-subtle p-1">
              {cases.map((item) => (
                <label key={item.id} className="flex items-center gap-2 px-1 py-0.5 text-caption">
                  <input
                    type="checkbox"
                    checked={selectedCases.includes(item.id)}
                    onChange={(event) =>
                      setSelectedCases((previous) =>
                        event.target.checked
                          ? [...previous, item.id]
                          : previous.filter((value) => value !== item.id),
                      )
                    }
                  />
                  <span>{item.label}</span>
                  <span className="font-mono text-text-muted">{item.id}</span>
                </label>
              ))}
            </div>
          ) : (
            <EmptyState>请先登记算例。</EmptyState>
          )}
          <label className="block text-bodySm">
            执行步骤（JSON）
            <textarea
              aria-label="提案执行步骤"
              value={steps}
              onChange={(event) => setSteps(event.target.value)}
              rows={5}
              className="mt-1 w-full rounded-sm border border-border-subtle bg-surface-sunken p-2 font-mono text-caption"
            />
          </label>
          <label className="block text-bodySm">
            因子（JSON）
            <textarea
              aria-label="提案因子"
              value={factors}
              onChange={(event) => setFactors(event.target.value)}
              rows={2}
              className="mt-1 w-full rounded-sm border border-border-subtle bg-surface-sunken p-2 font-mono text-caption"
            />
          </label>
          <div className="flex items-center gap-2">
            <Button onClick={() => void propose()} disabled={busy || !selectedCases.length}>
              {busy ? "校验中…" : "生成并校验提案"}
            </Button>
            <Button onClick={resetForm} disabled={busy}>
              清空表单
            </Button>
          </div>
          {proposal && (
            <div className="rounded-sm border border-border-subtle bg-surface-sunken p-2 text-caption">
              <div>
                提案 <code>{proposal.proposal.proposal_id}</code> · 网格 {proposal.preview.cell_count} 格
              </div>
              <div className="mt-1">
                校验：<strong>{proposal.validation.valid ? "通过" : "未通过"}</strong>
                {proposal.validation.warnings.map((warning) => (
                  <div key={warning} className="text-text-muted">警告：{warning}</div>
                ))}
              </div>
              {proposal.validation.valid && (
                <Button
                  onClick={() => void commitOne(proposal.proposal.proposal_id)}
                  disabled={busy}
                >
                  {busy ? "提交中…" : "Review 后 Commit（冻结定义）"}
                </Button>
              )}
            </div>
          )}
        </div>
      )}

      {/* ★ 已有提案清单：可累积多个、逐个提交 / 删除 —— 提案不再"一次只能有一个" */}
      {items.length > 0 && (
        <div className="mt-3">
          <div className="text-bodySm font-medium">已有提案（{items.length}）</div>
          <div className="mt-1 space-y-1">
            {items.map((item) => (
              <div
                key={item.proposal_id}
                className="flex flex-wrap items-center gap-2 rounded-sm border border-border-subtle px-2 py-1 text-caption"
              >
                <span className="font-medium">{item.title}</span>
                <code className="font-mono text-text-muted">{item.proposal_id}</code>
                <span className="text-text-muted">{item.step_count} 步</span>
                {item.committed_eid ? (
                  <span className="text-text-secondary">
                    已 commit → <code className="font-mono">{item.committed_eid}</code>
                  </span>
                ) : (
                  <Button
                    onClick={() => void commitOne(item.proposal_id)}
                    disabled={busy}
                    aria-label={`提交提案 ${item.proposal_id}`}
                  >
                    提交
                  </Button>
                )}
                <Button
                  onClick={() => void removeOne(item.proposal_id)}
                  disabled={busy}
                  aria-label={`删除提案 ${item.proposal_id}`}
                >
                  删除
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
