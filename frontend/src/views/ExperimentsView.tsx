/** ④ 实验矩阵视图 —— 方案 v4 §4.4「怎么批量跑」（判据 #2/#3 的界面落点）。
 *
 *  ★ 为什么它是「能组织研究」的落点：实验是**一等实体**（算例 × 因子 × 步骤序列），
 *    挂在算例下、结果按 `cache_key` 存档 —— 而不是会话里一串散落的 `tool_call`。
 *
 *  ★ **一格 = 一条显式声明的步骤序列**（2026-09-27 契约扩展）：引擎是**有状态**的，
 *    故一次 N-1 分析 = `load_network` → `run_n1_branch_contingency` 两步。
 *    本视图把「将要跑什么」（定义层）与「实际跑了什么」（执行层）都显示出来。
 *
 *  ★ **执行是串行且阻塞的**（网关侧裁决 §4.4）：一次 `/run` 请求跑完全部格子才返回，
 *    故界面在等待期显示"正在执行"并**禁用重复提交**（网关对同一实验返回 409）。
 *
 *  ⚠️ **本视图不发明语义**：因子只作标签维度，步骤序列由用户显式声明（JSON 定义）；
 *    界面不预置任何引擎专属模板，也不做"负荷水平"这类语义猜测。
 *
 *  ⚠️ 与 `CasesView` 同一处有意差异：操作反馈就地显示在面板内（`Toast` 属 S2 面）。
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  CasesResponseSchema,
  ExperimentCreateResponseSchema,
  ExperimentDeleteResponseSchema,
  ExperimentDetailSchema,
  ExperimentResultsResponseSchema,
  ExperimentRunResponseSchema,
  ExperimentsResponseSchema,
  SchemaDriftError,
  apiParsed,
  type Case,
  type ExperimentDetail,
  type ExperimentResultsResponse,
  type ExperimentRunResponse,
  type ExperimentsResponse,
} from "../api";
import {
  Button,
  EmptyState,
  ErrorBanner,
  ExperimentGrid,
  LoadingState,
  Signature,
  type GridCell,
} from "../components";

type Sig = "violated" | "incident";

/** 新建实验的**中性**模板 —— 不含任何引擎/模块专属内容（避免界面替用户声称能力）。
 *  `{case_path}` / `{case_id}` 是网关的**内置占位符**；`{因子名}` 由 `factors` 提供。 */
export const DEFAULT_STEPS_JSON = JSON.stringify(
  [{ server: "<server>", tool: "<tool>", args_template: {} }],
  null,
  2,
);

/** ★ 网格数据的**单一来源**：定义（要跑什么）→ 执行（跑得怎样）→ 结果表（指标）。
 *  优先级 = 信息量从新到旧，避免"执行过了却还显示待跑"这种自相矛盾的界面。
 *
 *  ★ 键取**并集**（不是只取当前定义）：只按当前定义取键，会让"定义变过之后取回的
 *    执行记录 / 存档结果"被**静默丢弃** —— 用户刚跑完却什么都看不到。
 *    并集里不属于当前定义的格子标记 `definitionChanged`，由网格显式标出。 */
export function toGridCells(
  detail: ExperimentDetail | null,
  run: ExperimentRunResponse | null,
  results: ExperimentResultsResponse | null,
): GridCell[] {
  const base = detail?.cells ?? [];
  const defByKey = new Map(base.map((c) => [c.cache_key, c]));
  const runByKey = new Map((run?.cells ?? []).map((c) => [c.cache_key, c]));
  const resByKey = new Map((results?.rows ?? []).map((r) => [r.cache_key, r]));

  const currentKeys = base.map((c) => c.cache_key);
  const extraKeys = [...new Set([...runByKey.keys(), ...resByKey.keys()])].filter(
    (k) => !defByKey.has(k),
  );

  return [...currentKeys, ...extraKeys].map((key, i) => {
    const def = defByKey.get(key);
    const rec = runByKey.get(key);
    const row = resByKey.get(key);
    const metrics = row?.metrics;
    const hasMetrics = !!metrics && Object.keys(metrics).length > 0;
    return {
      index: def?.index ?? rec?.index ?? row?.index ?? i,
      caseId: def?.case_id ?? rec?.case_id ?? row?.case_id ?? "?",
      bindings: def?.bindings ?? rec?.bindings ?? row?.bindings ?? {},
      cacheKey: key,
      // 结果表的状态最"新"（它会因算例改动而变 never_run）；其次执行记录；最后定义层
      status: row ? row.status : rec ? rec.status : (def?.status ?? "pending"),
      planned: def?.steps.map((s) => ({ server: s.server, tool: s.tool })),
      steps: rec?.steps,
      ranAt: row?.ran_at ?? rec?.ran_at ?? null,
      metrics: hasMetrics ? metrics : undefined,
      definitionChanged: !defByKey.has(key),
    };
  });
}

export function ExperimentsView() {
  // ★ 深链 `#experiments/<eid>` 直接选中某个实验 —— 与 `#skills` 同性质：
  //   既可分享，也让**无头验证**能定位到具体实验（否则截图只能拍到列表）。
  const initialEid = useMemo(() => {
    const m = window.location.hash.match(/experiments\/([A-Za-z0-9_-]+)/);
    return m ? m[1] : null;
  }, []);

  const [list, setList] = useState<ExperimentsResponse | null>(null);
  const [cases, setCases] = useState<Case[]>([]);
  const [selected, setSelected] = useState<string | null>(initialEid);
  const [detail, setDetail] = useState<ExperimentDetail | null>(null);
  const [run, setRun] = useState<ExperimentRunResponse | null>(null);
  const [results, setResults] = useState<ExperimentResultsResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<{ message: string; sig: Sig } | null>(null);
  const [note, setNote] = useState<ReactNode>(null);

  // 新建实验表单
  const [showForm, setShowForm] = useState(false);
  const [formCases, setFormCases] = useState<string[]>([]);
  const [formSteps, setFormSteps] = useState(DEFAULT_STEPS_JSON);
  const [formFactors, setFormFactors] = useState("[]");

  const fail = useCallback((err: unknown) => {
    setError({
      message: (err as Error).message,
      // ★ 结构漂移 = incident（本可判定却拿不到）；其余 = violated
      sig: err instanceof SchemaDriftError ? "incident" : "violated",
    });
  }, []);

  const reload = useCallback(async () => {
    try {
      const [l, cs] = await Promise.all([
        apiParsed("/experiments", ExperimentsResponseSchema),
        apiParsed("/cases", CasesResponseSchema),
      ]);
      setList(l);
      setCases(cs.cases);
      setError(null);
    } catch (err) {
      fail(err);
    }
  }, [fail]);

  useEffect(() => {
    void reload();
  }, [reload]);

  /** 选中实验 → 拉定义（并清掉上一次的执行/结果，避免张冠李戴）。 */
  const select = useCallback(
    async (eid: string) => {
      setSelected(eid);
      setDetail(null);
      setRun(null);
      setResults(null);
      setNote(null);
      try {
        setDetail(await apiParsed(`/experiments/${eid}`, ExperimentDetailSchema));
        setError(null);
      } catch (err) {
        fail(err);
      }
    },
    [fail],
  );

  /** 深链进来的实验要在挂载后自动拉定义（`selected` 的初始值来自 hash）。 */
  const bootstrapped = useRef(false);
  useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    if (initialEid) void select(initialEid);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅首次
  }, []);

  async function doRun(eid: string) {
    setBusy(eid);
    setNote(null);
    setError(null);
    try {
      const r = await apiParsed(`/experiments/${eid}/run`, ExperimentRunResponseSchema, {
        method: "POST",
      });
      setRun(r);
      setResults(null); // 结果表可能已过时（本轮跑的是当前 cache_key）
      const ok = r.summary.ok ?? 0;
      const bad = r.summary.failed ?? 0;
      setNote(
        <>
          已串行执行 <strong>{r.summary.cells}</strong> 格：成功 <strong>{ok}</strong> · 失败{" "}
          <strong>{bad}</strong>
          {bad > 0 && "（失败格在下方逐格可见）"}
        </>,
      );
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function doResults(eid: string) {
    setBusy(eid);
    setNote(null);
    setError(null);
    try {
      setResults(await apiParsed(`/experiments/${eid}/results`, ExperimentResultsResponseSchema));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function doDelete(eid: string, label: string) {
    if (!window.confirm(`确定删除实验“${label}”吗？该实验的结果记录也会被删除，算例源文件不受影响。`)) {
      return;
    }
    setBusy(eid);
    setNote(null);
    setError(null);
    try {
      await apiParsed(`/experiments/${eid}`, ExperimentDeleteResponseSchema, { method: "DELETE" });
      if (selected === eid) {
        setSelected(null);
        setDetail(null);
        setRun(null);
        setResults(null);
      }
      await reload();
      setNote(<>已删除实验 <span className="font-mono">{eid}</span>（算例源文件未删除）</>);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(null);
    }
  }

  async function create() {
    setNote(null);
    setError(null);
    if (!formCases.length) {
      setError({ message: "请至少勾选一个算例（实验的主语是算例）", sig: "violated" });
      return;
    }
    let steps: unknown;
    let factors: unknown;
    try {
      steps = JSON.parse(formSteps);
    } catch (e) {
      setError({ message: `「步骤」不是合法 JSON：${(e as Error).message}`, sig: "violated" });
      return;
    }
    try {
      factors = JSON.parse(formFactors || "[]");
    } catch (e) {
      setError({ message: `「因子」不是合法 JSON：${(e as Error).message}`, sig: "violated" });
      return;
    }
    try {
      const r = await apiParsed("/experiments", ExperimentCreateResponseSchema, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case_ids: formCases, steps, factors }),
      });
      setShowForm(false);
      await reload();
      // ★ 网关的 `notes` 必须显示：尤其「因子未被引用 → 重复格」那条告警 ——
      //   吞掉它，"N 格都成功"就会掩盖"其实只跑了一种条件"。
      setNote(
        <>
          {r.created ? "已登记实验" : "该定义已存在，未重复登记"}
          <span className="ml-1 font-mono">{r.experiment.id}</span>（{r.summary.cells} 格）
          {r.notes?.length ? (
            <ul className="mt-1 ml-4 list-disc">
              {r.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          ) : null}
        </>,
      );
    } catch (err) {
      fail(err);
    }
  }

  const gridCells = useMemo(() => toGridCells(detail, run, results), [detail, run, results]);
  const exp = detail?.experiment;

  return (
    <section aria-label="实验矩阵" className="min-w-0 flex-1 overflow-auto p-4">
      <div className="flex items-center gap-2">
        <h2 className="m-0 text-h2 font-medium">实验矩阵</h2>
        {list && (
          <span className="text-bodySm text-text-muted">
            {list.summary.total} 个实验 · 共 {list.summary.cells} 格
          </span>
        )}
        <span className="ml-auto" />
        <Button onClick={() => setShowForm((v) => !v)}>
          {showForm ? "收起新建" : "新建实验"}
        </Button>
      </div>

      {error && <ErrorBanner sig={error.sig} message={error.message} />}
      {note && (
        <div className="mt-2 rounded-md border border-border-subtle bg-surface-sunken px-3 py-2 text-bodySm text-text-secondary">
          {note}
        </div>
      )}

      {!list && !error && <LoadingState label="加载中…（等待 /experiments）" />}

      {showForm && (
        <div className="mt-3 rounded-md border border-border-subtle p-3">
          <div className="text-bodySm font-medium">新建实验</div>
          <div className="mt-1 text-caption text-text-muted">
            实验 = 算例集合 × 因子网格 × <strong>步骤序列</strong>。全部步骤必须属于
            <strong>同一个 server</strong>（有状态序列的前提：上一步装进的引擎状态要留给下一步）。
          </div>

          <div className="mt-2 text-bodySm">算例</div>
          {cases.length ? (
            <div className="mt-1 max-h-32 overflow-auto rounded-sm border border-border-subtle p-1">
              {cases.map((c) => (
                <label key={c.id} className="flex items-center gap-2 px-1 py-0.5 text-caption">
                  <input
                    type="checkbox"
                    checked={formCases.includes(c.id)}
                    onChange={(e) =>
                      setFormCases((prev) =>
                        e.target.checked ? [...prev, c.id] : prev.filter((x) => x !== c.id),
                      )
                    }
                  />
                  <span className="font-mono">{c.label}</span>
                  <span className="text-text-muted">{c.id}</span>
                </label>
              ))}
            </div>
          ) : (
            <EmptyState hint="先在左侧「算例库」登记一个算例。">还没有可用的算例。</EmptyState>
          )}

          <label className="mt-2 block text-bodySm">
            步骤（JSON）
            <textarea
              aria-label="步骤（JSON）"
              value={formSteps}
              onChange={(e) => setFormSteps(e.target.value)}
              rows={6}
              className="mt-1 w-full rounded-sm border border-border-subtle bg-surface-sunken p-2 font-mono text-caption"
            />
          </label>
          <div className="text-caption text-text-muted">
            内置占位符：<code>{"{case_path}"}</code>（算例绝对路径）· <code>{"{case_id}"}</code>；
            因子写成 <code>{"{因子名}"}</code>。未知占位符会被网关<strong>拒绝</strong>（不会静默留下）。
          </div>

          <label className="mt-2 block text-bodySm">
            因子（JSON，可空）
            <textarea
              aria-label="因子（JSON）"
              value={formFactors}
              onChange={(e) => setFormFactors(e.target.value)}
              rows={3}
              className="mt-1 w-full rounded-sm border border-border-subtle bg-surface-sunken p-2 font-mono text-caption"
            />
          </label>
          <div className="text-caption text-text-muted">
            ⚠️ 因子只有在<strong>被模板引用</strong>时才改变实验条件；未被引用的因子会让各格
            <code>cache_key</code> 相同（重复格）—— 网关会就此告警。
          </div>

          <div className="mt-2">
            <Button onClick={() => void create()}>登记实验</Button>
          </div>
        </div>
      )}

      {list && (
        <div className="mt-3">
          {list.experiments.length ? (
            list.experiments.map((e) => (
              <div
                key={e.id}
                className={`mb-1 rounded-sm border px-3 py-2 ${
                  selected === e.id
                    ? "border-interactive-default bg-interactive-subtle"
                    : "border-border-subtle"
                }`}
              >
                <button
                  type="button"
                  onClick={() => void select(e.id)}
                  className="block w-full text-left"
                >
                  <div className="text-bodySm font-medium">{e.label}</div>
                  <div className="font-mono text-caption text-text-muted">{e.id}</div>
                  <div className="text-caption text-text-secondary">
                    {e.steps.map((s) => `${s.server}.${s.tool}`).join(" → ")}
                    {typeof e.cell_count === "number" && <> · {e.cell_count} 格</>}
                  </div>
                </button>
                {/* ★ 引用的算例被注销 → 网格展不开。**不静默跳过**，如实显示在实验卡上 */}
                {e.error && (
                  <div className="mt-1 flex items-center gap-2">
                    <Signature sig="degraded" text="网格不可展开" />
                    <span className="text-caption text-text-secondary">{e.error}</span>
                  </div>
                )}
                <div className="mt-1 flex justify-end">
                  <Button
                    onClick={() => void doDelete(e.id, e.label)}
                    disabled={busy === e.id}
                    aria-label={`删除实验 ${e.label}`}
                  >
                    {busy === e.id ? "删除中…" : "删除"}
                  </Button>
                </div>
              </div>
            ))
          ) : (
            <EmptyState hint="点右上「新建实验」登记一个（需要先在算例库登记算例）。">
              还没有实验。
            </EmptyState>
          )}
        </div>
      )}

      {exp && (
        <div className="mt-4 rounded-md border border-border-subtle p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-bodySm font-medium">{exp.label}</span>
            <span className="font-mono text-caption text-text-muted">{exp.id}</span>
            <span className="ml-auto" />
            <Button onClick={() => selected && void doRun(selected)} disabled={busy === selected}>
              {busy === selected ? "执行中…" : "串行执行"}
            </Button>
            <Button onClick={() => selected && void doResults(selected)} disabled={busy === selected}>
              刷新结果表
            </Button>
            {/* ★ 导出走网关的文本端点（PDF 属渲染层，网关不做） */}
            <a
              className="rounded-sm border border-border-subtle px-2 py-1 text-bodySm hover:bg-interactive-subtle"
              href={`/experiments/${exp.id}/export?format=csv`}
            >
              导出 CSV
            </a>
            <a
              className="rounded-sm border border-border-subtle px-2 py-1 text-bodySm hover:bg-interactive-subtle"
              href={`/experiments/${exp.id}/export?format=md`}
            >
              导出 Markdown
            </a>
          </div>

          <div className="mt-2 text-caption text-text-secondary">
            步骤序列：
            {exp.steps.map((s, i) => (
              <span key={i} className="ml-1 font-mono">
                {i > 0 && " → "}
                {s.server}.{s.tool}
              </span>
            ))}
            {exp.factors.length > 0 && (
              <>
                {" · 因子："}
                {exp.factors.map((f) => `${f.name}(${f.values.length})`).join(" · ")}
              </>
            )}
          </div>

          {/* ★ 串行 + 阻塞的如实说明（不做并发暗示） */}
          <div className="mt-1 text-caption text-text-muted">
            执行是<strong>串行</strong>的：一次请求按网格顺序跑完全部格子；
            <strong>一格一个会话</strong>，某格失败只影响该格（失败原因在格内可见），不会中断其他格。
          </div>

          {detail && !run && !results && (
            <div className="mt-2 text-caption text-text-muted">
              下面是<strong>定义层</strong>网格（每格已绑定参数与 <code>cache_key</code>），状态为「待跑」——
              点「串行执行」才会真正跑。
            </div>
          )}

          <div className="mt-2">
            <ExperimentGrid cells={gridCells} orphaned={results?.summary.orphaned ?? 0} />
          </div>

          {results && results.orphaned_keys.length > 0 && (
            <details className="mt-2 text-caption text-text-muted">
              <summary>陈旧结果的 cache_key（{results.orphaned_keys.length}）</summary>
              <div className="mt-1 font-mono break-all">{results.orphaned_keys.join("\n")}</div>
            </details>
          )}
        </div>
      )}

    </section>
  );
}
