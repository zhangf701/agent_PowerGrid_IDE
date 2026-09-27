/** ⑥ 校验层三块面板的测试（跨引擎一致性 · 能力矩阵 · IR 检查器）。
 *
 *  ★ 夹具来源：
 *    - `contracts-t0.json` / `servers.json` / `case-diagnostics.json` —— **从运行中的网关抓取**（2026-09-27）；
 *    - 「带条目的诊断」没有真实样本（手头算例诊断全空）—— 渲染测试用**按
 *      `powerio.diagnostic_record` 源码字段集构造**的合成对象，并在用例里注明；
 *      真实空列表夹具负责证明 schema 与真实网关兼容。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import casesFx from "./__fixtures__/gateway/cases.json";
import t0Fx from "./__fixtures__/gateway/contracts-t0.json";
import diagFx from "./__fixtures__/gateway/case-diagnostics.json";
import serversFx from "./__fixtures__/gateway/servers.json";
import { CapabilityMatrixPanel, CrossEnginePanel, IrInspectorPanel } from "./components";
import { measure } from "./components";
import { crossEngineComparisons } from "./results";

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

/* ─────────────── CapabilityMatrixPanel（§5.3）─────────────── */

describe("CapabilityMatrixPanel", () => {
  function stubT0() {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/servers")) return json(serversFx);
        if (url.includes("/contracts/t0")) return json(t0Fx);
        return json({ detail: "not found" }, 404);
      }),
    );
  }

  it("★ 9 个引擎一行一个；契约状态来自 t0 findings（本次运行评估）", async () => {
    stubT0();
    render(<CapabilityMatrixPanel />);
    await waitFor(() => expect(screen.getByTestId("capability-matrix")).toBeInTheDocument());
    for (const s of serversFx.servers) {
      expect(screen.getByText(s)).toBeInTheDocument();
    }
    // 契约 2 对 andes 是 satisfied（真实夹具），对 genx 是 degraded
    const text = screen.getByTestId("capability-matrix").textContent ?? "";
    expect(text).toContain("满足");
    expect(text).toContain("降级");
    // 静态能力列有 surge 的 N-1 标注；文档知识声明必须在页面上
    expect(text).toContain("PTDF·LODF·OTDF·ATC");
    expect(text).toContain("文档知识");
    expect(text).toContain("不是");
  });

  it("★ findings 里没有的 server（powerio）显示「无记录」，不显示成正常（空集 ≠ satisfied）", async () => {
    stubT0();
    render(<CapabilityMatrixPanel />);
    await waitFor(() => expect(screen.getByTestId("capability-matrix")).toBeInTheDocument());
    const powerioRow = screen.getByText("powerio").closest("tr")!;
    expect(powerioRow.textContent).toContain("无记录");
  });

  it("fetch 失败 → 错误可见（不白屏）", async () => {
    vi.stubGlobal("fetch", vi.fn(() => json({ detail: "boom" }, 500)));
    render(<CapabilityMatrixPanel />);
    await waitFor(() => expect(screen.getByText(/boom/)).toBeInTheDocument());
  });
});

/* ─────────────── IrInspectorPanel（§5.4）─────────────── */

describe("IrInspectorPanel", () => {
  function stubDiag(overrides: Record<string, () => Promise<Response>> = {}) {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        for (const [key, handler] of Object.entries(overrides)) {
          if (url.includes(key)) return handler();
        }
        if (url.includes("/cases/")) return json(diagFx);
        if (url.includes("/cases")) return json(casesFx);
        return json({ detail: "not found" }, 404);
      }),
    );
  }

  async function pickAndRun() {
    await waitFor(() => expect(screen.getByLabelText("选择算例")).toBeInTheDocument());
    const id = casesFx.cases[0].id;
    fireEvent.change(screen.getByLabelText("选择算例"), { target: { value: id } });
    fireEvent.click(screen.getByRole("button", { name: "跑诊断" }));
    await waitFor(() => expect(screen.getByTestId("ir-inspector").textContent).toMatch(/解析于|错误|失败|事故/));
    return id;
  }

  it("★ 真实诊断夹具（零诊断）：value_type + status 原文 + counts 如实显示", async () => {
    stubDiag();
    render(<IrInspectorPanel />);
    await pickAndRun();
    const text = screen.getByTestId("ir-inspector").textContent ?? "";
    expect(text).toContain("powerio.BalancedNetwork");
    expect(text).toContain("ok: no diagnostics");
    expect(text).toContain("错误 0");
    expect(text).toContain("错误 0 · 警告 0");
  });

  it("★ 未解析的算例 → 网关 409 的 detail 原样可见（不吞错误）", async () => {
    stubDiag({
      "/cases/": () =>
        json({ detail: "算例尚未解析 —— 请先在算例库执行解析" }, 409),
    });
    render(<IrInspectorPanel />);
    await pickAndRun();
    expect(screen.getByTestId("ir-inspector").textContent).toContain("算例尚未解析");
  });

  it("★ 诊断条目按 severity 排序（error → warning → remark → note）；建议与 target 可见", async () => {
    // ⚠️ 合成数据：字段集核实自 powerio `diagnostic_record()` 源码（code/severity/message/target
    //    恒在 + suggested_action 可选）；真实网关样本是空列表（上一用例）。
    const withEntries = {
      ...diagFx,
      result: {
        ...diagFx.result,
        summary: { ...diagFx.result.summary, text: "2 errors, 1 warning", counts: { error: 2, warning: 1, remark: 0, note: 0 } },
        diagnostics: [
          { code: "PIO-W-001", severity: "warning", message: "w", target: "loads[3]" },
          { code: "PIO-E-002", severity: "error", message: "e2", target: "buses[7]", suggested_action: "补齐 qmax" },
          { code: "PIO-E-001", severity: "error", message: "e1", target: "buses[5]" },
          { code: "PIO-N-001", severity: "note", message: "n", target: "*" },
        ],
      },
    };
    stubDiag({ "/cases/": () => json(withEntries) });
    render(<IrInspectorPanel />);
    await pickAndRun();
    const codes = [...screen.getByTestId("ir-inspector").querySelectorAll("[data-testid='ir-diagnostic']")].map(
      (el) => el.querySelector(".font-mono")!.textContent,
    );
    expect(codes).toEqual(["PIO-E-001", "PIO-E-002", "PIO-W-001", "PIO-N-001"]);
    expect(screen.getByTestId("ir-inspector").textContent).toContain("补齐 qmax");
  });
});

/* ─────────────── CrossEnginePanel（§6.3 前瞻规格）─────────────── */

describe("CrossEnginePanel", () => {
  it("★ 同算例配对 → Δ 显示 + 「满足」徽章（图标 + 文字，非纯色）", () => {
    const rows = [
      {
        server: "pandapower",
        tool: "run_power_flow",
        seq: 1,
        args: { file_path: "D:/data/case39.m" },
        results: [{ label: "最低电压", value: measure(0.982, { unit: "pu" }, "a") }],
      },
      {
        server: "surge",
        tool: "run_ac_power_flow",
        seq: 2,
        args: { file_path: "D:/data/case39.m" },
        results: [{ label: "最低电压", value: measure(0.9820001, { unit: "pu" }, "b") }],
      },
    ];
    render(<CrossEnginePanel comparisons={crossEngineComparisons(rows)} />);
    const text = screen.getByTestId("cross-engine-panel").textContent ?? "";
    expect(text).toContain("Δ");
    expect(text).toContain("满足");
    expect(text).toContain("0.982 pu");
    expect(text).toContain("1e-4"); // ★ 阈值显式声明
  });

  it("★ 算例标识缺失 → 判定是「无法判定」，不是拍一个结论", () => {
    const rows = [
      {
        server: "pandapower",
        tool: "run_power_flow",
        seq: 1,
        args: null,
        results: [{ label: "最低电压", value: measure(0.982, { unit: "pu" }, "a") }],
      },
      {
        server: "surge",
        tool: "run_ac_power_flow",
        seq: 2,
        args: null,
        results: [{ label: "最低电压", value: measure(0.9820001, { unit: "pu" }, "b") }],
      },
    ];
    render(<CrossEnginePanel comparisons={crossEngineComparisons(rows)} />);
    expect(screen.getByTestId("cross-engine-panel").textContent).toContain("无法判定");
  });

  it("空配对 → 引导文案（说明数据从哪来）", () => {
    render(<CrossEnginePanel comparisons={[]} />);
    expect(document.body.textContent).toContain("跨引擎结果");
  });
});
