/** ExperimentGrid —— 实验矩阵格（UI 规范 v2 §4.7.5，P2）。
 *
 *  ★ 规范原文只固定了三条约束，本组件**逐条**落实（每条都在代码里能指出落点）：
 *
 *  1. **进度必须可观测，且失败必须逐格可见**（不得只给一个总进度条）
 *     → 每格一行、行内自带状态签名；`failed` 的格子**在行内**列出失败的步骤与引擎错误，
 *       而不是把失败折叠进一个"N/M 完成"的计数器里。总计数只是**补充**，不是唯一信息。
 *
 *  2. **结果必须绑定 `cache_key`**，陈旧结果须标注「来自旧契约状态」
 *     → 每行显式显示 `cache_key`；`never_run` 表示「当前 `cache_key` 没有存档结果」；
 *       存档里对不上任何当前格子的记录由 `orphaned` 单独标注为**来自旧条件**，
 *       不与当前结果并列（否则新旧混排 = 静默错配）。
 *
 *  3. **执行模型为串行优先**（v4 §4.4 已裁决）
 *     → 界面不做任何并发暗示（无「并行度」控件、无并发进度），并如实写明串行。
 *
 *  ★ 颜色不单独承载信息：状态一律走 `Signature`（图标 + 文字 + 颜色三元绑定）。
 */
import { Signature, type SignatureKey } from "./Signature";

/** 一格要跑的一步（定义层：只有 server/tool）。 */
export type GridPlannedStep = { server: string; tool: string };

/** 一格的一步执行记录（执行后才有 `ok` / `error` / `remounted`）。 */
export type GridStep = GridPlannedStep & {
  ok?: boolean;
  error?: string | null;
  remounted?: boolean;
};

/** 组件输入 —— 由调用方从**定义端点**或**执行端点**归一化而来。 */
export type GridCell = {
  index: number;
  caseId: string;
  bindings: Record<string, unknown>;
  cacheKey: string;
  /** `pending`（定义层）| `ok` | `failed` | `never_run`（无存档结果） */
  status: string;
  /** 未执行时展示「将要跑什么」 */
  planned?: GridPlannedStep[];
  /** 执行记录（跑过才有） */
  steps?: GridStep[];
  ranAt?: string | null;
  /** 结果表指标（键带 `metric.` 前缀） */
  metrics?: Record<string, unknown>;
  /** ★ 该格**不在当前定义里**（定义改过，执行/结果记录属于旧条件）——
   *  必须显式标出，否则"跑完却看不到结果"或"新旧混排"都是静默错配。 */
  definitionChanged?: boolean;
};

/** 格子状态 → 状态签名 + 中文标签（**未知状态不得静默当作正常**）。 */
const CELL_SIG: Record<string, { sig: SignatureKey; label: string }> = {
  ok: { sig: "satisfied", label: "成功" },
  completed: { sig: "satisfied", label: "完成" },
  failed: { sig: "violated", label: "失败" },
  failed_environment: { sig: "degraded", label: "环境失败" },
  failed_execution: { sig: "violated", label: "执行失败" },
  failed_validation: { sig: "violated", label: "校验失败" },
  not_converged: { sig: "degraded", label: "未收敛" },
  cancelled: { sig: "unknown", label: "已取消" },
  pending: { sig: "unknown", label: "待跑" },
  never_run: { sig: "unknown", label: "未跑" },
};

/** 未在映射里的状态：原样显示 + 用 `unknown` 签名（不猜、不静默当成功）。 */
export function cellSignature(status: string): { sig: SignatureKey; label: string } {
  return CELL_SIG[status] ?? { sig: "unknown", label: status };
}

/** 行内展示的指标条数上限（完整指标在结果表里；这里只给"一眼可见"的几个）。 */
export const INLINE_METRIC_LIMIT = 4;

function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Number(v.toFixed(6)));
  return String(v);
}

/** 因子绑定 → `name=value`（按名字排序，保证同一实验的行序稳定可读）。 */
export function bindingText(bindings: Record<string, unknown>): string {
  const keys = Object.keys(bindings).sort();
  if (!keys.length) return "—";
  return keys.map((k) => `${k}=${fmtValue(bindings[k])}`).join(" · ");
}

/** 从执行记录里挑出**第一个失败的步骤**（失败逐格可见的载体）。 */
export function firstFailure(steps?: GridStep[]): GridStep | null {
  if (!steps) return null;
  return steps.find((s) => s.ok === false) ?? null;
}

/** 行内指标的展示顺序：**数值优先**（跨格可比较的量），布尔次之，文本垫底。
 *
 *  ★ 为什么不是纯字典序：指标里混着 `metric.message`（长文案）与
 *    `metric.results.n_contingencies`（可比数值）。纯字典序会让长文案霸占行内
 *    有限的展示位，把真正能横向比较的数字挤掉。同类内部仍按名排序（顺序稳定）。 */
export function orderMetricKeys(metrics: Record<string, unknown>): string[] {
  const rank = (v: unknown): number => {
    if (typeof v === "number") return 0;
    if (typeof v === "boolean") return 1;
    return 2;
  };
  return Object.keys(metrics).sort((a, b) => {
    const d = rank(metrics[a]) - rank(metrics[b]);
    return d !== 0 ? d : a.localeCompare(b);
  });
}

export function ExperimentGrid({
  cells,
  orphaned = 0,
  onSelect,
  selectedIndex,
}: {
  cells: GridCell[];
  /** 存档里对不上任何当前格子的记录数（陈旧结果） */
  orphaned?: number;
  onSelect?: (index: number) => void;
  selectedIndex?: number | null;
}) {
  if (!cells.length) return null;

  const counts: Record<string, number> = {};
  for (const c of cells) counts[c.status] = (counts[c.status] ?? 0) + 1;
  const order = [
    "ok", "completed", "failed", "failed_environment", "failed_execution",
    "failed_validation", "not_converged", "cancelled", "pending", "never_run",
  ];

  return (
    <div data-testid="experiment-grid">
      {/* ★ 总计数是**补充**：下面每格自带状态，失败行内可见 */}
      <div className="mb-1 flex flex-wrap items-center gap-2 text-bodySm text-text-secondary">
        <span>
          共 <strong>{cells.length}</strong> 格
        </span>
        {order
          .filter((k) => counts[k])
          .map((k) => {
            const s = cellSignature(k);
            return (
              <span key={k} className="inline-flex items-center gap-1">
                <Signature sig={s.sig} text={`${s.label} ${counts[k]}`} />
              </span>
            );
          })}
        <span className="text-text-muted">· 串行执行（不并发）</span>
      </div>

      {/* ★ 约束 2：陈旧结果必须显式标注「来自旧条件」，不与当前结果并列 */}
      {orphaned > 0 && (
        <div className="mb-1 flex items-center gap-2 text-bodySm">
          <Signature
            sig="degraded"
            text={`${orphaned} 条陈旧结果`}
            title="这些结果的 cache_key 已不对应任何当前格子（算例或模板改过），属于旧条件"
          />
          <span className="text-text-secondary">
            存档里有 <strong>{orphaned}</strong> 条结果<strong>来自旧条件</strong>
            （算例或步骤模板改过 → 格子算出新 <code>cache_key</code>）——
            它们不与当前结果并列，需要时请重跑。
          </span>
        </div>
      )}

      <div className="overflow-x-auto rounded-sm border border-border-subtle">
        <table className="w-full border-collapse text-caption">
          <thead>
            <tr className="border-b border-border-subtle bg-surface-sunken text-left text-text-muted">
              <th className="px-2 py-1 font-normal">格</th>
              <th className="px-2 py-1 font-normal">算例 / 因子</th>
              <th className="px-2 py-1 font-normal">状态</th>
              <th className="px-2 py-1 font-normal">步骤 / 结果</th>
              <th className="px-2 py-1 font-normal">cache_key</th>
            </tr>
          </thead>
          <tbody>
            {cells.map((c, rowIdx) => {
              const s = cellSignature(c.status);
              const failure = firstFailure(c.steps);
              // ★ 步骤序号的**唯一来源**是数组位置：定义层的步骤没有 `index`
              //   （它只有 server/tool），执行记录才有 —— 用位置编号，两者一致。
              const failurePos = failure ? (c.steps ?? []).indexOf(failure) + 1 : 0;
              const steps: GridStep[] = c.steps ?? c.planned ?? [];
              const metricKeys = c.metrics ? orderMetricKeys(c.metrics) : [];
              const shownMetrics = metricKeys.slice(0, INLINE_METRIC_LIMIT);
              return (
                <tr
                  /* ⚠️ 不能用 `index` 或 `cacheKey` 单独做 key：两者都**可能重复** ——
                     `index` 在"执行记录不属于当前定义"的追加行上会撞，
                     `cacheKey` 在"未引用因子"的重复格上会撞（正是网关告警的那种情形）。 */
                  key={`${rowIdx}-${c.cacheKey}`}
                  onClick={onSelect ? () => onSelect(c.index) : undefined}
                  className={`border-b border-border-subtle last:border-b-0 ${
                    selectedIndex === c.index ? "bg-interactive-subtle" : ""
                  } ${onSelect ? "cursor-pointer" : ""}`}
                >
                  <td className="px-2 py-1 font-mono align-top">{c.index}</td>
                  <td className="px-2 py-1 align-top">
                    <div className="font-mono">{c.caseId}</div>
                    <div className="text-text-muted">{bindingText(c.bindings)}</div>
                  </td>
                  <td className="px-2 py-1 align-top whitespace-nowrap">
                    <Signature sig={s.sig} text={s.label} />
                    {c.ranAt && <div className="mt-0.5 text-text-muted">{c.ranAt}</div>}
                  </td>
                  <td className="px-2 py-1 align-top">
                    {/* ★ 约束 1：失败**在这一格里**说清楚，不折叠进总进度 */}
                    {failure ? (
                      <div>
                        <div className="text-text-secondary">
                          失败于第 {failurePos} 步{" "}
                          <code>
                            {failure.server}.{failure.tool}
                          </code>
                        </div>
                        <div className="text-text-secondary">{failure.error ?? "（无错误详情）"}</div>
                        {failure.remounted && (
                          <div className="text-text-muted">
                            注：该步经「断裂后重连」执行 —— server 进程此前已死，会话状态无法担保。
                          </div>
                        )}
                      </div>
                    ) : steps.length ? (
                      <ol className="m-0 list-none p-0">
                        {steps.map((st, i) => (
                          <li key={i} className="flex items-center gap-1">
                            <span className="font-mono">{st.tool}</span>
                            {st.ok === true && <span className="text-text-muted">✔</span>}
                            {st.ok === false && <span className="text-text-muted">✖</span>}
                          </li>
                        ))}
                      </ol>
                    ) : (
                      <span className="text-text-muted">—</span>
                    )}
                    {c.definitionChanged && (
                      <div className="mt-0.5">
                        <Signature
                          sig="degraded"
                          text="不在当前定义里"
                          title="该格的 cache_key 不属于当前实验定义 —— 定义改过，这条记录来自旧条件"
                        />
                      </div>
                    )}
                    {c.status === "never_run" && (
                      <div className="text-text-muted">
                        当前 <code>cache_key</code> 没有存档结果（算例或模板改过，或从未执行）
                      </div>
                    )}
                    {shownMetrics.length > 0 && (
                      <div className="mt-0.5 font-mono text-text-secondary">
                        {shownMetrics.map((k) => `${k}=${fmtValue(c.metrics![k])}`).join("  ")}
                        {metricKeys.length > shownMetrics.length && (
                          <span className="text-text-muted">
                            {"  "}（共 {metricKeys.length} 项指标，见结果表）
                          </span>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-1 align-top font-mono break-all text-text-muted">
                    {c.cacheKey}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
