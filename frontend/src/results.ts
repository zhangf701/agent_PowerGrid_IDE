/** 工具结果 → 结构化展示项（**数据适配层**，F-4 接线的核心）。
 *
 *  ★ 为什么需要：对话里的数值与编号此前只是**模型的自述**。实测模型会把
 *    **数组位置当成母线编号**（报「0.943 pu @ 母线 78」，而直接读数组是
 *    `bus_numbers[75] = 76`），且语气确定、只在被提示时才做对。
 *    故数值与标识符必须由**代码**从工具结果里取出，经 `Quantity` / `Identifier` 渲染。
 *
 *  ★ 本层是 `measure()` 的**唯一调用点**（§4.4：把判据从 N 个渲染点收敛到
 *    **1 个可审计、可加运行时校验、可写单测**的适配点）。
 *
 *  ⚠️ **两条硬约束**：
 *    ① **只覆盖有真实样本的形状**（潮流 / N-1，夹具取自运行中的网关）。
 *       认不出的形状 → 返回空数组 —— **绝不猜**。
 *    ② **不猜编号约定**（§4.5）：未实测的输出标 `unknown`（渲染成「约定未知」），
 *       而不是套用引擎级默认值 —— 那是「语气确定的假声明」。
 */
import { deriveConvention, measure, type Convention, type ResultItem } from "./components";

/** 结果摘要的形状（由网关 `_result_excerpt()` 产出）。
 *
 *  ★ **内层 JSON 由网关解析**（不是前端解）—— 否则 MCP 包装的 `content[0].text`
 *    会把 JSON **二次转义**，实测膨胀 ~59%（23 KB 结果 → 36.5 KB 摘要，顶破上限）。
 */
interface Excerpt {
  is_error?: boolean;
  /** MCP 且内层是 JSON（**已解析成对象**） */
  inner?: unknown;
  /** MCP 且内层是纯文本 */
  text?: string;
  /** 非 MCP 包装的结果，原样 */
  raw?: unknown;
  __truncated__?: true;
  __unserializable__?: true;
}

/** 取出可结构化的语义载荷。取不到 → `null`（**不猜**）。
 *
 *  ⚠️ 三种「取不到」都要如实返回 null，而不是拿别的东西顶替：
 *    截断（`__truncated__`）/ 纯文本 / 形状不认识。
 */
export function unwrapMcpResult(result: unknown): unknown | null {
  if (result === null || typeof result !== "object") return null;
  const o = result as Excerpt;
  if (o.__truncated__ || o.__unserializable__) return null;
  if (o.inner !== undefined) return o.inner;
  if (o.raw !== undefined) return o.raw;
  if (typeof o.text === "string") return null; // 纯文本结果无法结构化
  return null;
}

/** ★ 母线标识符的约定 = **按「输出」查表**（`tokens.json#identifierConvention.byOutput`）。
 *
 *  **F-5（2026-09-26 实测裁定）**：约定是「输出」的属性，不是「引擎」的属性 ——
 *  - `surge.run_ac_power_flow.bus_numbers` = **1-based**（case118 实测：1…118，源文件编号）；
 *  - `surge.run_n1_branch_contingency.bus_number` = **1-based**（case118 N-1 出现 118，
 *    0-based 最大只能是 117 —— 决定性）；
 *  - 而 surge 的**矩阵索引**是 0-based（case30 PTDF/LODF）—— 同引擎、不同输出、不同约定。
 *
 *  故此处**不再硬编码**（首版曾硬编码 `BUS_CONVENTION="1-based"`，会把 pandapower
 *  这类 0-based 引擎的潮流结果也标错），而是按 `server.tool.field` 查真源表；
 *  未实测的输出 → `unknown` → 界面渲染「(约定未知)」—— 宁可未知，不可猜错。
 */
function busConvention(server: string, tool: string, field: string): Convention {
  return deriveConvention(undefined, `${server}.${tool}.${field}`);
}

/** 潮流结果里电压的判据单位（有量纲量：单位即判据，无需 criterion）。 */
const PF_SHAPES = new Set(["run_ac_power_flow", "run_power_flow", "run_dc_power_flow"]);

function extremeIndex(values: unknown[], mode: "min" | "max"): number {
  let best = -1;
  let bestVal = mode === "min" ? Infinity : -Infinity;
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    // ⚠️ 网关会把 NaN/Infinity 消毒成 null —— 必须跳过，不能当成 0
    if (typeof v !== "number" || !Number.isFinite(v)) continue;
    if (mode === "min" ? v < bestVal : v > bestVal) {
      bestVal = v;
      best = i;
    }
  }
  return best;
}

/** 潮流结果 → 收敛 / 最低电压 / 最高电压（后两者带**母线标识符**，约定按输出查表）。 */
function extractPowerFlow(inner: unknown, server: string, tool: string): ResultItem[] {
  const source = `${server}.${tool}`;
  const r = (inner as { results?: Record<string, unknown> } | null)?.results;
  if (!r) return [];
  const vm = r.vm;
  const buses = r.bus_numbers;
  if (!Array.isArray(vm) || !Array.isArray(buses) || vm.length !== buses.length) return [];

  const conv = busConvention(server, tool, "bus_numbers");
  const items: ResultItem[] = [];
  if (typeof r.converged === "boolean") {
    items.push({
      label: "收敛",
      text: r.converged ? `是（${String(r.iterations ?? "?")} 次迭代）` : "否",
    });
  }
  const iMin = extremeIndex(vm, "min");
  const iMax = extremeIndex(vm, "max");
  if (iMin >= 0) {
    items.push({
      label: "最低电压",
      value: measure(vm[iMin], { unit: "pu" }, source),
      ref: { id: buses[iMin] as number, convention: conv, kind: "bus" },
    });
  }
  if (iMax >= 0) {
    items.push({
      label: "最高电压",
      value: measure(vm[iMax], { unit: "pu" }, source),
      ref: { id: buses[iMax] as number, convention: conv, kind: "bus" },
    });
  }
  return items;
}

/** N-1 结果 → 场景数 / 越限 / Top-1 最重载支路。 */
function extractN1(inner: unknown, source: string): ResultItem[] {
  const r = (inner as { results?: Record<string, unknown> } | null)?.results;
  if (!r || typeof r.n_contingencies !== "number" || !Array.isArray(r.results)) return [];

  const items: ResultItem[] = [
    { label: "场景数", text: `${r.n_contingencies}（收敛 ${String(r.n_converged ?? "?")}）` },
    { label: "越限", text: `${String(r.n_with_violations ?? "?")} 个场景 / ${String(r.n_violations ?? "?")} 条` },
  ];

  // Top-1 = max_loading_pct 最大者
  let top: Record<string, unknown> | null = null;
  for (const e of r.results as Record<string, unknown>[]) {
    const p = e?.max_loading_pct;
    if (typeof p !== "number" || !Number.isFinite(p)) continue;
    if (!top || p > (top.max_loading_pct as number)) top = e;
  }
  if (top) {
    items.push({
      label: "最重载（Top-1）",
      // ★ 判据必须是 **MVA** —— 用 MW 会把 142% 看成 98%（项目实测陷阱）
      value: measure(top.max_loading_pct as number, { unit: "%", criterion: "MVA" }, source),
      text: `${String(top.contingency_id)}（${String(top.label)}）`,
    });
  }
  return items;
}

/** 从一次工具调用的事件 payload 里抽出可结构化呈现的项。
 *
 *  ⚠️ 认不出的形状 → `[]`（**不猜**）。新增形状时**必须**同时加真实夹具与测试。
 */
export function extractResults(
  server: string,
  tool: string,
  resultExcerpt: unknown,
): ResultItem[] {
  const inner = unwrapMcpResult(resultExcerpt);
  if (inner === null) return [];
  const source = `${server}.${tool}`;
  if (PF_SHAPES.has(tool)) return extractPowerFlow(inner, server, tool);
  if (tool === "run_n1_branch_contingency") return extractN1(inner, source);
  return [];
}
