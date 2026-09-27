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
import {
  deriveConvention,
  measure,
  type Convention,
  type Measured,
  type ResultItem,
} from "./components";

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

/** 潮流结果 → 收敛 / 最低电压 / 最高电压（后两者带**母线标识符**，约定按输出查表）。
 *
 *  ⚠️ 两种**真实形状**（都有网关夹具，2026-09-27）：
 *    - A（surge `run_ac_power_flow`）：`vm` 数组 + `bus_numbers` 数组（1-based 母线号）；
 *    - B（pandapower `run_power_flow`）：`bus_results.vm_pu` = **键控字典**，键 `"0".."N-1"`
 *      （0-based 母线索引，无 bus_numbers 数组）—— 首版只认 A，跨引擎一致性面板因此
 *      配不上对（张老师真机测试坐实）。认不出 → []（不猜）。
 */
function extractPowerFlow(inner: unknown, server: string, tool: string): ResultItem[] {
  const source = `${server}.${tool}`;
  const r = (inner as { results?: Record<string, unknown> } | null)?.results;
  if (!r) return [];

  const items: ResultItem[] = [];
  const pushExtreme = (
    entries: { bus: number; vm: number }[],
    convention: Convention,
  ) => {
    if (!entries.length) return false;
    let iMin = 0;
    let iMax = 0;
    for (let i = 1; i < entries.length; i += 1) {
      if (entries[i].vm < entries[iMin].vm) iMin = i;
      if (entries[i].vm > entries[iMax].vm) iMax = i;
    }
    items.push({
      label: "最低电压",
      value: measure(entries[iMin].vm, { unit: "pu" }, source),
      ref: { id: entries[iMin].bus, convention, kind: "bus" },
    });
    items.push({
      label: "最高电压",
      value: measure(entries[iMax].vm, { unit: "pu" }, source),
      ref: { id: entries[iMax].bus, convention, kind: "bus" },
    });
    return true;
  };

  /* 形状 A：vm + bus_numbers 平行数组（surge） */
  const vm = r.vm;
  const buses = r.bus_numbers;
  if (Array.isArray(vm) && Array.isArray(buses) && vm.length === buses.length) {
    const conv = busConvention(server, tool, "bus_numbers");
    if (typeof r.converged === "boolean") {
      items.push({
        label: "收敛",
        text: r.converged ? `是（${String(r.iterations ?? "?")} 次迭代）` : "否",
      });
    }
    const entries: { bus: number; vm: number }[] = [];
    for (let i = 0; i < vm.length; i += 1) {
      // ⚠️ 网关会把 NaN/Infinity 消毒成 null —— 必须跳过，不能当成 0
      if (typeof vm[i] !== "number" || !Number.isFinite(vm[i])) continue;
      entries.push({ bus: buses[i] as number, vm: vm[i] as number });
    }
    pushExtreme(entries, conv);
    return items;
  }

  /* 形状 B：bus_results.vm_pu 键控字典（pandapower，键 = 0-based 索引） */
  const busResults = r.bus_results as Record<string, Record<string, unknown>> | undefined;
  const vmByBus = busResults?.vm_pu;
  if (vmByBus && typeof vmByBus === "object" && !Array.isArray(vmByBus)) {
    const conv = busConvention(server, tool, "bus_results");
    if (typeof r.converged === "boolean") {
      items.push({ label: "收敛", text: r.converged ? "是" : "否" });
    }
    const entries: { bus: number; vm: number }[] = [];
    for (const [k, v] of Object.entries(vmByBus)) {
      const idx = Number(k);
      if (!Number.isInteger(idx) || idx < 0) continue; // 键不是非负整数 → 不猜
      if (typeof v !== "number" || !Number.isFinite(v)) continue;
      entries.push({ bus: idx, vm: v });
    }
    pushExtreme(entries, conv);
    return items;
  }

  return [];
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

/* ────────────────── 跨引擎一致性配对（⑥ 校验层 · §6.3 前瞻规格）────────────────── */

/** 跨引擎配对后的可比组。 */
export interface CrossEngineEntry {
  server: string;
  /** 事件序号 —— ★ §6.3：并发到达顺序不确定，必须靠单调序列号排序后再渲染 */
  seq: number;
  /** 原始 Measured（**不再复制**——渲染组件直接用它，杜绝绕过 `measure()` 品牌的旁路） */
  measured: Measured;
}

export interface CrossEngineComparison {
  label: string;
  unit: string;
  criterion?: string;
  /** 从参数里提取的算例标识（文件路径等）；`null` = 参数里找不到可比对标识 */
  caseKey: string | null;
  /** ★ caseKey 不是本调用自己的参数，而是继承自该 server 会话内**最近一次载入** ——
   *  `run_*` 类调用通常无参（操作已载入的网络），此时用载入调用的路径补全 */
  caseKeyInherited: boolean;
  entries: CrossEngineEntry[];
  /** 最大 − 最小（`entries` ≥ 2 时存在） */
  delta: number;
  /** 相对偏差 = Δ / max|value|（全 0 时为 0） */
  relative: number;
  /** ★ 相对偏差 ≤ 1e-4 才判「一致」—— 阈值是**显式声明**的，不是隐含的 */
  consistent: boolean;
  /** 算例一致性是否核实过 —— `false` 时 Δ **只展示**，不给出一致性判定（不猜） */
  caseVerified: boolean;
}

/** 一致性阈值：相对偏差 ≤ 1e-4。
 *  ★ 依据：case118 跨引擎实测 Δ = 2.0e-06 pu（有可解释的保真度损失）——
 *    判「一致」不应要求机器精度；而工程上有意义的电压差异 ≥ 1e-3 pu。
 *    1e-4 介于两者之间：吸收数值噪声，放过真差异。**阈值必须在界面上随判定一起写出**。 */
export const CONSISTENCY_TOLERANCE = 1e-4;

/** 参数里寻找算例标识的键（大小写不敏感子串匹配）。⚠️ 白名单制 —— 认不出的键不猜。 */
const CASE_ARG_KEYS = ["file", "path", "case"];

function caseKeyOf(args?: Record<string, unknown> | null): string | null {
  if (!args) return null;
  const found: string[] = [];
  for (const [k, v] of Object.entries(args)) {
    const lk = k.toLowerCase();
    if (CASE_ARG_KEYS.some((s) => lk.includes(s)) && typeof v === "string" && v.trim()) {
      found.push(v.trim());
    }
  }
  // 多个候选标识取字典序拼接 —— 保证同一组参数得到同一把钥匙
  return found.length ? found.sort().join("|") : null;
}

/** 从会话工具轨迹里配出**跨引擎**的同名同单位可比组。
 *
 *  ★ 只配 `rows` 里的 **Measured** 项（label + unit + criterion 全同才算同一指标）；
 *  ★ `caseKey` 不同的**永不配对**（跨算例比较 = 错误的一致性结论，比慢更危险）；
 *  ★ **caseKey 继承**：`run_*` 类调用通常无参（操作会话池里已载入的网络）——
 *    按 seq 顺序记录每个 server **最近一次**带算例路径的调用，为其后的无参调用补全
 *    caseKey（`caseKeyInherited=true`）。这与会话池的真实状态一致；从未载入过可识别
 *    路径的 server 仍落 `caseVerified: false` —— 不猜。
 *  ★ 单引擎组不是比较 —— 直接丢弃（只回跨引擎组）。
 */
export function crossEngineComparisons(
  rows: { server: string; tool: string; seq: number; args?: Record<string, unknown> | null; results?: ResultItem[] }[],
): CrossEngineComparison[] {
  type Key = string;
  const groups = new Map<
    Key,
    {
      label: string;
      unit: string;
      criterion?: string;
      caseKey: string | null;
      caseKeyInherited: boolean;
      entries: CrossEngineEntry[];
    }
  >();

  // ★ 预扫描（按 seq 升序）：每个 server 的「会话内最近载入」算例标识
  const ordered = [...rows].sort((a, b) => a.seq - b.seq);
  const lastCaseByServer = new Map<string, string>();
  const caseKeyOfRow = (row: (typeof ordered)[number]): { key: string | null; inherited: boolean } => {
    const own = caseKeyOf(row.args);
    if (own) {
      lastCaseByServer.set(row.server, own);
      return { key: own, inherited: false };
    }
    const prev = lastCaseByServer.get(row.server);
    return { key: prev ?? null, inherited: prev !== undefined };
  };

  for (const row of ordered) {
    // ★ 载入调用（无 results）也必须推进 lastCaseByServer —— 先更新状态，再过滤
    const { key: ck, inherited } = caseKeyOfRow(row);
    if (!row.results) continue;
    for (const it of row.results) {
      if (!it.value) continue; // 纯文本 / 标识符项不可比
      const m = it.value;
      const key = `${it.label}|${m.unit}|${m.criterion ?? ""}|${ck ?? "?"}`;
      if (!groups.has(key)) {
        groups.set(key, {
          label: it.label,
          unit: m.unit,
          criterion: m.criterion,
          caseKey: ck,
          caseKeyInherited: inherited,
          entries: [],
        });
      }
      groups.get(key)!.entries.push({ server: row.server, seq: row.seq, measured: m });
    }
  }

  const out: CrossEngineComparison[] = [];
  for (const g of groups.values()) {
    const servers = new Set(g.entries.map((e) => e.server));
    if (servers.size < 2) continue; // 单引擎，无可比性
    // ★ §6.3：按 seq 排序后再渲染（到达顺序不可信）
    g.entries.sort((a, b) => a.seq - b.seq);
    const vals = g.entries.map((e) => e.measured.value);
    const delta = Math.max(...vals) - Math.min(...vals);
    const scale = Math.max(...vals.map(Math.abs));
    const relative = scale === 0 ? 0 : delta / scale;
    out.push({
      label: g.label,
      unit: g.unit,
      criterion: g.criterion,
      caseKey: g.caseKey,
      caseKeyInherited: g.caseKeyInherited,
      entries: g.entries,
      delta,
      relative,
      consistent: relative <= CONSISTENCY_TOLERANCE,
      caseVerified: g.caseKey !== null,
    });
  }
  // 确定输出顺序：先已核实算例的，再 Δ 大的在前
  out.sort((a, b) => Number(b.caseVerified) - Number(a.caseVerified) || b.delta - a.delta);
  return out;
}

/* ────────────────── N-1 violations 结构化（⑥ 校验层配套）────────────────── */

/** 单条 N-1 违规的结构化行。数值只能由 `measure()` 构造（单位 + 判据强制）。 */
export interface ViolationItem {
  /** 故障场景 id（如 `branch_26`） */
  contingencyId: string;
  /** 违规类型**原文**（引擎输出，如 `ThermalOverload`） */
  type: string;
  /** 位置 —— 母线违规时给出（约定按输出查表，未实测 → unknown） */
  bus?: { id: number; convention: Convention };
  /** 位置 —— 支路（热越限）时给出两端母线 */
  branch?: { from: number; to: number; convention: Convention };
  /** 负载率（% · MVA 判据） */
  loading?: Measured;
  /** 视在功率 / 限值（MVA）—— §7.2：说「超限」必须同时给出限值与实测值 */
  flowMva?: Measured;
  limitMva?: Measured;
  /** 电压（pu）与限值（pu） */
  vm?: Measured;
  vmLimit?: number;
}

/** 违规类型的中文标签 —— 原文始终保留（§7.1：引擎输出保留原文）。 */
export const VIOLATION_TYPE_LABEL: Record<string, string> = {
  ThermalOverload: "热越限",
  VoltageHigh: "电压越上限",
  VoltageLow: "电压越下限",
  Islanding: "孤岛",
  NonConvergent: "不收敛",
};

/** 有限数值才 measurable（网关已把 NaN 消毒成 null，这里防的是旧形状）。 */
function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** N-1 结果 → 结构化违规行（**排序确定**：热越限按负载率降序 → 电压按越限幅度降序 → 其余）。
 *
 *  ★ 排序必须在**数据层**做死（与渲染无关）：同一场景的多条违规在服务端按场景分组，
 *    直接渲染会把 Top-1 埋在中间 —— N-1 排序选题（`n1-ranking` 模块）的第一步就是它。
 *  ★ 电压的越限幅度 = |vm − vm_limit|：High 与 Low 用同一把尺子。
 *  ⚠️ 位置字段的编号约定**按输出查表**（F-5）：`bus_number` / `from_bus` / `to_bus`
 *    各查各的键 —— 实测覆盖前如实落 unknown，不猜。
 */
export function extractViolations(
  server: string,
  tool: string,
  resultExcerpt: unknown,
): ViolationItem[] {
  const inner = unwrapMcpResult(resultExcerpt);
  if (inner === null) return [];
  const source = `${server}.${tool}`;
  const r = (inner as { results?: Record<string, unknown> } | null)?.results;
  if (!r || !Array.isArray(r.violations)) return [];

  const conv = (field: string) => busConvention(server, tool, field);
  const items: ViolationItem[] = [];

  for (const raw of r.violations as Record<string, unknown>[]) {
    if (!raw || typeof raw !== "object") continue;
    const type = typeof raw.violation_type === "string" ? raw.violation_type : "?";
    const it: ViolationItem = { contingencyId: String(raw.contingency_id ?? "?"), type };

    // 位置：母线违规（bus_number）与支路违规（from/to_bus）二选一，字段按类型可空
    const bus = num(raw.bus_number);
    const from = num(raw.from_bus);
    const to = num(raw.to_bus);
    if (bus !== null) it.bus = { id: bus, convention: conv("bus_number") };
    if (from !== null && to !== null) {
      it.branch = { from, to, convention: conv("from_bus") };
    }

    const loading = num(raw.loading_pct);
    if (loading !== null) {
      it.loading = measure(loading, { unit: "%", criterion: "MVA" }, source);
    }
    const flow = num(raw.flow_mva);
    if (flow !== null) it.flowMva = measure(flow, { unit: "MVA" }, source);
    const limit = num(raw.limit_mva);
    if (limit !== null) it.limitMva = measure(limit, { unit: "MVA" }, source);
    const vm = num(raw.vm_pu);
    if (vm !== null) it.vm = measure(vm, { unit: "pu" }, source);
    const vmLimit = num(raw.vm_limit_pu);
    if (vmLimit !== null) it.vmLimit = vmLimit;

    items.push(it);
  }

  const severityRank = (it: ViolationItem): number => {
    if (it.loading) return it.loading.value; // 热越限：负载率即严重度
    if (it.vm && it.vmLimit != null) return Math.abs(it.vm.value - it.vmLimit) * 1000;
    return -1; // 孤岛 / 不收敛：无标量严重度，排后
  };
  items.sort((a, b) => severityRank(b) - severityRank(a));
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
