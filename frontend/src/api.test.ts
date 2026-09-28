/** 入站结构校验（UI 规范 v2 §8.4）的测试。
 *
 *  ★ 最重要的一条：**真实网关响应必须通过 schema** ——
 *    夹具是从运行中的网关抓的，不是手写的想象字段。schema 写错会在这里先红。
 *  ★ 反向断言：结构漂移必须抛 `SchemaDriftError` 并**指出路径**（否则用户只看到"失败"）。
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import envFx from "./__fixtures__/gateway/environment.json";
import skillsFx from "./__fixtures__/gateway/skills.json";
import casesFx from "./__fixtures__/gateway/cases.json";
import parseFx from "./__fixtures__/gateway/case-parse.json";
import t0Fx from "./__fixtures__/gateway/contracts-t0.json";
import diagFx from "./__fixtures__/gateway/case-diagnostics.json";
import serversFx from "./__fixtures__/gateway/servers.json";
import {
  CaseDiagnosticsSchema,
  CaseParseResponseSchema,
  CaseRegisterResponseSchema,
  CasesResponseSchema,
  EnvironmentSchema,
  SchemaDriftError,
  ServersResponseSchema,
  SkillsResponseSchema,
  T0ReportSchema,
  apiParsed,
} from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("真实响应能通过 schema（夹具取自运行中的网关）", () => {
  it("/environment 通过；且 llm.required_env 缺失时**不得**判为漂移", () => {
    const r = EnvironmentSchema.safeParse(envFx);
    expect(r.success).toBe(true);
    // ★ 回归：先前该字段被写成必填 → LLM 未配置时那一栏 .join() 抛 TypeError（白屏）
    expect(envFx.llm).not.toHaveProperty("required_env");
    if (r.success) expect(r.data.llm.required_env).toBeUndefined();
  });

  it("/skills 通过，22 个技能 / 10 个带触发表", () => {
    const r = SkillsResponseSchema.safeParse(skillsFx);
    expect(r.success).toBe(true);
    if (r.success) {
      expect(r.data.skills).toHaveLength(22);
      expect(r.data.summary?.with_escalation).toBe(10);
      // ★ 健康度如实为 unknown —— 界面不得把它渲染成"正常"
      expect(r.data.health?.level).toBe("unknown");
    }
  });

  it("/cases 通过；含一个**围笼外**算例（within_allowed_roots=false）", () => {
    const r = CasesResponseSchema.safeParse(casesFx);
    expect(r.success).toBe(true);
    if (r.success) {
      expect(r.data.cases).toHaveLength(2);
      // ★ 这两条是 ② 算例库要呈现的核心事实，夹具必须真的覆盖到
      expect(r.data.cases.filter((c) => !c.within_allowed_roots)).toHaveLength(1);
      expect(r.data.summary.unreadable_by_servers).toBe(1);
    }
  });

  it("/cases/{id}/parse 通过（一次调用即含提示所需全部字段）", () => {
    const r = CaseParseResponseSchema.safeParse(parseFx);
    expect(r.success).toBe(true);
    if (r.success) {
      expect(r.data.has_ir).toBe(true);
      expect(r.data.ir_bytes).toBeGreaterThan(0);
    }
  });

  it("/cases 的坏元素能被定位到具体算例", () => {
    const drifted = {
      ...casesFx,
      cases: [{ ...casesFx.cases[0], within_allowed_roots: "no" }],
    };
    const r = CasesResponseSchema.safeParse(drifted);
    expect(r.success).toBe(false);
    if (!r.success) {
      expect(r.error.issues[0].path.join(".")).toBe("cases.0.within_allowed_roots");
    }
  });

  it("登记响应：`path_normalized` 可缺省（干净路径不得报已归一化）", () => {
    const clean = { created: true, case: casesFx.cases[0] };
    expect(CaseRegisterResponseSchema.safeParse(clean).success).toBe(true);
    const normalized = { ...clean, path_normalized: ["剥离首尾引号"] };
    const r = CaseRegisterResponseSchema.safeParse(normalized);
    expect(r.success).toBe(true);
    if (r.success) expect(r.data.path_normalized).toEqual(["剥离首尾引号"]);
  });

  it("/servers 通过（9 个 server id）", () => {
    const r = ServersResponseSchema.safeParse(serversFx);
    expect(r.success).toBe(true);
    if (r.success) expect(r.data.servers).toHaveLength(9);
  });

  it("/contracts/t0 通过；findings 与事件流 ContractFinding 同形（含 state —— 双轨汇总的输入）", () => {
    const r = T0ReportSchema.safeParse(t0Fx);
    expect(r.success).toBe(true);
    if (r.success) {
      expect(r.data.findings.length).toBeGreaterThan(0);
      expect(r.data.summary.primary).toBe("degraded");
      // ★ 38 条 finding 必须全带 state（缺了它就进不了双轨汇总）
      for (const f of r.data.findings) expect(f.state).toBeTruthy();
    }
  });

  it("/cases/{id}/diagnostics 通过（真实样本 = 零诊断的 case118）", () => {
    const r = CaseDiagnosticsSchema.safeParse(diagFx);
    expect(r.success).toBe(true);
    if (r.success) {
      expect(r.data.stale).toBe(false);
      expect(r.data.result.summary.status).toBe("ok");
      expect(r.data.result.diagnostics).toHaveLength(0);
    }
  });
});

describe("结构漂移必须响亮且可定位", () => {
  it("缺字段 → SchemaDriftError，issues 指出字段路径", () => {
    const drifted = { ...envFx, gateway: { python: "3.12.6" } };
    const r = EnvironmentSchema.safeParse(drifted);
    expect(r.success).toBe(false);
    if (!r.success) {
      const paths = r.error.issues.map((i) => i.path.join("."));
      expect(paths).toContain("gateway.python_ok");
    }
  });

  it("类型错 → 不通过（字符串冒充布尔）", () => {
    const drifted = { ...envFx, gateway: { python: "3.12.6", python_ok: "yes" } };
    expect(EnvironmentSchema.safeParse(drifted).success).toBe(false);
  });

  it("非对象（null / 字符串）→ 不通过，且定位到根", () => {
    for (const bad of [null, "boom", 42]) {
      const r = EnvironmentSchema.safeParse(bad);
      expect(r.success).toBe(false);
      if (!r.success) expect(r.error.issues[0].path).toHaveLength(0);
    }
  });

  it("skills 数组里的单个坏元素能被定位", () => {
    const drifted = {
      ...skillsFx,
      skills: [{ id: "a", name: "a", kind: "tool" }, { id: 1, name: "b", kind: "tool" }],
    };
    const r = SkillsResponseSchema.safeParse(drifted);
    expect(r.success).toBe(false);
    if (!r.success) expect(r.error.issues[0].path.join(".")).toBe("skills.1.id");
  });
});

describe("apiParsed 的失败语义", () => {
  const okResponse = (body: unknown) =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

  it("HTTP 200 但结构漂移 → SchemaDriftError（不能静默进状态树）", async () => {
    vi.stubGlobal("fetch", vi.fn(() => okResponse({ gateway: {} })));
    await expect(apiParsed("/environment", EnvironmentSchema)).rejects.toBeInstanceOf(
      SchemaDriftError,
    );
  });

  it("★ 200 但响应不是 JSON（dev 代理漏路径回落 HTML）→ 普通 Error 且**给排查线索**（2026-09-27 实测）", async () => {
    // 张老师真机踩中：/servers 漏在 vite proxy 正则外 → vite 回落 index.html（200 + HTML）
    // → 旧实现把字符串传给 schema → 报「可能已漂移」，把排查方向带偏（网关根本没被请求到）。
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response("<!doctype html><html>…", {
            status: 200,
            headers: { "Content-Type": "text/html" },
          }),
        ),
      ),
    );
    const err = await apiParsed("/servers", ServersResponseSchema).catch((e) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err).not.toBeInstanceOf(SchemaDriftError); // 不是 schema 漂移 —— 措辞不能误导
    expect(String(err.message)).toContain("不是 JSON");
    expect(String(err.message)).toContain("dev 代理");
  });

  it("★ 守卫：vite dev 代理必须覆盖前端会请求的每一条网关路径（/servers 曾漏）", async () => {
    const { GATEWAY_PREFIXES } = await import("./gatewayPaths");
    const covered: readonly string[] = GATEWAY_PREFIXES;
    // 前端实际请求的全部网关路径前缀（新增端点时必须同步加进 gatewayPaths.ts）
    for (const p of [
      "health",
      "environment",
      "skills",
      "servers",
      "cases",
      "experiments",
      "experiment-proposals",
      "contracts",
      "sessions",
      "modules",
      "checks",
    ]) {
      expect(covered, `dev 代理缺少 "${p}"（dev 下会回落 index.html，表现为「响应不是 JSON」）`).toContain(p);
    }
  });

  it("HTTP 错误 → 普通 Error，**不是** SchemaDriftError（两类失败用户动作不同）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("boom", { status: 500 }))),
    );
    const err = await apiParsed("/environment", EnvironmentSchema).catch((e) => e);
    expect(err).toBeInstanceOf(Error);
    expect(err).not.toBeInstanceOf(SchemaDriftError);
    expect(String(err.message)).toContain("/environment");
  });

  it("★ 空响应体的 5xx → 明确指向「网关没在跑」（dev 代理连不上时的返回）", async () => {
    // ★ Vite 的 http-proxy 在目标 ECONNREFUSED（网关没起）时返回 **500 + 空体**。
    //   裸报一个空 detail（「HTTP 500：」）会让用户完全无法判断是网关没起还是代码坏了
    //   —— 2026-09-27 张老师真机测试踩中。
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response("", { status: 500 }))));
    const err = await apiParsed("/environment", EnvironmentSchema).catch((e) => e);
    expect(err).toBeInstanceOf(Error);
    expect(String(err.message)).toContain("网关没在跑");
    expect(String(err.message)).toContain("8765");
    expect(String(err.message)).toContain("run_gateway.sh");
  });

  it("结构正确 → 返回解析后的数据", async () => {
    vi.stubGlobal("fetch", vi.fn(() => okResponse(envFx)));
    const env = await apiParsed("/environment", EnvironmentSchema);
    expect(env.gateway.python_ok).toBe(true);
  });
});
