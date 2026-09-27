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
import ppFx from "./__fixtures__/gateway/result-power-flow-pp.json";
import n1Fx from "./__fixtures__/gateway/result-n1.json";
import { ResultSummary, ToolCallRow, ViolationTable } from "./components";
import {
  crossEngineComparisons,
  extractResults,
  extractViolations,
  unwrapMcpResult,
} from "./results";
import { measure } from "./components";

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

/* ─────────────── extractResults —— pandapower 潮流形状（真实夹具，2026-09-27）─────────────── */

describe("extractResults —— pandapower 形状（bus_results 键控字典）", () => {
  // ★ 张老师真机测试坐实的缺口：pp 的潮流结果没有 vm/bus_numbers 数组，
  //   而是 bus_results.vm_pu 键控字典（键 "0".."38"）—— 首版只认 surge 形状，
  //   跨引擎一致性面板因此配不上对。
  const items = extractResults("pandapower", "run_power_flow", ppFx);

  it("最低电压 0.982 @ 键 30；最高电压 1.0636 @ 键 35（与 surge 同算例实测一致）", () => {
    expect(items.find((i) => i.label === "最低电压")!.value!.value).toBeCloseTo(0.982, 6);
    expect(items.find((i) => i.label === "最低电压")!.ref!.id).toBe(30);
    expect(items.find((i) => i.label === "最高电压")!.value!.value).toBeCloseTo(1.0636, 6);
    expect(items.find((i) => i.label === "最高电压")!.ref!.id).toBe(35);
  });

  it("★ 编号约定 = 0-based，来自 byOutput 新条目（键含 \"0\"、39 条母线 → 决定性）", () => {
    expect(items.find((i) => i.label === "最低电压")!.ref!.convention).toBe("0-based");
  });

  it("收敛 = 是（pp 形状无迭代数字段，不臆造）", () => {
    const c = items.find((i) => i.label === "收敛")!;
    expect(c.text).toBe("是");
  });

  it("键含非正整数 / 非有限值 → 跳过；两个形状都不认识 → 空数组", () => {
    const weird = {
      is_error: false,
      inner: { results: { bus_results: { vm_pu: { "0": 1.0, x: 2.0, "-1": 3.0, NaN: null } } } },
    };
    const items = extractResults("pandapower", "run_power_flow", weird);
    expect(items.find((i) => i.label === "最低电压")!.ref!.id).toBe(0);
    expect(extractResults("pandapower", "run_dc_power_flow", { is_error: false, inner: { foo: 1 } })).toEqual([]);
  });
});

/* ─────────────── crossEngineComparisons —— caseKey 继承（run 调用无参）─────────────── */

describe("crossEngineComparisons —— caseKey 继承（张老师真机场景）", () => {
  const load = (server: string, seq: number, file: string) => ({
    server,
    tool: server === "surge" ? "load_network" : "load_network_from_any",
    seq,
    args: { file_path: file },
    results: undefined,
  });

  it("★ load 带路径 + run 无参 → run 的 caseKey 继承自同引擎最近载入，正常配对并给判定", () => {
    const rows = [
      load("pandapower", 1, "D:/data/case39.m"),
      load("surge", 2, "D:/data/case39.m"),
      {
        server: "surge",
        tool: "run_ac_power_flow",
        seq: 3,
        args: {},
        results: [{ label: "最低电压", value: measure(0.982, { unit: "pu" }, "s") }],
      },
      {
        server: "pandapower",
        tool: "run_power_flow",
        seq: 4,
        args: null,
        results: [{ label: "最低电压", value: measure(0.982, { unit: "pu" }, "p") }],
      },
    ];
    const out = crossEngineComparisons(rows);
    expect(out).toHaveLength(1);
    expect(out[0].caseKey).toContain("case39.m");
    expect(out[0].caseVerified).toBe(true);
    expect(out[0].caseKeyInherited).toBe(true);
    expect(out[0].consistent).toBe(true);
  });

  it("★ 两引擎最近载入的是**不同**算例 → 永不配对（继承也不能跨算例）", () => {
    const rows = [
      load("pandapower", 1, "D:/data/case39.m"),
      load("surge", 2, "D:/data/case118.m"),
      {
        server: "surge",
        tool: "run_ac_power_flow",
        seq: 3,
        args: {},
        results: [{ label: "最低电压", value: measure(0.943, { unit: "pu" }, "s") }],
      },
      {
        server: "pandapower",
        tool: "run_power_flow",
        seq: 4,
        args: null,
        results: [{ label: "最低电压", value: measure(0.982, { unit: "pu" }, "p") }],
      },
    ];
    expect(crossEngineComparisons(rows)).toHaveLength(0);
  });

  it("★ 继承按引擎隔离：surge 载过、pandapower 从未载 → **不配对**（一方算例未知就不能比）", () => {
    const rows = [
      load("surge", 1, "D:/data/case39.m"),
      {
        server: "surge",
        tool: "run_ac_power_flow",
        seq: 2,
        args: {},
        results: [{ label: "最低电压", value: measure(0.982, { unit: "pu" }, "s") }],
      },
      {
        server: "pandapower",
        tool: "run_power_flow",
        seq: 3,
        args: null,
        results: [{ label: "最低电压", value: measure(0.982, { unit: "pu" }, "p") }],
      },
    ];
    // surge 侧继承到 case39，pandapower 侧算例未知 → 两项分属不同 caseKey 组、
    // 各自单引擎 → 全部丢弃。宁可不比，不可不知算例就比（错误的一致性结论比慢更危险）。
    expect(crossEngineComparisons(rows)).toHaveLength(0);
  });
});

/* ─────────────── N-1 violations 结构化（⑥ 校验层配套）────────────── */

describe("extractViolations —— 真实 N-1 夹具（52 条）", () => {
  const rows = extractViolations("surge", "run_n1_branch_contingency", n1Fx);

  it("★ 条数 = 52（与 results.violations 数组一致，不丢不重）", () => {
    const raw = (
      n1Fx as { inner: { results: { violations: unknown[] } } }
    ).inner.results.violations;
    expect(rows).toHaveLength(raw.length);
    expect(rows).toHaveLength(52);
  });

  it("★ 排序：第 1 条 = branch_26 的 161.84% 热越限（Top-1 必须在最前）", () => {
    expect(rows[0].contingencyId).toBe("branch_26");
    expect(rows[0].type).toBe("ThermalOverload");
    expect(rows[0].loading!.value).toBeCloseTo(161.836, 2);
    expect((rows[0].loading as unknown as { criterion: string }).criterion).toBe("MVA");
  });

  it("★ 热越限行的位置 = 支路两端，且编号约定 **1-based**（F-5 延伸：from_bus/to_bus 已入 byOutput）", () => {
    expect(rows[0].branch!.from).toBe(23);
    expect(rows[0].branch!.to).toBe(24);
    expect(rows[0].branch!.convention).toBe("1-based");
    expect(rows[0].bus).toBeUndefined();
  });

  it("★ 热越限给出 flow / limit MVA（§7.2：说「超限」必须同时给出限值与实测值）", () => {
    expect(rows[0].flowMva!.value).toBeCloseTo(971.017, 2);
    expect(rows[0].limitMva!.value).toBeCloseTo(600.0, 6);
  });

  it("★ 电压违规带母线标识 + 限值；单位 pu", () => {
    const vh = rows.find((r) => r.contingencyId === "branch_4" && r.type === "VoltageHigh")!;
    expect(vh.bus!.id).toBe(25);
    expect(vh.bus!.convention).toBe("1-based");
    expect(vh.vm!.value).toBeCloseTo(1.06193, 5);
    expect(vh.vmLimit).toBeCloseTo(1.06, 6);
    expect(vh.loading).toBeUndefined(); // 电压违规没有负载率 —— 字段按类型可空
  });

  it("★ 母线违规行不臆造支路（bus_number 与 from/to 互斥时按真实字段取）", () => {
    const islanding = rows.filter((r) => r.type === "Islanding");
    expect(islanding.length).toBeGreaterThan(0);
    for (const r of islanding) {
      expect(r.bus).toBeUndefined();
      expect(r.branch).toBeUndefined();
    }
  });

  it("★ 电压违规的排序幅度 = |vm − vm_limit|（High/Low 同一把尺子）", () => {
    const vh = rows.find((r) => r.contingencyId === "branch_4" && r.type === "VoltageHigh")!;
    const vl = rows.find((r) => r.contingencyId === "branch_19" && r.type === "VoltageLow")!;
    expect(vh.vm!.value - vh.vmLimit!).toBeCloseTo(0.00193, 5);
    expect(vl.vmLimit! - vl.vm!.value).toBeCloseTo(0.00317, 5);
    // branch_19 的低压越限幅度更大 → 在 branch_4 高压越限之前
    expect(rows.indexOf(vl)).toBeLessThan(rows.indexOf(vh));
  });

  it("认不出的形状 → 空数组（不猜）", () => {
    expect(extractViolations("surge", "run_n1_branch_contingency", pfFx)).toEqual([]);
    expect(extractViolations("surge", "run_n1_branch_contingency", null)).toEqual([]);
    expect(
      extractViolations("surge", "run_n1_branch_contingency", { is_error: false, inner: {} }),
    ).toEqual([]);
  });
});

describe("ViolationTable 渲染", () => {
  const rows = extractViolations("surge", "run_n1_branch_contingency", n1Fx);

  it("★ 默认截断到 10 条且**截断必须可见**（共 52 条 · 显示前 10）", () => {
    render(<ViolationTable items={rows} />);
    const text = screen.getByTestId("violation-table").textContent ?? "";
    expect(text).toContain("共 52 条");
    expect(text).toContain("前 10 条");
    expect(screen.getAllByTestId("violation-table").length).toBe(1);
  });

  it("★ 类型列 = 中文标签 + 引擎原文（颜色不单独承载信息）", () => {
    render(<ViolationTable items={rows.slice(0, 1)} />);
    const text = screen.getByTestId("violation-table").textContent ?? "";
    expect(text).toContain("热越限");
    expect(text).toContain("ThermalOverload");
    expect(text).toContain("超限"); // Quantity 的 alarm 文字
    expect(text).toContain("(1-based)");
  });

  it("空 items → 不渲染", () => {
    const { container } = render(<ViolationTable items={[]} />);
    expect(container.textContent).toBe("");
  });
});

/* ─────────────── crossEngineComparisons（跨引擎一致性，§6.3）─────────────── */

describe("crossEngineComparisons —— 跨引擎配对", () => {
  const rowsFor = (file?: string) => [
    {
      server: "pandapower",
      tool: "run_power_flow",
      seq: 1,
      args: file ? { file_path: file } : null,
      results: [
        { label: "最低电压", value: measure(0.982, { unit: "pu" }, "pandapower.run_power_flow") },
      ],
    },
    {
      server: "surge",
      tool: "run_ac_power_flow",
      seq: 2,
      args: file ? { file_path: file } : null,
      results: [
        { label: "最低电压", value: measure(0.9820001, { unit: "pu" }, "surge.run_ac_power_flow") },
      ],
    },
  ];

  it("★ 同算例 + 同指标 + 同单位 → 配对，Δ 与 consistent 都有", () => {
    const out = crossEngineComparisons(rowsFor("D:/data/case39.m"));
    expect(out).toHaveLength(1);
    expect(out[0].label).toBe("最低电压");
    expect(out[0].caseKey).toContain("case39.m");
    expect(out[0].caseVerified).toBe(true);
    expect(out[0].consistent).toBe(true);
    expect(out[0].delta).toBeCloseTo(1e-7, 9);
    // ★ §6.3：按 seq 排序（pandapower seq=1 在前）
    expect(out[0].entries[0].server).toBe("pandapower");
  });

  it("★ 算例不同 → 永不配对（错误的一致性结论比慢更危险）", () => {
    const rows = [
      rowsFor("D:/data/case39.m")[0],
      { ...rowsFor("D:/data/case118.m")[1] },
    ];
    expect(crossEngineComparisons(rows)).toHaveLength(0);
  });

  it("★ 参数里没有算例标识 → 仍配对，但 caseVerified=false（Δ 照显，不给判定）", () => {
    const out = crossEngineComparisons(rowsFor());
    expect(out).toHaveLength(1);
    expect(out[0].caseKey).toBeNull();
    expect(out[0].caseVerified).toBe(false);
    expect(out[0].consistent).toBe(true); // 数值上算出一致，但界面必须显示「无法判定」
  });

  it("★ 相对偏差超阈值 → consistent=false", () => {
    const rows = [
      {
        server: "pandapower",
        tool: "run_power_flow",
        seq: 1,
        args: { file_path: "c.m" },
        results: [{ label: "最大过载", value: measure(142, { unit: "%", criterion: "MVA" }, "a") }],
      },
      {
        server: "pypsa",
        tool: "run_power_flow",
        seq: 2,
        args: { file_path: "c.m" },
        results: [{ label: "最大过载", value: measure(98, { unit: "%", criterion: "MVA" }, "b") }],
      },
    ];
    const out = crossEngineComparisons(rows);
    expect(out[0].consistent).toBe(false);
    expect(out[0].relative).toBeGreaterThan(0.3);
  });

  it("单引擎结果不成组；label/单位/判据不同不成组", () => {
    const rows = [
      {
        server: "pandapower",
        tool: "run_power_flow",
        seq: 1,
        args: null,
        results: [{ label: "最低电压", value: measure(0.98, { unit: "pu" }, "a") }],
      },
      {
        server: "surge",
        tool: "run_ac_power_flow",
        seq: 2,
        args: null,
        results: [{ label: "最高电压", value: measure(0.98, { unit: "pu" }, "b") }],
      },
    ];
    expect(crossEngineComparisons(rows)).toHaveLength(0);
  });
});
