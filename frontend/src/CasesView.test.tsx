/** ② 算例库视图的测试。
 *
 *  ★ 最重要的一条：**围笼 409 分支**必须给出**可执行指引**（把哪个目录加进哪个变量）。
 *    这条此前从未被真实触发过（单测里一直是 monkeypatch），本视图是它的第一个真实落点。
 *  ★ 数据安全底线：注销只注销登记，**绝不删源文件** —— 断言请求方法是 `DELETE`
 *    且响应 `source_file_kept: true`。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import casesFx from "./__fixtures__/gateway/cases.json";
import parseFx from "./__fixtures__/gateway/case-parse.json";
import { CasesView } from "./views/CasesView";

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

/** 项目外那个算例的 id（夹具里 `within_allowed_roots=false` 的那张）。 */
const OUTSIDE_ID = casesFx.cases.find((c) => !c.within_allowed_roots)!.id;
const INSIDE_ID = casesFx.cases.find((c) => c.within_allowed_roots)!.id;

/** 网关对围笼外算例解析的**真实** 409 文案（2026-09-27 实测抓取；
 *  ⚠️ 2026-09-26 版用 `_科研项目` —— 该文件已不存在，现用 Downloads 下的围笼测试文件）。 */
const FENCE_409 =
  "算例所在目录不在 `POWERIO_MCP_ALLOWED_ROOTS` 内 —— server 子进程读不到它。" +
  "请把 `C:\\Users\\Z\\Downloads` 加入该变量后重启网关" +
  "（当前允许根：['D:\\coding\\powerMcp_Pskills', 'C:\\Users\\Z\\.powermcp']；" +
  "见 `GET /environment` 的 `server_env` 段）。";

type Call = { method: string; url: string };

function stub(overrides: Record<string, () => Promise<Response>> = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      calls.push({ method, url });

      for (const [key, handler] of Object.entries(overrides)) {
        if (url.includes(key)) return handler();
      }
      if (url.includes("/parse")) return json(parseFx);
      if (url.includes("/cases/")) {
        return json({ unregistered: INSIDE_ID, label: "case39.m", source_file_kept: true });
      }
      return json(casesFx);
    }),
  );
  return calls;
}

describe("② 算例库视图", () => {
  it("渲染两个算例；围笼外那张带可执行指引", async () => {
    stub();
    render(<CasesView />);
    await waitFor(() => expect(screen.getAllByTestId("case-card")).toHaveLength(2));
    expect(screen.getByText("case39.m")).toBeInTheDocument();
    expect(screen.getByText("server 读不到")).toBeInTheDocument();
    // ★ 指引必须说清「把哪个目录加进哪个变量」，而不是只说读不到
    expect(screen.getByText(/POWERIO_MCP_ALLOWED_ROOTS/)).toBeInTheDocument();
  });

  it("空库显示空态文案（与 MVP 同款）", async () => {
    stub({
      "/cases": () =>
        json({ ...casesFx, cases: [], summary: { ...casesFx.summary, total: 0 } }),
    });
    render(<CasesView />);
    expect(await screen.findByText("还没有算例。在下面填路径登记一个。")).toBeInTheDocument();
  });

  it("★ 围笼 409：解析项目外算例 → 错误可见且**给出可执行指引**", async () => {
    stub({ [`/cases/${OUTSIDE_ID}/parse`]: () => json({ detail: FENCE_409 }, 409) });
    render(<CasesView />);
    await waitFor(() => expect(screen.getAllByTestId("case-card")).toHaveLength(2));

    const cards = screen.getAllByTestId("case-card");
    const outside = cards.find((el) => el.textContent?.includes("server 读不到"))!;
    fireEvent.click(within(outside).getByRole("button", { name: "解析" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("POWERIO_MCP_ALLOWED_ROOTS");
    expect(alert.textContent).toContain("加入该变量后重启网关");
    expect(alert.textContent).toContain("Downloads");
  });

  it("★ 回归（2026-09-27 真机踩中）：先成功解析 A，再解析 B 失败 —— A 的提示**不得残留**", async () => {
    // 张老师实测：case39 解析成功（「已解析 …51.0 KB」）→ 点围笼外算例解析（409），
    // 残留的 case39 提示被误读成围笼文件的结果。根因 = act() 只清 error 不清 note。
    stub({ [`/cases/${OUTSIDE_ID}/parse`]: () => json({ detail: FENCE_409 }, 409) });
    render(<CasesView />);
    await waitFor(() => expect(screen.getAllByTestId("case-card")).toHaveLength(2));

    const cards = screen.getAllByTestId("case-card");
    const inside = cards.find((el) => !el.textContent?.includes("server 读不到"))!;
    fireEvent.click(within(inside).getByRole("button", { name: "解析" }));
    // ★ 成功反馈带算例名（可归因）
    expect(await screen.findByText(/已解析 case39\.m：/)).toBeInTheDocument();

    const outside = cards.find((el) => el.textContent?.includes("server 读不到"))!;
    fireEvent.click(within(outside).getByRole("button", { name: "解析" }));

    // 409 横幅可见的同时，上一条「已解析」**必须已消失**
    await screen.findByRole("alert");
    expect(screen.queryByText(/已解析 case39\.m：/)).toBeNull();
  });

  it("★ 注销：走 DELETE 且提示「源文件未删除」（数据安全底线）", async () => {
    const calls = stub();
    render(<CasesView />);
    await waitFor(() => expect(screen.getAllByTestId("case-card")).toHaveLength(2));

    fireEvent.click(screen.getAllByRole("button", { name: "注销" })[0]);

    expect(await screen.findByText(/已注销登记/)).toBeInTheDocument();
    expect(screen.getByText("源文件未删除")).toBeInTheDocument();

    const del = calls.find((c) => c.method === "DELETE");
    expect(del?.url).toContain(`/cases/${INSIDE_ID}`);
    // ★ 没有任何请求打向会删文件的路径（本网关也不存在这样的端点）
    expect(calls.every((c) => c.method === "DELETE" ? c.url.endsWith(INSIDE_ID) : true)).toBe(true);
  });

  it("登记成功 → 提示已登记；带归一化时**如实**说明路径被改过", async () => {
    // POST 与 GET 同路径，用 method 区分
    vi.stubGlobal(
      "fetch",
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
        if ((init?.method ?? "GET").toUpperCase() === "POST") {
          return json({
            created: true,
            case: casesFx.cases[0],
            path_normalized: ["剥离首尾引号"],
            path_used: casesFx.cases[0].source_path,
          });
        }
        return json(casesFx);
      }),
    );
    render(<CasesView />);
    await waitFor(() => expect(screen.getAllByTestId("case-card")).toHaveLength(2));

    fireEvent.change(screen.getByLabelText("算例文件的绝对路径"), {
      target: { value: `"${casesFx.cases[0].source_path}"` },
    });
    fireEvent.click(screen.getByRole("button", { name: "登记" }));

    expect(await screen.findByText(/已登记算例/)).toBeInTheDocument();
    expect(screen.getByText(/路径已自动归一化：剥离首尾引号/)).toBeInTheDocument();
  });

  it("登记空路径 → 立即报错，不发请求", async () => {
    const calls = stub();
    render(<CasesView />);
    await waitFor(() => expect(screen.getAllByTestId("case-card")).toHaveLength(2));
    const before = calls.length;

    fireEvent.click(screen.getByRole("button", { name: "登记" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("请先填算例文件的绝对路径");
    expect(calls.length).toBe(before);
  });
});
