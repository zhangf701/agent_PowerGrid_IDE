/** 数据适配层 + 结构化结果呈现的测试（F-4 接线）。
 *
 *  ★ 最要紧的一条：**钉住 F-4 里模型答错的那个数** ——
 *    模型报「最低电压 0.943 pu @ 母线 78」，而直接读数组是 `bus_numbers[75] = 76`。
 *    适配层必须给出 **76**，且标注 **(1-based)**（不是 `byEngine` 里写的 0-based）。
 *  ★ 夹具 `result-power-flow.json` / `result-n1.json` 均**取自运行中的网关**。
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import pfFx from "./__fixtures__/gateway/result-power-flow.json";
import n1Fx from "./__fixtures__/gateway/result-n1.json";
import { ResultSummary, ToolCallRow } from "./components";
import { extractResults, unwrapMcpResult } from "./results";

afterEach(cleanup);

describe("unwrapMcpResult —— 摘要形状由网关产出（内层 JSON 已在网关解析）", () => {
  it("★ 双层编码已在网关拆掉：inner 直接是对象", () => {
    const inner = unwrapMcpResult({ is_error: false, inner: { a: 1 } });
    expect(inner).toEqual({ a: 1 });
  });

  it("非 MCP 包装 → raw 原样透传", () => {
    expect(unwrapMcpResult({ raw: { status: "ok" } })).toEqual({ status: "ok" });
  });

  it("截断 / 纯文本 / 非对象 → null（不抛、不猜）", () => {
    expect(unwrapMcpResult({ __truncated__: true, bytes: 99, keys: [] })).toBeNull();
    expect(unwrapMcpResult({ is_error: false, text: "纯文本结果" })).toBeNull();
    expect(unwrapMcpResult({})).toBeNull();
    expect(unwrapMcpResult(null)).toBeNull();
    expect(unwrapMcpResult("字符串")).toBeNull();
  });
});

describe("extractResults —— 潮流（真实夹具）", () => {
  const items = extractResults("surge", "run_ac_power_flow", pfFx);

  it("★ 最低电压 = 0.943 pu @ 母线 76（模型报的 78 是错的）", () => {
    const min = items.find((i) => i.label === "最低电压")!;
    expect(min).toBeDefined();
    expect(min.value!.value).toBeCloseTo(0.943, 6);
    expect(min.ref!.id).toBe(76); // ★ 不是 78
  });

  it("★ 编号约定 = **1-based**，来自 byOutput 查表（不是硬编码，也不是 byEngine 的 0-based）", () => {
    // F-5：约定按「输出」标注 —— 真源是 tokens.json#identifierConvention.byOutput
    expect(items.find((i) => i.label === "最低电压")!.ref!.convention).toBe("1-based");
  });

  it("★ 未实测的输出 → 约定 unknown（宁可未知，不可猜错 —— F-5 的反例：pandapower 是 0-based）", () => {
    // pandapower.run_power_flow 不在 byOutput 表里，且 byEngine.pandapower = 0-based ≠ 1-based
    const sample = {
      is_error: false,
      inner: { results: { converged: true, vm: [0.95, 1.01], bus_numbers: [1, 2] } },
    };
    const items = extractResults("pandapower", "run_power_flow", sample);
    expect(items.find((i) => i.label === "最低电压")!.ref!.convention).toBe("unknown");
  });

  it("最高电压 = 1.05 pu @ 母线 10", () => {
    const max = items.find((i) => i.label === "最高电压")!;
    expect(max.value!.value).toBeCloseTo(1.05, 6);
    expect(max.ref!.id).toBe(10);
  });

  it("收敛状态也在（纯文本，无单位故不走 Quantity）", () => {
    const c = items.find((i) => i.label === "收敛")!;
    expect(c.text).toMatch(/^是/);
    expect(c.value).toBeUndefined();
  });

  it("★ 数值全部经 measure() 构造（value 非空即带 source）", () => {
    for (const it of items) {
      if (it.value) expect(it.value.source).toBe("surge.run_ac_power_flow");
    }
  });
});

describe("extractResults —— N-1（真实夹具）", () => {
  const items = extractResults("surge", "run_n1_branch_contingency", n1Fx);

  it("场景数与越限条数", () => {
    expect(items.find((i) => i.label === "场景数")!.text).toBe("46（收敛 45）");
    expect(items.find((i) => i.label === "越限")!.text).toBe("23 个场景 / 52 条");
  });

  it("★ Top-1 最重载 = branch_26（Line 21->22），且判据是 **MVA**", () => {
    const top = items.find((i) => i.label === "最重载（Top-1）")!;
    expect(top.value!.value).toBeCloseTo(161.836, 2);
    expect(top.value!.unit).toBe("%");
    // ★ 判据必须是 MVA —— 用 MW 会把 142% 看成 98%（项目实测陷阱）
    expect((top.value as unknown as { criterion: string }).criterion).toBe("MVA");
    expect(top.text).toContain("branch_26");
    expect(top.text).toContain("Line 21->22");
  });
});

describe("extractResults —— 认不出就不猜", () => {
  it("未知工具 / 纯文本 / 未知形状 → 空数组", () => {
    expect(extractResults("surge", "compute_ptdf", pfFx)).toEqual([]);
    expect(extractResults("surge", "run_ac_power_flow", { is_error: false, text: "纯文本" })).toEqual([]);
    expect(extractResults("surge", "run_ac_power_flow", { is_error: false, inner: { foo: 1 } })).toEqual([]);
    expect(extractResults("surge", "run_ac_power_flow", null)).toEqual([]);
  });

  it("★ 含 null 的 vm（网关把 NaN 消毒成 null）不得被当成 0", () => {
    const sample = {
      is_error: false,
      inner: { results: { converged: true, vm: [null, 0.98, null, 1.02], bus_numbers: [1, 2, 3, 4] } },
    };
    const items = extractResults("surge", "run_ac_power_flow", sample);
    expect(items.find((i) => i.label === "最低电压")!.ref!.id).toBe(2);
    expect(items.find((i) => i.label === "最高电压")!.ref!.id).toBe(4);
  });

  it("vm 与 bus_numbers 长度不一致 → 不渲染（宁可没有，不可错配）", () => {
    const sample = {
      is_error: false,
      inner: { results: { vm: [1.0, 1.0], bus_numbers: [1, 2, 3] } },
    };
    expect(extractResults("surge", "run_ac_power_flow", sample)).toEqual([]);
  });
});

describe("ResultSummary 渲染", () => {
  const items = extractResults("surge", "run_ac_power_flow", pfFx);

  it("★ 数值带单位、标识符带编号约定，且标题声明「非模型转述」", () => {
    const { container } = render(<ResultSummary items={items} />);
    const text = container.textContent ?? "";
    expect(text).toContain("非");
    expect(text).toContain("模型转述");
    expect(text).toContain("0.943 pu");
    expect(text).toContain("(1-based)"); // ★ 不是 (0-based)
    expect(text).not.toContain("(0-based)");
    expect(text).toContain("76");
  });

  it("空 items → 不渲染（不占位、不噪声）", () => {
    const { container } = render(<ResultSummary items={[]} />);
    expect(container.textContent).toBe("");
  });

  it("★ 经 ToolCallRow 渲染时，结果块出现在工具行下方", () => {
    render(
      <ToolCallRow
        server="surge"
        tool="run_ac_power_flow"
        status="ok"
        args={{}}
        results={items}
      />,
    );
    expect(screen.getByTestId("result-summary")).toBeInTheDocument();
    expect(screen.getByTestId("tool-call-row")).toBeInTheDocument();
  });
});
