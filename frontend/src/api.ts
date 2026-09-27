/** 网关 API 访问 + **入站结构校验**（UI 规范 v2 §8.4，强制）。
 *
 *  ★ 为什么必须校验：`JSON.parse` 返回 `any`，**编译期守卫在运行时全部穿透**。
 *    网关字段一旦漂移（改名 / 变 null / 类型变），会**直达 React 状态树 → 白屏**，
 *    而且整个会话反复触发。故入站数据必须经 `safeParse` 后才允许进入状态树。
 *
 *  ★ 校验范围 = **真正进入状态树的字段**（不是全量镜像后端响应）。
 *    未被消费的字段不校验 —— 它们不影响渲染，要求它们只会让 schema 无谓变脆。
 *
 *  ★ 失败语义：抛 `SchemaDriftError`，由调用方渲染成 **`incident` 签名**的错误横幅。
 *    - 不静默丢弃（等于 fail-open，用户以为有保护实际没有）；
 *    - 不白屏（一次性请求，不是 SSE 长流 —— §8.4 的「禁止 throw」是针对**流**的，
 *      流里 throw 会炸掉整条连接；请求/响应路径上抛给调用方的 try/catch 是既定模式）。
 *
 *  ★ 夹具：`src/__fixtures__/gateway/*.json` 是**从真实网关抓取**的响应，
 *    测试用它们验证「真实响应能通过 schema」—— 防止 schema 写的是想象中的字段。
 */

import { z } from "zod";

import type { SseFrame } from "./sse";

/** 最小 markdown 渲染：先 esc 防注入，再只认 **粗体** 与 `代码`（与 MVP 同口径）。 */
export function md(s: string): string {
  return esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+?)`/g, "<code>$1</code>");
}

export function esc(s: string): string {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!,
  );
}

/** 响应结构与前端契约不符 —— 属于 `incident`（本可判定却拿不到），必须升级可见。 */
export class SchemaDriftError extends Error {
  readonly path: string;
  readonly issues: readonly string[];

  constructor(path: string, issues: readonly string[]) {
    super(
      `${path} → 响应结构与前端契约不符（网关字段可能已漂移）：${issues.join("；")}`,
    );
    this.name = "SchemaDriftError";
    this.path = path;
    this.issues = issues;
  }
}

/** 裸传输层：错误必须在界面上可见（MVP 判据），故把失败翻译成带上下文的 Error 抛出。 */
export async function api<T>(path: string, opts?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(path, opts);
  } catch (e) {
    throw new Error(`无法连接网关（${path}）：${(e as Error).message}。网关起了吗？`);
  }
  const text = await resp.text();
  let body: unknown = null;
  let notJson = false;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    notJson = true;
  }
  if (!resp.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : text.slice(0, 300);
    throw new Error(`${path} → HTTP ${resp.status}：${detail}`);
  }
  // ★ 200 却不是 JSON：几乎总是 **dev 代理没覆盖该路径**（vite 回落 index.html，
  //   2026-09-27 实测：/servers 漏在代理正则外 → 能力矩阵面板「! 事故 expected object,
  //   received string」）。这不是「网关字段漂移」（schema 漂移的措辞会误导排查方向），
  //   单独报，给可操作的排查线索。
  if (notJson && text) {
    throw new Error(
      `${path} → 响应不是 JSON（HTTP ${resp.status}）。常见原因：dev 代理` +
        `（frontend/vite.config.ts 的 proxy 正则）未覆盖该路径，或网关未启动返回了 HTML 页。` +
        `响应开头：${text.slice(0, 100)}`,
    );
  }
  return body as T;
}

/** ★ 唯一允许进入状态树的入口：传输 + `safeParse`。 */
export async function apiParsed<T>(
  path: string,
  schema: z.ZodType<T>,
  opts?: RequestInit,
): Promise<T> {
  const body = await api<unknown>(path, opts);
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    throw new SchemaDriftError(
      path,
      parsed.error.issues.slice(0, 4).map((i) => {
        const where = i.path.length ? i.path.join(".") : "(根)";
        return `${where}: ${i.message}`;
      }),
    );
  }
  return parsed.data;
}

/* ══════════════════ /environment ══════════════════ */

export const EnvironmentSchema = z.object({
  gateway: z.object({ python: z.string(), python_ok: z.boolean() }),
  powermcp: z.object({ root_ok: z.boolean() }),
  llm: z.object({
    configured: z.boolean(),
    model: z.string().optional(),
    endpoint: z.string().optional(),
    /** ⚠️ 真实 `/environment` **不回传**该字段（2026-09-26 用真实响应夹具实测）——
     *  故必须声明为可选。先前把它写成必填，导致「LLM 未配置」那一栏会在
     *  `required_env.join()` 上抛 TypeError（白屏），只因当时 LLM 恰好已配置才未暴露。 */
    required_env: z.array(z.string()).optional(),
  }),
  paths: z.object({ set: z.boolean(), roots: z.array(z.string()) }),
  modules: z.object({ enabled: z.array(z.string()), failed: z.array(z.string()) }),
});
export type Environment = z.infer<typeof EnvironmentSchema>;

/* ══════════════════ /skills ══════════════════ */

export const EscalationSchema = z.object({
  observation: z.string(),
  escalate_to: z.string(),
});

export const SkillSchema = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.string(),
  description: z.string().optional(),
  escalation: z.array(EscalationSchema).optional(),
});

export const SkillsResponseSchema = z.object({
  skills: z.array(SkillSchema),
  summary: z
    .object({
      total: z.number().optional(),
      by_kind: z.record(z.string(), z.number()).optional(),
      with_escalation: z.number().optional(),
    })
    .optional(),
  health: z
    .object({
      level: z.string().optional(),
      signals: z
        .object({
          escalation_missing: z.array(z.string()).optional(),
          dangling_escalation: z.array(z.string()).optional(),
          orphan_playbooks: z.array(z.string()).optional(),
        })
        .optional(),
    })
    .optional(),
});
export type SkillsResponse = z.infer<typeof SkillsResponseSchema>;
export type Skill = z.infer<typeof SkillSchema>;
export type SkillEscalation = z.infer<typeof EscalationSchema>;

/* ══════════════════ /cases（② 算例库）══════════════════ */

/** 单个算例。★ 只声明**视图真正消费**的字段 —— 未消费的字段（`notes` / `current_sha256`）
 *  不进 schema，避免无谓变脆；`available` / `drift` / `within_allowed_roots` 是**服务端现算**的，
 *  前端**不得缓存**（存下来的「文件还在」会过期，而过期的「还在」比不报更危险 —— §4.7.2 硬规则 1）。 */
export const CaseSchema = z.object({
  id: z.string(),
  label: z.string(),
  source_path: z.string(),
  format: z.string(),
  size: z.number(),
  sha256: z.string(),
  registered_at: z.string(),
  /** 源文件**现在**是否可读 */
  available: z.boolean(),
  /** 文件在、但内容与登记时不同 */
  drift: z.boolean(),
  /** server 子进程**能否读到它** */
  within_allowed_roots: z.boolean(),
  current_size: z.number().nullable().optional(),
});

export const CasesResponseSchema = z.object({
  cases: z.array(CaseSchema),
  summary: z.object({
    total: z.number(),
    available: z.number(),
    drifted: z.number(),
    unreadable_by_servers: z.number(),
  }),
  allowed_roots: z.array(z.string()),
  index_exists: z.boolean(),
});

/** `POST /cases` —— `path_normalized` 只在**确实改动过**路径时出现（网关侧不静默修正）。 */
export const CaseRegisterResponseSchema = z.object({
  created: z.boolean(),
  case: CaseSchema,
  path_normalized: z.array(z.string()).optional(),
  path_used: z.string().optional(),
});

/** `POST /cases/{id}/parse` —— ★ 用它**一次调用**即可拿到提示所需全部字段
 *  （`value_type` / `ir_bytes` / `has_ir`），不必再打 `/ir`（后者会回 52KB 全文）。 */
export const CaseParseResponseSchema = z.object({
  case_id: z.string(),
  value_type: z.string(),
  ir_bytes: z.number(),
  has_ir: z.boolean(),
});

export const CaseUnregisterResponseSchema = z.object({
  unregistered: z.string(),
  label: z.string(),
  /** ★ 数据安全底线：注销**只删索引条目**，源文件保留 */
  source_file_kept: z.boolean(),
});

export type Case = z.infer<typeof CaseSchema>;
export type CasesResponse = z.infer<typeof CasesResponseSchema>;
export type CaseParseResponse = z.infer<typeof CaseParseResponseSchema>;
export type CaseUnregisterResponse = z.infer<typeof CaseUnregisterResponseSchema>;

/* ══════════════════ 会话（③ 对话分析）══════════════════ */

export const SessionSchema = z.object({
  id: z.string(),
  servers: z.array(z.string()),
});
export type Session = z.infer<typeof SessionSchema>;

/* ────────────────── SSE 入站校验（UI 规范 §8.4，强制）──────────────────
 *
 * ★ 为什么这一处**最**需要校验：SSE 是**长连接流式推送**，网关字段一旦漂移，
 *   坏数据会**反复**直达状态树。而 `JSON.parse` 返回 `any`，编译期守卫在运行时全穿透。
 * ★ 失败语义（§8.4 原文要求）：
 *   - **不 throw** —— 流里 throw 会炸掉整条连接（用户丢掉整轮回答）；
 *   - **不静默丢弃** —— 静默 = fail-open，用户以为有保护实际没有；
 *   - **降级为 incident** —— 渲染成可见的 `! 事故` 标记，流继续。
 */

function issuesOf(err: z.ZodError): string[] {
  return err.issues
    .slice(0, 3)
    .map((i) => `${i.path.length ? i.path.join(".") : "(根)"}: ${i.message}`);
}

type Decoded<T> = { ok: true; value: T } | { ok: false; issues: string[] };

function decode<T>(data: string, schema: z.ZodType<T>): Decoded<T> {
  let raw: unknown;
  try {
    raw = JSON.parse(data);
  } catch (e) {
    return { ok: false, issues: [`JSON 解析失败：${(e as Error).message}`] };
  }
  const r = schema.safeParse(raw);
  return r.success ? { ok: true, value: r.data } : { ok: false, issues: issuesOf(r.error) };
}

/* ── `/chat` 的帧：`event:` 名 = 对话事件 kind ── */

const ChatTextFrame = z.object({ text: z.string() });
const ChatDetailFrame = z.object({ detail: z.string() });
const ChatToolCallFrame = z.object({
  server: z.string(),
  tool: z.string(),
  args: z.record(z.string(), z.unknown()),
});
const ChatToolErrorFrame = z.object({
  server: z.string(),
  tool: z.string(),
  detail: z.string(),
});

export type ChatFrame =
  | { kind: "text"; text: string }
  | { kind: "final"; text: string }
  | { kind: "notice"; detail: string }
  | { kind: "error"; detail: string }
  | { kind: "tool_call"; server: string; tool: string; args: Record<string, unknown> }
  | { kind: "tool_error"; server: string; tool: string; detail: string }
  /** 已知 kind 但结构不符 —— **降级为 incident**，不炸流 */
  | { kind: "malformed"; rawKind: string; issues: string[] }
  /** 前端未覆盖的新 kind —— 保留原样（前向兼容），由校验层计数 */
  | { kind: "unknown"; rawKind: string };

export function parseChatFrame(frame: SseFrame): ChatFrame {
  const { event, data } = frame;
  const bad = (issues: string[]): ChatFrame => ({ kind: "malformed", rawKind: event, issues });

  switch (event) {
    case "text":
    case "final": {
      const d = decode(data, ChatTextFrame);
      return d.ok ? { kind: event, text: d.value.text } : bad(d.issues);
    }
    case "notice":
    case "error": {
      const d = decode(data, ChatDetailFrame);
      return d.ok ? { kind: event, detail: d.value.detail } : bad(d.issues);
    }
    case "tool_call": {
      const d = decode(data, ChatToolCallFrame);
      return d.ok ? { kind: "tool_call", ...d.value } : bad(d.issues);
    }
    case "tool_error": {
      const d = decode(data, ChatToolErrorFrame);
      return d.ok ? { kind: "tool_error", ...d.value } : bad(d.issues);
    }
    default:
      return { kind: "unknown", rawKind: event };
  }
}

/* ── `/sessions/{sid}/events` 的帧：`event:` 名 = 通道，`data:` 是包装 ── */

export const EvidenceEventSchema = z.object({
  seq: z.number(),
  kind: z.string(),
  payload: z.record(z.string(), z.unknown()),
  at: z.string(),
});
export type EvidenceEvent = z.infer<typeof EvidenceEventSchema>;

/** 契约 finding —— 与 `/contracts/t0` **同形**（`ContractFinding` 的 `asdict`）。
 *  ★ 必须保留 `state`：`summarize()` 的输入 —— 缺了它的裸字典无法参与双轨汇总，
 *    主徽标永远不会因它变红（又是静默 fail-open）。 */
export const ContractFindingSchema = z.object({
  contract: z.number(),
  state: z.string(),
  reason: z.string().nullable(),
  subject: z.string(),
  detail: z.string(),
  evidence: z.record(z.string(), z.unknown()),
});
export type ContractFinding = z.infer<typeof ContractFindingSchema>;

const ToolCallPayload = z.object({
  server: z.string(),
  tool: z.string(),
  args: z.record(z.string(), z.unknown()),
  /** ★ 结果摘要（F-4 接线）—— 供前端做**结构化结果呈现**。
   *  ⚠️ 必须**显式声明**：`z.object` 默认**剥掉**未知键，漏了它摘要会被静默丢弃，
   *     界面就退回到「转述模型自述」，而实测模型会标错母线编号。 */
  result_excerpt: z.unknown().optional(),
});
const ToolErrorPayload = z.object({
  server: z.string(),
  tool: z.string(),
  error: z.string(),
});
const InventoryDegradedPayload = z.object({
  failures: z.array(z.object({ server: z.string(), error: z.string() })),
});

export type Evidence =
  | {
      kind: "tool_call";
      seq: number;
      server: string;
      tool: string;
      args: Record<string, unknown>;
      /** 结果摘要（供结构化结果呈现；可能缺省或为截断标记） */
      resultExcerpt?: unknown;
    }
  | { kind: "tool_error"; seq: number; server: string; tool: string; error: string }
  | { kind: "contract_violation"; seq: number; finding: ContractFinding }
  | { kind: "contract_unknown"; seq: number; finding: ContractFinding }
  | { kind: "inventory_degraded"; seq: number; failures: { server: string; error: string }[] }
  | { kind: "unknown"; seq: number; rawKind: string }
  | { kind: "malformed"; seq: number; rawKind: string; issues: string[] };

/** 按 `kind` 分派并校验 payload。未知 kind → `unknown`（前向兼容，**不**当畸形）。 */
export function parseEvidence(ev: EvidenceEvent): Evidence {
  const bad = (issues: string[]): Evidence => ({
    kind: "malformed",
    seq: ev.seq,
    rawKind: ev.kind,
    issues,
  });

  switch (ev.kind) {
    case "tool_call": {
      const r = ToolCallPayload.safeParse(ev.payload);
      return r.success
        ? {
            kind: "tool_call",
            seq: ev.seq,
            server: r.data.server,
            tool: r.data.tool,
            args: r.data.args,
            resultExcerpt: r.data.result_excerpt,
          }
        : bad(issuesOf(r.error));
    }
    case "tool_error": {
      const r = ToolErrorPayload.safeParse(ev.payload);
      return r.success ? { kind: "tool_error", seq: ev.seq, ...r.data } : bad(issuesOf(r.error));
    }
    case "contract_violation":
    case "contract_unknown": {
      const r = ContractFindingSchema.safeParse(ev.payload);
      return r.success
        ? { kind: ev.kind, seq: ev.seq, finding: r.data }
        : bad(issuesOf(r.error));
    }
    case "inventory_degraded": {
      const r = InventoryDegradedPayload.safeParse(ev.payload);
      return r.success
        ? { kind: "inventory_degraded", seq: ev.seq, failures: r.data.failures }
        : bad(issuesOf(r.error));
    }
    default:
      return { kind: "unknown", seq: ev.seq, rawKind: ev.kind };
  }
}

/** 解析一帧 `/events` 的 `data:`（包装层）。坏帧 → `null`（不炸流）。 */
export function parseEvidenceFrame(data: string): Evidence | null {
  const d = decode(data, EvidenceEventSchema);
  return d.ok ? parseEvidence(d.value) : null;
}

/* ══════════════════ ⑥ 校验层三块（§5.2/§5.3/§5.4）══════════════════
 *
 *  ⚠️ 本块必须在 `ContractFindingSchema` **之后**（`T0ReportSchema` 复用同一 schema，
 *  放在前面会因 const 暂时性死区在模块加载时直接 ReferenceError）。 */

/** `GET /servers` —— 9 个开源 server id（能力矩阵的行）。 */
export const ServersResponseSchema = z.object({
  servers: z.array(z.string()),
});
export type ServersResponse = z.infer<typeof ServersResponseSchema>;

/** `GET /contracts/t0` —— findings 与事件流里的 `ContractFinding` **同形**（复用同一 schema）。 */
export const T0ReportSchema = z.object({
  cache_key: z.string(),
  evaluated_at: z.string(),
  summary: z.object({
    primary: z.string(),
    structural_unknown: z.number(),
    incident_unknown: z.number(),
  }),
  findings: z.array(ContractFindingSchema),
});
export type T0Report = z.infer<typeof T0ReportSchema>;

/** powerio 单条诊断（字段集核实自 `powerio.diagnostic_record` 源码，2026-09-27）：
 *  `code` / `severity` / `message` / `target` 恒在；其余按需出现。 */
export const DiagnosticRecordSchema = z.object({
  code: z.string(),
  severity: z.string(),
  message: z.string(),
  target: z.string(),
  id: z.string().optional(),
  suggested_action: z.string().optional(),
  details: z.string().nullable().optional(),
  related: z.array(z.string()).optional(),
  spans: z
    .array(
      z.object({
        source: z.string(),
        byte_start: z.number(),
        byte_end: z.number(),
      }),
    )
    .optional(),
});
export type DiagnosticRecord = z.infer<typeof DiagnosticRecordSchema>;

/** `GET /cases/{id}/diagnostics`（真实响应夹具 `case-diagnostics.json`）。 */
export const CaseDiagnosticsSchema = z.object({
  case_id: z.string(),
  value_type: z.string().nullable(),
  parsed_at: z.string().nullable(),
  /** 源文件在解析后又变过 → 诊断结论来自旧数据（网关现算比对） */
  stale: z.boolean(),
  result: z.object({
    value_type: z.string().nullable().optional(),
    summary: z.object({
      status: z.string(),
      counts: z.object({
        error: z.number(),
        warning: z.number(),
        remark: z.number(),
        note: z.number(),
      }),
      text: z.string(),
    }),
    diagnostics: z.array(DiagnosticRecordSchema),
  }),
});
export type CaseDiagnostics = z.infer<typeof CaseDiagnosticsSchema>;


