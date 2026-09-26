/** ③ 对话分析 + ⑥ 校验层（状态条部分）的测试。
 *
 *  ★ 三条最重要的：
 *    ① **真实 SSE 夹具必须能被解析**（`chat.sse` / `evidence.sse` 都是从运行中的网关抓的）；
 *    ② **按 `seq` 去重** —— 服务端不解析 `Last-Event-ID`，重连全量重放，不去重就重复计数；
 *    ③ **校验层三条硬规则** —— 折叠 ≠ 隐藏 · incident 必须升到状态条 · structural 不抢主徽标。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import chatSse from "./__fixtures__/gateway/chat.sse?raw";
import evidenceSse from "./__fixtures__/gateway/evidence.sse?raw";
import App from "./App";
import {
  parseChatFrame,
  parseEvidenceFrame,
  type ContractFinding,
} from "./api";
import {
  ContractBadge,
  ToolCallRow,
  VerificationLayer,
  summarizeFindings,
} from "./components";
import { drainFrames, parseAllFrames, parseFrameBlock } from "./sse";
import { applyChatFrame, type Turn } from "./views/ChatView";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/* ─────────────────── ① SSE 帧解析：用真实抓取的流 ─────────────────── */

describe("SSE 帧解析（真实夹具）", () => {
  it("真实 /chat 流 → 2 帧：text + final", () => {
    const frames = parseAllFrames(chatSse);
    expect(frames.map((f) => f.event)).toEqual(["text", "final"]);
    expect(parseChatFrame(frames[0])).toEqual({ kind: "text", text: "收到" });
    expect(parseChatFrame(frames[1])).toEqual({ kind: "final", text: "收到" });
    // /chat 无 id:
    expect(frames[0].id).toBeNull();
  });

  it("真实 /events 流 → 带 seq 的 evidence 帧（tool_call + contract_violation）", () => {
    const frames = parseAllFrames(evidenceSse);
    expect(frames.map((f) => f.event)).toEqual(["evidence", "evidence", "evidence"]);
    expect(frames.map((f) => f.id)).toEqual([1, 2, 3]);

    const evs = frames.map((f) => parseEvidenceFrame(f.data));
    expect(evs[0]).toMatchObject({ kind: "tool_call", seq: 1, server: "surge", tool: "load_network" });
    expect(evs[2]).toMatchObject({ kind: "contract_violation", seq: 3 });
    const f = (evs[2] as { finding: ContractFinding }).finding;
    // ★ finding 必须与 /contracts/t0 同形 —— 尤其要有 state（否则进不了双轨汇总）
    expect(f.contract).toBe(3);
    expect(f.state).toBe("violated");
    expect(f.subject).toBe("surge");
  });

  it("坏帧不抛、不毁流：缺 event / 缺 data / 非法 JSON 都只跳过该帧", () => {
    expect(parseFrameBlock("data: {}\n")).toBeNull();
    expect(parseFrameBlock("event: text\n")).toBeNull();
    expect(parseChatFrame({ event: "text", data: "{不是 JSON", id: null })).toMatchObject({
      kind: "malformed",
    });
    // 一帧坏 + 一帧好 → 好帧照样出来
    const { frames } = drainFrames("event: text\ndata: 垃圾\n\nevent: text\ndata: {\"text\":\"好\"}\n\n");
    expect(frames).toHaveLength(2);
  });

  it("未知 kind → unknown（前向兼容，不当畸形）", () => {
    expect(parseChatFrame({ event: "brand_new", data: "{}", id: null })).toEqual({
      kind: "unknown",
      rawKind: "brand_new",
    });
    expect(parseEvidenceFrame(JSON.stringify({ seq: 9, kind: "brand_new", payload: {}, at: "t" }))).toEqual({
      kind: "unknown",
      seq: 9,
      rawKind: "brand_new",
    });
  });

  it("已知 kind 但结构不符 → malformed（§8.4：降级为 incident，不炸流）", () => {
    // server 变成数字
    const bad = JSON.stringify({ seq: 1, kind: "tool_call", payload: { server: 1, tool: "x", args: {} }, at: "t" });
    expect(parseEvidenceFrame(bad)).toMatchObject({ kind: "malformed", rawKind: "tool_call" });
  });
});

/* ─────────────────── ② 回合组装（纯函数） ─────────────────── */

describe("applyChatFrame —— 回合组装", () => {
  const base: Turn[] = [{ id: 1, question: "问", answer: "", notices: [] }];

  it("text 增量累积；final **覆盖**（否则回答会重复一遍）", () => {
    let ts = applyChatFrame(base, 1, { kind: "text", text: "收" });
    ts = applyChatFrame(ts, 1, { kind: "text", text: "到" });
    expect(ts[0].answer).toBe("收到");
    ts = applyChatFrame(ts, 1, { kind: "final", text: "收到" });
    expect(ts[0].answer).toBe("收到");
  });

  it("notice / error 各自归位", () => {
    let ts = applyChatFrame(base, 1, { kind: "notice", detail: "有 server 未拉起" });
    expect(ts[0].notices).toEqual(["有 server 未拉起"]);
    ts = applyChatFrame(ts, 1, { kind: "error", detail: "轮次超限" });
    expect(ts[0].failure).toBe("轮次超限");
  });

  it("tool_call / tool_error 帧**有意忽略**（轨迹取自 evidence 通道，避免重复计数）", () => {
    const ts = applyChatFrame(base, 1, { kind: "tool_call", server: "s", tool: "t", args: {} });
    expect(ts[0]).toEqual(base[0]);
  });
});

/* ─────────────────── ③ 双轨汇总（§3.8.2 / §4.7.1） ─────────────────── */

const finding = (contract: number, state: string, reason: string | null = null): ContractFinding => ({
  contract,
  state,
  reason,
  subject: "s",
  detail: "d",
  evidence: {},
});

describe("summarizeFindings —— 双轨汇总", () => {
  it("★ 空集 = unknown，**不是** satisfied（「没检查」≠「检查过且正常」）", () => {
    const r = summarizeFindings([]);
    expect(r.worst).toBe("unknown");
    expect(r.summary).toEqual({ satisfied: 0, degraded: 0, violated: 0, unknown: 0 });
  });

  it("★ structural 未知**不参与主徽标竞争**（否则告警疲劳淹没真告警）", () => {
    const r = summarizeFindings([finding(4, "unknown", "structural"), finding(1, "satisfied")]);
    expect(r.worst).toBe("satisfied");
    expect(r.summary.unknown).toBe(1);
    expect(r.incidentUnknown).toBe(0);
  });

  it("★ 只有 structural 未知时主徽标仍是 unknown（没有可判定项）", () => {
    expect(summarizeFindings([finding(4, "unknown", "structural")]).worst).toBe("unknown");
  });

  it("★ incident 参与竞争且优先级最高（事故 > 违反 > 降级 > 满足）", () => {
    const r = summarizeFindings([
      finding(1, "satisfied"),
      finding(2, "degraded"),
      finding(3, "violated"),
      finding(4, "unknown", "incident"),
    ]);
    expect(r.worst).toBe("incident");
    expect(r.incidentUnknown).toBe(1);
  });

  it("计数分四态，structural 与 incident 都计入 unknown", () => {
    const r = summarizeFindings([
      finding(1, "satisfied"),
      finding(2, "degraded"),
      finding(3, "violated"),
      finding(4, "unknown", "structural"),
      finding(5, "unknown", "incident"),
    ]);
    expect(r.summary).toEqual({ satisfied: 1, degraded: 1, violated: 1, unknown: 2 });
    expect(r.incidentUnknown).toBe(1);
  });
});

/* ─────────────────── ④ 组件：徽章与状态条 ─────────────────── */

describe("ContractBadge / VerificationLayer", () => {
  it("★ state=unknown 不给 reason → 抛错（否则无法决定渲染「未知」还是「事故」）", () => {
    expect(() => render(<ContractBadge state="unknown" />)).toThrow(/reason/);
  });

  it("unknown + incident → 渲染「事故」；unknown + structural → 渲染「未知」", () => {
    const { container: a } = render(<ContractBadge state="unknown" reason="incident" />);
    expect(a.textContent).toContain("事故");
    cleanup();
    const { container: b } = render(<ContractBadge state="unknown" reason="structural" />);
    expect(b.textContent).toContain("未知");
    expect(b.textContent).not.toContain("事故");
  });

  it("带契约编号时显示「契约 N · 标签」，且**标签不省略**", () => {
    const { container } = render(<ContractBadge state="degraded" contractType={3} />);
    expect(container.textContent).toContain("契约 3");
    expect(container.textContent).toContain("降级");
  });

  it("★ 硬规则 ①：折叠时状态条**仍在**（折叠 ≠ 隐藏）", () => {
    const { container } = render(
      <VerificationLayer
        open={false}
        onToggle={() => {}}
        summary={{ satisfied: 2, degraded: 0, violated: 1, unknown: 0 }}
        worst="violated"
        incidentUnknown={0}
      />,
    );
    expect(container.textContent).toContain("违反"); // 主徽标
    expect(container.textContent).toContain("✔ 2");
    expect(container.textContent).toContain("✖ 1");
    expect(container.textContent).toContain("展开 ▾");
  });

  it("★ 硬规则 ②：incident 计数**升到状态条**（不藏在折叠里）", () => {
    const { container } = render(
      <VerificationLayer
        open={false}
        onToggle={() => {}}
        summary={{ satisfied: 0, degraded: 0, violated: 0, unknown: 3 }}
        worst="incident"
        incidentUnknown={2}
      />,
    );
    expect(container.textContent).toContain("事故");
    expect(container.textContent).toContain("2 项事故");
  });

  it("★ 硬规则 ③：structural 只作次级标记 +?N，不抢主徽标", () => {
    const { container } = render(
      <VerificationLayer
        open={false}
        onToggle={() => {}}
        summary={{ satisfied: 1, degraded: 0, violated: 0, unknown: 4 }}
        worst="satisfied"
        incidentUnknown={0}
      />,
    );
    expect(container.textContent).toContain("满足");
    expect(container.textContent).toContain("+?4");
  });

  it("disabled（用户显式关闭）→ 留下可恢复入口与状态说明，不静默消失", () => {
    const { container } = render(
      <VerificationLayer
        open={false}
        onToggle={() => {}}
        summary={{ satisfied: 0, degraded: 0, violated: 0, unknown: 0 }}
        worst="unknown"
        incidentUnknown={0}
        disabled
        onEnable={() => {}}
      />,
    );
    expect(container.textContent).toContain("校验层已关闭");
    expect(container.textContent).toContain("重新开启");
  });
});

describe("ToolCallRow", () => {
  it("徽标文案与 MVP 同口径（已执行 / 失败）+ 工具名 + 参数", () => {
    const { container } = render(
      <ToolCallRow server="surge" tool="load_network" status="ok" args={{ file_path: "a.m" }} />,
    );
    expect(container.textContent).toContain("已执行");
    expect(container.textContent).toContain("surge.load_network");
    expect(container.textContent).toContain("file_path");
  });

  it("失败行显示原因", () => {
    const { container } = render(
      <ToolCallRow server="s" tool="t" status="bad" error="solver diverged" />,
    );
    expect(container.textContent).toContain("失败");
    expect(container.textContent).toContain("solver diverged");
  });

  it("契约标注**默认折叠**（v4 §4.3：不阻断结果呈现）", () => {
    const { container } = render(
      <ToolCallRow
        server="s"
        tool="t"
        status="ok"
        contract={{ label: "契约 3 降级：linearized 被静默忽略", sig: "degraded" }}
      />,
    );
    const details = container.querySelector("details");
    expect(details).not.toBeNull();
    expect(details!.open).toBe(false); // 默认折叠
    expect(container.textContent).toContain("契约标注");
  });
});

/* ─────────────────── ⑤ 端到端：真实 /chat 流 + evidence 去重 ─────────────────── */

class FakeEventSource {
  static last: FakeEventSource | null = null;
  listeners: Record<string, ((ev: MessageEvent) => void)[]> = {};
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeEventSource.last = this;
  }
  addEventListener(type: string, fn: (ev: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(fn);
  }
  close() {
    this.closed = true;
  }
  emit(type: string, data: string) {
    for (const fn of this.listeners[type] ?? []) fn({ data } as MessageEvent);
  }
}

const json = (body: unknown) =>
  Promise.resolve(
    new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }),
  );

function sseResponse(text: string) {
  const stream = new ReadableStream({
    start(c) {
      c.enqueue(new TextEncoder().encode(text));
      c.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

const EMPTY_CASES = {
  cases: [],
  summary: { total: 0, available: 0, drifted: 0, unreadable_by_servers: 0 },
  allowed_roots: [],
  index_exists: false,
};

describe("③ 对话分析 端到端（真实 /chat 流）", () => {
  it("发问 → 用真实 chat.sse 渲染出回答与连接状态", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/chat")) return Promise.resolve(sseResponse(chatSse));
        if (url.includes("/sessions")) return json({ id: "s1", servers: ["surge"] });
        if (url.includes("/cases")) return json(EMPTY_CASES);
        if (url.includes("/environment")) {
          return json({
            gateway: { python: "3.12.6", python_ok: true },
            powermcp: { root_ok: true },
            llm: { configured: true, model: "m", endpoint: "e" },
            paths: { set: true, roots: ["D:/x"] },
            modules: { enabled: [], failed: [] },
          });
        }
        return json({ skills: [], summary: {}, health: {} });
      }),
    );

    render(<App />);
    const box = await screen.findByLabelText("对话输入");
    fireEvent.change(box, { target: { value: "只回答两个字：收到" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    // 真实流的 text+final 都渲染成「收到」
    await waitFor(() => expect(screen.getByText("收到")).toBeInTheDocument());
    expect(screen.getByText(/对话完成：2 帧/)).toBeInTheDocument();
    // 默认落在「对话」标签（③ 是主界面）
    expect(screen.getByRole("button", { name: "对话" })).toBeInTheDocument();
  });

  it("★ evidence 按 seq 去重：同一条重放两次只计一次", async () => {
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/sessions")) return json({ id: "s2", servers: ["surge"] });
        if (url.includes("/cases")) return json(EMPTY_CASES);
        if (url.includes("/environment")) {
          return json({
            gateway: { python: "3.12.6", python_ok: true },
            powermcp: { root_ok: true },
            llm: { configured: true, model: "m", endpoint: "e" },
            paths: { set: true, roots: [] },
            modules: { enabled: [], failed: [] },
          });
        }
        return json({ skills: [], summary: {}, health: {} });
      }),
    );

    render(<App />);
    await waitFor(() => expect(FakeEventSource.last).not.toBeNull());
    const es = FakeEventSource.last!;

    const frame = JSON.stringify({
      seq: 1,
      kind: "tool_call",
      payload: { server: "surge", tool: "load_network", args: { file_path: "a.m" } },
      at: "t",
    });
    es.emit("evidence", frame);
    es.emit("evidence", frame); // ★ 重放同一条

    // 契约事件也验证一遍：同一 seq 的 finding 只进一次
    const cf = JSON.stringify({
      seq: 2,
      kind: "contract_violation",
      payload: {
        contract: 3,
        state: "violated",
        reason: null,
        subject: "surge",
        detail: "缺少必填参数 `file_path`",
        evidence: {},
      },
      at: "t",
    });
    es.emit("evidence", cf);
    es.emit("evidence", cf);

    // 状态条计数（整行文本形如「✔ 0 · ▲ 0 · ✖ 1」）
    await waitFor(() => expect(screen.getByText(/✖ 1/)).toBeInTheDocument());
    expect(screen.queryByText(/✖ 2/)).toBeNull();
  });
});
