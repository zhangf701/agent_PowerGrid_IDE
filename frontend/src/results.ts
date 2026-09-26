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
import { measure, type Convention, type ResultItem } from "./components";

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

/** ★ `bus_numbers` / `bus_number` 的编号约定 = **1-based**（源文件编号）。
 *
 *  **实测证据（2026-09-26）**：
 *  - `case118` 的 `run_ac_power_flow` → `bus_numbers` = 1…118（118 条）；
 *  - `case118` 的 `run_n1_branch_contingency` → `bus_number` **出现 118**
 *    （0-based 的最大值只能是 117，故 118 是决定性证据）。
 *
 *  ⚠️⚠️ **这**不是** tokens 里写的 `byEngine.surge = "0-based"`** ——
 *    spec 的依据是「case30 PTDF/LODF 实测（索引 12/15/33 与 pandapower 一致）」，
 *    那说的是**矩阵索引**；而母线号是**源文件编号**。⇒ **约定是按「输出」的，不是按「引擎」的**
 *    （见 F-5）。冻结的 `byEngine` 表表达不了这件事，故此处**显式传 convention 且不传 engine**
 *    （传 engine 会因与 `byEngine` 冲突而按 §4.5 抛错 —— 那正是该守卫在起作用）。
 *
 *  ⚠️ **边界**：只对 **MATPOWER 源**实测过。其他源格式（PSS/E `.raw` 等）需另行实测，
 *    未实测前不应套用此值。
 */
export const BUS_CONVENTION: Convention = "1-based";

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

/** 潮流结果 → 收敛 / 最低电压 / 最高电压（后两者带**母线标识符**）。 */
function extractPowerFlow(inner: unknown, source: string): ResultItem[] {
  const r = (inner as { results?: Record<string, unknown> } | null)?.results;
  if (!r) return [];
  const vm = r.vm;
  const buses = r.bus_numbers;
  if (!Array.isArray(vm) || !Array.isArray(buses) || vm.length !== buses.length) return [];

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
      ref: { id: buses[iMin] as number, convention: BUS_CONVENTION, kind: "bus" },
    });
  }
  if (iMax >= 0) {
    items.push({
      label: "最高电压",
      value: measure(vm[iMax], { unit: "pu" }, source),
      ref: { id: buses[iMax] as number, convention: BUS_CONVENTION, kind: "bus" },
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
  if (PF_SHAPES.has(tool)) return extractPowerFlow(inner, source);
  if (tool === "run_n1_branch_contingency") return extractN1(inner, source);
  return [];
}
