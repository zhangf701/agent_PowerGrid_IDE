/** ④ 实验矩阵视图 + ExperimentGrid 的测试。
 *
 *  ★ 三条硬约束必须被钉住（UI 规范 §4.7.5）：
 *    1. 进度可观测且**失败逐格可见**（不得只给总进度条）
 *    2. 结果**绑 cache_key**，陈旧结果须标注「来自旧条件」
 *    3. **串行优先**（界面不得做并发暗示）
 *  ★ 夹具全部来自**运行中的真实网关**（`src/__fixtures__/gateway/experiment*.json`），
 *    并在此断言「真实响应能通过 zod schema」—— 防止 schema 写的是想象中的字段。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  ExperimentCreateResponseSchema,
  ExperimentDetailSchema,
  ExperimentResultsResponseSchema,
  ExperimentRunResponseSchema,
  ExperimentsResponseSchema,
  V2ProposalsListSchema,
} from "./api";
import {
  ExperimentGrid,
  bindingText,
  cellSignature,
  firstFailure,
  orderMetricKeys,
  type GridCell,
} from "./components/ExperimentGrid";
import { ExperimentsView, toGridCells } from "./views/ExperimentsView";

import casesFx from "./__fixtures__/gateway/cases.json";
import createFx from "./__fixtures__/gateway/experiment-create.json";
import detailFx from "./__fixtures__/gateway/experiment-detail.json";
import detailFailedFx from "./__fixtures__/gateway/experiment-detail-failed.json";
import listFx from "./__fixtures__/gateway/experiments.json";
import proposalsFx from "./__fixtures__/gateway/experiment-proposals.json";
import resultsFx from "./__fixtures__/gateway/experiment-results.json";
import staleFx from "./__fixtures__/gateway/experiment-results-stale.json";
import runFailedFx from "./__fixtures__/gateway/experiment-run-failed.json";
import runFx from "./__fixtures__/gateway/experiment-run.json";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const json = (body: unknown, status = 200) =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );

type Call = { method: string; url: string; body?: unknown };

/** 打桩：按 URL + 方法路由到真实夹具。 */
function stub(overrides: Record<string, () => Promise<Response>> = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });

      for (const [key, handler] of Object.entries(overrides)) {
        if (url.includes(key)) return handler();
      }
      if (url.includes("/cases")) return json(casesFx);
      // ★ 提案清单（提案卡挂载时就会请求）—— 不路由会落到 listFx，触发 schema 漂移
      if (url.includes("/experiment-proposals")) return json(proposalsFx);
      if (url.includes("/experiments/") && url.endsWith("/run")) return json(runFx);
      if (url.includes("/experiments/") && url.endsWith("/results")) return json(resultsFx);
      if (url.includes("/experiments/")) return json(detailFx);
      if (method === "POST" && url.endsWith("/experiments")) return json(createFx, 201);
      return json(listFx);
    }),
  );
  return calls;
}

/* ══════════════ 夹具 ↔ schema（真实响应必须能通过）══════════════ */

describe("experiments 夹具通过 schema", () => {
  it("列表 / 详情 / 执行 / 结果 / 建实验 五个真实响应全部通过", () => {
    expect(ExperimentsResponseSchema.safeParse(listFx).success).toBe(true);
    expect(ExperimentDetailSchema.safeParse(detailFx).success).toBe(true);
    expect(ExperimentDetailSchema.safeParse(detailFailedFx).success).toBe(true);
    expect(ExperimentRunResponseSchema.safeParse(runFx).success).toBe(true);
    expect(ExperimentRunResponseSchema.safeParse(runFailedFx).success).toBe(true);
    expect(ExperimentResultsResponseSchema.safeParse(resultsFx).success).toBe(true);
    expect(ExperimentResultsResponseSchema.safeParse(staleFx).success).toBe(true);
    expect(ExperimentCreateResponseSchema.safeParse(createFx).success).toBe(true);
  });

  it("★ 执行夹具里 `remounted` 与 `error` 是**显式字段**（失败可见的载体）", () => {
    const parsed = ExperimentRunResponseSchema.parse(runFailedFx);
    const step = parsed.cells[0].steps[1];
    expect(step.ok).toBe(false);
    expect(step.error).toBeTruthy();
    expect(step.remounted).toBe(false);
  });

  it("★ 陈旧夹具确实是 never_run + orphaned（否则约束 2 的测试会假过）", () => {
    const parsed = ExperimentResultsResponseSchema.parse(staleFx);
    expect(parsed.rows[0].status).toBe("never_run");
    expect(parsed.summary.orphaned).toBeGreaterThan(0);
    expect(parsed.orphaned_keys.length).toBe(parsed.summary.orphaned);
  });
});

/* ══════════════ 纯函数 ══════════════ */

describe("ExperimentGrid 纯函数", () => {
  it("cellSignature：未知状态**不得**被当作正常", () => {
    expect(cellSignature("ok").sig).toBe("satisfied");
    expect(cellSignature("failed").sig).toBe("violated");
    expect(cellSignature("never_run").sig).toBe("unknown");
    // 网关将来新增状态 → 原样显示 + unknown 签名（不猜、不静默当成功）
    expect(cellSignature("paused")).toEqual({ sig: "unknown", label: "paused" });
  });

  it("firstFailure 取**第一个**失败步（不是最后一个）", () => {
    const steps = [
      { server: "s", tool: "a", ok: true },
      { server: "s", tool: "b", ok: false, error: "boom" },
      { server: "s", tool: "c", ok: false, error: "later" },
    ];
    expect(firstFailure(steps)?.tool).toBe("b");
    expect(firstFailure([{ server: "s", tool: "a", ok: true }])).toBeNull();
    expect(firstFailure(undefined)).toBeNull();
  });

  it("bindingText 按名排序（同一实验行序稳定）", () => {
    expect(bindingText({ b: 2, a: 1 })).toBe("a=1 · b=2");
    expect(bindingText({})).toBe("—");
  });

  it("★ orderMetricKeys：数值优先（可比较的量不被长文案挤掉）", () => {
    expect(
      orderMetricKeys({
        "metric.message": "N-1 branch analysis: 46 scenarios",
        "metric.results.n_contingencies": 46,
        "metric.ok": true,
        "metric.results.n_violations": 52,
      }),
    ).toEqual([
      "metric.results.n_contingencies",
      "metric.results.n_violations",
      "metric.ok",
      "metric.message",
    ]);
  });

  it("toGridCells：结果表状态优先于执行记录与定义层", () => {
    const detail = ExperimentDetailSchema.parse(detailFx);
    const results = ExperimentResultsResponseSchema.parse(staleFx);
    // 定义层说 pending，但结果表说 never_run（算例改过）—— 必须以后者为准
    const cells = toGridCells(detail, null, results);
    const key = results.rows[0].cache_key;
    const cell = cells.find((c) => c.cacheKey === key);
    if (cell) expect(cell.status).toBe("never_run");
  });

  it("★ toGridCells：执行记录若不在当前定义里，必须**保留并标记**（不静默丢）", () => {
    const detail = ExperimentDetailSchema.parse(detailFx);
    const run = ExperimentRunResponseSchema.parse(runFailedFx); // 另一个实验（key 不同）
    const cells = toGridCells(detail, run, null);
    const runKey = run.cells[0].cache_key;
    const extra = cells.find((c) => c.cacheKey === runKey);
    expect(extra, "执行记录被静默丢弃了").toBeTruthy();
    expect(extra!.definitionChanged).toBe(true);
    expect(extra!.steps?.[1].ok).toBe(false); // 失败信息仍在
    // 当前定义的格子仍然在前、且未被标记
    expect(cells[0].definitionChanged).toBe(false);
  });

  it("toGridCells：定义与执行一致时，不产生多余行、不误标", () => {
    const detail = ExperimentDetailSchema.parse(detailFx);
    const run = ExperimentRunResponseSchema.parse(runFx); // 同 cache_key
    const cells = toGridCells(detail, run, null);
    expect(cells.length).toBe(detail.cells.length);
    expect(cells.every((c) => !c.definitionChanged)).toBe(true);
    expect(cells.every((c) => c.status === "ok")).toBe(true);
  });
});

/* ══════════════ ExperimentGrid 渲染（三条约束）══════════════ */

function grid(cells: GridCell[], orphaned = 0) {
  return render(<ExperimentGrid cells={cells} orphaned={orphaned} />);
}

describe("ExperimentGrid · 约束 1：失败逐格可见", () => {
  it("失败格**在行内**给出失败步骤与引擎错误，不折叠成总进度", () => {
    const cells: GridCell[] = [
      {
        index: 0,
        caseId: "cd4cf1328477",
        bindings: {},
        cacheKey: "k0",
        status: "failed",
        steps: [
          { server: "surge", tool: "load_network", ok: true, error: null, remounted: false },
          {
            server: "surge",
            tool: "no_such_tool",
            ok: false,
            error: "surge.no_such_tool 不存在或该 server 未拉起",
            remounted: false,
          },
        ],
      },
    ];
    grid(cells);
    expect(screen.getByText(/失败于第 2 步/)).toBeTruthy();
    // 工具名出现在两处：失败步骤的 <code>（"surge.no_such_tool"）与引擎错误原文
    expect(screen.getAllByText(/no_such_tool/).length).toBeGreaterThan(0);
    expect(screen.getByText(/不存在或该 server 未拉起/)).toBeTruthy();
    // 状态徽标与总计数都在（总计数是补充，不是唯一信息）
    expect(screen.getAllByText("失败").length).toBeGreaterThan(0);
    expect(screen.getByText(/共/)).toBeTruthy();
  });

  it("★ `remounted=true` 必须解释「会话状态无法担保」", () => {
    grid([
      {
        index: 0,
        caseId: "c",
        bindings: {},
        cacheKey: "k",
        status: "failed",
        steps: [{ server: "s", tool: "t", ok: false, error: "连接断裂", remounted: true }],
      },
    ]);
    expect(screen.getByText(/server 进程此前已死/)).toBeTruthy();
  });
});

describe("ExperimentGrid · 约束 2：结果绑 cache_key", () => {
  it("每行显示 cache_key", () => {
    grid([{ index: 0, caseId: "c", bindings: {}, cacheKey: "abc123def456", status: "ok" }]);
    expect(screen.getByText("abc123def456")).toBeTruthy();
  });

  it("never_run 必须说明「当前 cache_key 没有存档结果」", () => {
    grid([{ index: 0, caseId: "c", bindings: {}, cacheKey: "k", status: "never_run" }]);
    expect(screen.getByText(/没有存档结果/)).toBeTruthy();
  });

  it("★ 陈旧结果（orphaned）必须显式标注「来自旧条件」", () => {
    grid([{ index: 0, caseId: "c", bindings: {}, cacheKey: "k", status: "never_run" }], 3);
    expect(screen.getByText(/3 条陈旧结果/)).toBeTruthy();
    expect(screen.getByText(/来自旧条件/)).toBeTruthy();
  });

  it("无陈旧结果时不渲染陈旧提示（不制造假警报）", () => {
    grid([{ index: 0, caseId: "c", bindings: {}, cacheKey: "k", status: "ok" }], 0);
    expect(screen.queryByText(/陈旧结果/)).toBeNull();
  });

  it("★ 重复格（未引用因子 → 相同 cache_key）不得撞 React key，且两行都要渲染", () => {
    grid([
      { index: 0, caseId: "c", bindings: { load_level: 1.0 }, cacheKey: "same", status: "pending" },
      { index: 1, caseId: "c", bindings: { load_level: 1.1 }, cacheKey: "same", status: "pending" },
    ]);
    // 两行都渲染（key 若重复，React 会丢行）
    expect(screen.getAllByText("same").length).toBe(2);
    expect(screen.getByText("load_level=1")).toBeTruthy();
    expect(screen.getByText("load_level=1.1")).toBeTruthy();
  });
});

/* ══════════════ 视图 ══════════════ */

describe("ExperimentsView", () => {
  it("加载后列出实验与计数", async () => {
    stub();
    render(<ExperimentsView />);
    await waitFor(() => expect(screen.getByText(/个实验 · 共/)).toBeTruthy());
    expect(screen.getByText("case39 N-1 两步")).toBeTruthy();
  });

  it("★ 约束 3：如实写明串行，且**不提供**并发控件", async () => {
    stub();
    render(<ExperimentsView />);
    await waitFor(() => expect(screen.getByText("case39 N-1 两步")).toBeTruthy());
    fireEvent.click(screen.getByText("case39 N-1 两步"));
    await waitFor(() => expect(screen.getByText(/串行执行（不并发）/)).toBeTruthy());
    expect(screen.getByText(/一格一个会话/)).toBeTruthy();
    expect(screen.queryByText(/并行度/)).toBeNull();
    expect(screen.queryByText(/并发数/)).toBeNull();
  });

  it("删除实验 → 二次确认后 DELETE，并清掉当前选择", async () => {
    const calls = stub({
      "/experiments/": () => json({ deleted: true, experiment_id: detailFx.experiment.id }),
    });
    vi.stubGlobal("confirm", vi.fn(() => true));
    render(<ExperimentsView />);
    await waitFor(() => expect(screen.getByText("case39 N-1 两步")).toBeTruthy());
    fireEvent.click(screen.getByLabelText("删除实验 case39 N-1 两步"));
    await waitFor(() => expect(screen.getByText(/已删除实验/)).toBeTruthy());
    expect(vi.mocked(window.confirm)).toHaveBeenCalledOnce();
    expect(calls.some((c) => c.method === "DELETE" && c.url.includes("/experiments/"))).toBe(true);
    expect(screen.queryByTestId("experiment-grid")).toBeNull();
  });

  it("选中实验 → 拉定义并渲染网格（含定义层「待跑」说明）", async () => {
    stub();
    render(<ExperimentsView />);
    await waitFor(() => expect(screen.getByText("case39 N-1 两步")).toBeTruthy());
    fireEvent.click(screen.getByText("case39 N-1 两步"));
    await waitFor(() => expect(screen.getByTestId("experiment-grid")).toBeTruthy());
    expect(screen.getByText(/定义层/)).toBeTruthy();
    // 两步序列都要显示出来
    expect(screen.getAllByText(/load_network/).length).toBeGreaterThan(0);
  });

  it("串行执行 → POST /run，并显示逐格结果与计数", async () => {
    const calls = stub();
    render(<ExperimentsView />);
    await waitFor(() => expect(screen.getByText("case39 N-1 两步")).toBeTruthy());
    fireEvent.click(screen.getByText("case39 N-1 两步"));
    await waitFor(() => expect(screen.getByTestId("experiment-grid")).toBeTruthy());

    fireEvent.click(screen.getByText("串行执行"));
    await waitFor(() => expect(screen.getByText(/已串行执行/)).toBeTruthy());
    const runCall = calls.find((c) => c.method === "POST" && c.url.endsWith("/run"));
    expect(runCall).toBeTruthy();
    expect(screen.getAllByText(/成功/).length).toBeGreaterThan(0);
  });

  it("★ 执行失败时失败格逐格可见（用真实的失败夹具）", async () => {
    stub({
      "/run": () => json(runFailedFx),
      "/experiments/": () => json(detailFailedFx),
    });
    render(<ExperimentsView />);
    await waitFor(() => expect(screen.getByText("失败示例（工具不存在）")).toBeTruthy());
    fireEvent.click(screen.getByText("失败示例（工具不存在）"));
    await waitFor(() => expect(screen.getByTestId("experiment-grid")).toBeTruthy());

    fireEvent.click(screen.getByText("串行执行"));
    await waitFor(() => expect(screen.getByText(/失败于第 2 步/)).toBeTruthy());
    expect(screen.getByText(/no_such_tool 不存在或该 server 未拉起/)).toBeTruthy();
  });

  it("刷新结果表 → 显示陈旧标注与 orphaned 明细", async () => {
    stub({ "/results": () => json(staleFx) });
    render(<ExperimentsView />);
    await waitFor(() => expect(screen.getByText("case39 N-1 两步")).toBeTruthy());
    fireEvent.click(screen.getByText("case39 N-1 两步"));
    await waitFor(() => expect(screen.getByTestId("experiment-grid")).toBeTruthy());

    fireEvent.click(screen.getByText("刷新结果表"));
    await waitFor(() => expect(screen.getByText(/来自旧条件/)).toBeTruthy());
    expect(screen.getByText(/陈旧结果的 cache_key/)).toBeTruthy();
  });

  it("导出链接指向网关的文本端点（PDF 不在网关做）", async () => {
    stub();
    render(<ExperimentsView />);
    await waitFor(() => expect(screen.getByText("case39 N-1 两步")).toBeTruthy());
    fireEvent.click(screen.getByText("case39 N-1 两步"));
    await waitFor(() => expect(screen.getByText("导出 CSV")).toBeTruthy());
    const eid = detailFx.experiment.id;
    expect(screen.getByText("导出 CSV").getAttribute("href")).toBe(
      `/experiments/${eid}/export?format=csv`,
    );
    expect(screen.getByText("导出 Markdown").getAttribute("href")).toBe(
      `/experiments/${eid}/export?format=md`,
    );
  });

  it("★ 深链 #experiments/<eid> 自动选中该实验（可分享 / 供无头验证定位）", async () => {
    window.location.hash = `#experiments/${detailFx.experiment.id}`;
    try {
      stub();
      render(<ExperimentsView />);
      await waitFor(() => expect(screen.getByTestId("experiment-grid")).toBeTruthy());
      expect(screen.getByText("导出 CSV")).toBeTruthy();
    } finally {
      window.location.hash = "";
    }
  });

  it("★ 结构漂移 → incident 横幅（不是静默）", async () => {
    stub({ "/experiments": () => json({ wrong: true }) });
    render(<ExperimentsView />);
    await waitFor(() => expect(screen.getByText(/响应结构与前端契约不符/)).toBeTruthy());
    expect(screen.getByText("事故")).toBeTruthy();
  });

  it("★ 建实验：提交 case_ids/steps/factors，并**显示网关 notes**（未引用因子告警）", async () => {
    const calls = stub();
    render(<ExperimentsView />);
    await waitFor(() => expect(screen.getByText("新建实验")).toBeTruthy());
    fireEvent.click(screen.getByText("新建实验"));

    // 勾选第一个算例（checkbox 在 <label> 内，点文字即切换）
    const firstCase = casesFx.cases[0];
    fireEvent.click(screen.getByText(firstCase.id));
    fireEvent.change(screen.getByLabelText("步骤（JSON）"), {
      target: {
        value: JSON.stringify([
          { server: "surge", tool: "load_network", args_template: { file_path: "{case_path}" } },
        ]),
      },
    });
    fireEvent.click(screen.getByText("登记实验"));

    await waitFor(() => expect(screen.getByText(/已登记实验|该定义已存在/)).toBeTruthy());
    const post = calls.find((c) => c.method === "POST" && c.url.endsWith("/experiments"));
    expect(post).toBeTruthy();
    expect(post!.body).toMatchObject({ case_ids: [firstCase.id] });
    // ★ 网关的告警必须出现在界面上（吞掉它 = 让"重复格"看起来正常）
    expect(screen.getByText(/未被任何步骤的/)).toBeTruthy();
  });

  it("建实验：步骤 JSON 非法 → 就地报错，不发请求", async () => {
    const calls = stub();
    render(<ExperimentsView />);
    await waitFor(() => expect(screen.getByText("新建实验")).toBeTruthy());
    fireEvent.click(screen.getByText("新建实验"));
    const firstCase = casesFx.cases[0];
    fireEvent.click(screen.getByText(firstCase.id));
    fireEvent.change(screen.getByLabelText("步骤（JSON）"), { target: { value: "{bad" } });
    fireEvent.click(screen.getByText("登记实验"));

    await waitFor(() => expect(screen.getByText(/不是合法 JSON/)).toBeTruthy());
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });
});

/* ══════════════ ★ 提案可累积多个（F-V2-6 回归）══════════════ */

describe("★ 提案清单：可累积多个、可提交 / 删除", () => {
  it("夹具来自真实网关且通过 schema（含已提交与未提交两种）", () => {
    expect(V2ProposalsListSchema.safeParse(proposalsFx).success).toBe(true);
    expect(proposalsFx.total).toBe(proposalsFx.proposals.length);
    // ★ 夹具必须两种都含，否则下面「已提交显示 eid / 未提交有提交按钮」的断言会假过
    expect(proposalsFx.proposals.some((p) => p.committed_eid)).toBe(true);
    expect(proposalsFx.proposals.some((p) => !p.committed_eid)).toBe(true);
  });

  it("★ 全部提案都渲染出来（不再「一次只能看到一个」）", async () => {
    stub();
    render(<ExperimentsView />);
    await waitFor(() => expect(screen.getByText(`已有提案（${proposalsFx.total}）`)).toBeTruthy());
    for (const item of proposalsFx.proposals) {
      expect(screen.getByText(item.proposal_id)).toBeTruthy();
    }
  });

  it("已提交的提案显示其 eid；未提交的有「提交」按钮", async () => {
    stub();
    render(<ExperimentsView />);
    await waitFor(() => expect(screen.getByText(/已有提案/)).toBeTruthy());
    const committed = proposalsFx.proposals.find((p) => p.committed_eid)!;
    expect(screen.getByText(committed.committed_eid!)).toBeTruthy();
    const pending = proposalsFx.proposals.find((p) => !p.committed_eid)!;
    expect(screen.getByLabelText(`提交提案 ${pending.proposal_id}`)).toBeTruthy();
  });

  it("删除提案真的发 DELETE 请求（不是只从界面消失）", async () => {
    const calls = stub();
    render(<ExperimentsView />);
    await waitFor(() => expect(screen.getByText(/已有提案/)).toBeTruthy());
    const target = proposalsFx.proposals[0];
    fireEvent.click(screen.getByLabelText(`删除提案 ${target.proposal_id}`));
    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.method === "DELETE" && c.url.includes(`/experiment-proposals/${target.proposal_id}`),
        ),
      ).toBe(true),
    );
  });

  it("每个提案都有独立的删除按钮（N 个提案 = N 个删除入口）", async () => {
    stub();
    render(<ExperimentsView />);
    await waitFor(() => expect(screen.getByText(/已有提案/)).toBeTruthy());
    for (const item of proposalsFx.proposals) {
      expect(screen.getByLabelText(`删除提案 ${item.proposal_id}`)).toBeTruthy();
    }
  });
});
