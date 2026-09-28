import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import App from "./App";

/** 骨架冒烟测试：App 在两个端点都返回数据时渲染出真实内容；
 *  任一端点失败时错误态可见（非白屏）——与 DoD #4/#7 对应。 */
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const jsonResponse = (body: unknown) =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );

/** ② 算例库的空库响应（形状取自真实 `GET /cases`）。
 *  ★ 必须提供：视图会自行拉 `/cases`，若落到 404 会**多出第二条 `role="alert"`**，
 *    让「端点失败时错误横幅可见」那条断言变成多匹配。 */
const EMPTY_CASES = {
  cases: [],
  summary: { total: 0, available: 0, drifted: 0, unreadable_by_servers: 0 },
  allowed_roots: [],
  index_exists: false,
};

/** ③ 对话分析在挂载时建会话（校验层状态条要「所有视图共有」，故有意急切建立）。 */
const SESSION = { id: "s-test", servers: ["surge"] };

/** 技能手册现在在**标签页**后面（与 MVP 同布局）—— 断言前先切过去。 */
function gotoSkills() {
  fireEvent.click(screen.getByRole("button", { name: "技能手册" }));
}

function stubFetch(envOk: boolean, skillsOk: boolean) {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/sessions")) {
        return jsonResponse(SESSION);
      }
      if (path.includes("/cases")) {
        return jsonResponse(EMPTY_CASES);
      }
      if (path.includes("/environment")) {
        if (!envOk) {
          return Promise.resolve(new Response("boom", { status: 500 }));
        }
        return jsonResponse({
          gateway: { python: "3.12.6", python_ok: true },
          powermcp: { root_ok: true },
          llm: { configured: true, model: "deepseek", endpoint: "x", required_env: [] },
          paths: { set: true, roots: ["D:/x"], env_var: "POWERIO_MCP_ALLOWED_ROOTS", note: "" },
          modules: { enabled: ["n1"], failed: [] },
        });
      }
      if (path.includes("/skills")) {
        if (!skillsOk) {
          return Promise.resolve(new Response("boom", { status: 500 }));
        }
        return jsonResponse({
          skills: [
            {
              id: "surge.run_power_flow",
              name: "run_power_flow",
              kind: "tool",
              description: "基态潮流",
              path: "powerskills-tool/skills/run_power_flow/SKILL.md",
              escalation: [{ observation: "不收敛", escalate_to: "solver-guide" }],
            },
          ],
          summary: { total: 1, by_kind: { tool: 1 }, with_escalation: 1 },
          health: { level: "unknown", signals: {} },
        });
      }
      return Promise.resolve(new Response("not found", { status: 404 }));
    }),
  );
}

describe("App 骨架冒烟", () => {
  it("两端点正常时渲染环境面板与技能卡片", async () => {
    stubFetch(true, true);
    render(<App />);
    expect(await screen.findByText("环境就绪")).toBeInTheDocument();
    // ★ 数据到达后「加载中…」**必须消失**（骨架步曾无条件渲染，永远挂在页面上 ——
    //   2026-09-27 真机指出。前置「加载态可见」断言在 stub 下是竞态，故不写。）
    expect(screen.queryByText(/加载中/)).toBeNull();
    gotoSkills();
    expect(await screen.findByText("run_power_flow")).toBeInTheDocument();
    expect(screen.getByText(/健康度/)).toHaveTextContent("unknown");
  });

  it("端点失败时错误横幅可见（非白屏），且**不再**显示加载态（加载已失败，不能再等）", async () => {
    stubFetch(false, true);
    render(<App />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("/environment");
    expect(screen.queryByText(/加载中/)).toBeNull();
  });

  it("★ 技能卡给文档出处路径 + 新标签兜底链接（09-28 裁决）", async () => {
    stubFetch(true, true);
    render(<App />);
    await screen.findByText("环境就绪");
    gotoSkills();
    const link = await screen.findByRole("link", { name: "新标签打开" });
    // 兜底链接走网关端点（按 id 定位，无路径穿越），新标签打开 markdown 原文
    expect(link).toHaveAttribute("href", "/skills/surge.run_power_flow/doc");
    expect(link).toHaveAttribute("target", "_blank");
    expect(
      screen.getByText("powerskills-tool/skills/run_power_flow/SKILL.md"),
    ).toBeInTheDocument();
  });

  it("★ 方法手册就地折叠展开（B2：运行时取原文，会话内缓存；09-28 裁决）", async () => {
    const docPayload = {
      id: "surge.run_power_flow",
      kind: "tool",
      path: "powerskills-tool/skills/run_power_flow/SKILL.md",
      content:
        "---\nname: run_power_flow\n---\n# 基态潮流手册\n\n1. 先载入算例。\n2. 检查收敛。\n\n## Escalation triggers\n\n| Observation | Escalate to |\n|---|---|\n| `不收敛` | `convergence-failure-mitigation` |\n",
    };
    const docFetch = vi.fn(() => jsonResponse(docPayload));
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const path = String(input);
        if (path.includes("/doc")) return docFetch();
        if (path.includes("/sessions")) return jsonResponse(SESSION);
        if (path.includes("/cases")) return jsonResponse(EMPTY_CASES);
        if (path.includes("/environment")) {
          return jsonResponse({
            gateway: { python: "3.12.6", python_ok: true },
            powermcp: { root_ok: true },
            llm: { configured: true, model: "m", endpoint: "x", required_env: [] },
            paths: { set: true, roots: ["D:/x"], env_var: "E", note: "" },
            modules: { enabled: [], failed: [] },
          });
        }
        return jsonResponse({
          skills: [
            {
              id: "surge.run_power_flow",
              name: "run_power_flow",
              kind: "tool",
              description: "基态潮流",
              path: "powerskills-tool/skills/run_power_flow/SKILL.md",
            },
          ],
          summary: { total: 1, by_kind: { tool: 1 }, with_escalation: 0 },
          health: { level: "unknown", signals: {} },
        });
      }),
    );
    render(<App />);
    await screen.findByText("环境就绪");
    gotoSkills();
    // 默认折叠：正文不可见
    expect(screen.queryByTestId("skill-doc-body")).toBeNull();
    // 展开 → 取原文 → 渲染标题与列表（frontmatter 不显示）
    fireEvent.click(screen.getByTestId("skill-doc-toggle"));
    expect(await screen.findByTestId("skill-doc-body")).toHaveTextContent("基态潮流手册");
    expect(screen.getByTestId("skill-doc-body")).toHaveTextContent("先载入算例");
    expect(screen.getByTestId("skill-doc-body")).not.toHaveTextContent("name: run_power_flow");
    // 再次点击 → 收起；再展开 → **不再发请求**（会话内缓存）
    fireEvent.click(screen.getByTestId("skill-doc-toggle"));
    expect(screen.queryByTestId("skill-doc-body")).toBeNull();
    fireEvent.click(screen.getByTestId("skill-doc-toggle"));
    expect(await screen.findByTestId("skill-doc-body")).toHaveTextContent("基态潮流手册");
    expect(docFetch).toHaveBeenCalledTimes(1);
  });

  it("筛选框命中名称/描述/触发表，未命中显示空态（对齐 MVP 行为）", async () => {
    // 三个技能：名称含 surge / 描述含 电压 / 触发表含 n-1
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const path = String(input);
        if (path.includes("/sessions")) {
          return jsonResponse(SESSION);
        }
        if (path.includes("/cases")) {
          return jsonResponse(EMPTY_CASES);
        }
        if (path.includes("/environment")) {
          return jsonResponse({
            gateway: { python: "3.12.6", python_ok: true },
            powermcp: { root_ok: true },
            llm: { configured: true, model: "m", endpoint: "x", required_env: [] },
            paths: { set: true, roots: ["D:/x"], env_var: "E", note: "" },
            modules: { enabled: [], failed: [] },
          });
        }
        return jsonResponse({
          skills: [
            { id: "a", name: "surge_tool", kind: "tool", description: "潮流" },
            { id: "b", name: "other", kind: "tool", description: "检查电压薄弱点" },
            {
              id: "c",
              name: "third",
              kind: "engineering",
              escalation: [{ observation: "n-1 越限", escalate_to: "g" }],
            },
          ],
          summary: { total: 3, by_kind: { tool: 2, engineering: 1 }, with_escalation: 1 },
          health: { level: "unknown", signals: {} },
        });
      }),
    );
    render(<App />);
    await screen.findByText("环境就绪");
    gotoSkills();
    await screen.findByText("surge_tool");
    const boxes = screen.getAllByRole("textbox");
    const filter = boxes[boxes.length - 1];
    // 命中触发表字段
    fireEvent.change(filter, { target: { value: "n-1" } });
    expect(screen.getAllByTestId("skill-card")).toHaveLength(1);
    expect(screen.getByText("third")).toBeInTheDocument();
    // 命中描述
    fireEvent.change(filter, { target: { value: "电压" } });
    expect(screen.getAllByTestId("skill-card")).toHaveLength(1);
    expect(screen.getByText("other")).toBeInTheDocument();
    // 未命中 → 空态文案与 MVP 同款
    fireEvent.change(filter, { target: { value: "不存在的词" } });
    expect(screen.queryByTestId("skill-card")).toBeNull();
    expect(screen.getByText(/没有匹配/)).toBeInTheDocument();
  });
});
