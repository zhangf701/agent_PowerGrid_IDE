/** 组件层测试 —— 钉住规范里那些「看起来是细节、实则是缺陷防线」的行为。
 *
 *  优先级最高的三条：
 *  ① `Signature` **图标 + 文字**同时存在（颜色不得单独承载信息），且五图标互不相似；
 *  ② `Identifier` 查表未命中 → `(约定未知)`，**绝不猜一个值**（猜 = 语气确定的假声明）；
 *  ③ `Quantity` 的判据只能由 `measure()` 注入，渲染点写不出来。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

import {
  CaseCard,
  ErrorState,
  Identifier,
  LoadingState,
  Quantity,
  Signature,
  deriveConvention,
  fmtBytes,
  measure,
  parentOf,
  signatureOf,
  type SignatureKey,
  type UnitSpec,
} from "./components";
import type { Case } from "./api";

afterEach(cleanup);

describe("Signature —— 色 + 图标 + 标签，三者不拆分", () => {
  it("五签名的图标互不相似，且各自带标签（去掉颜色仍可区分）", () => {
    const keys: SignatureKey[] = ["satisfied", "degraded", "violated", "unknown", "incident"];
    const icons = keys.map((k) => signatureOf(k).icon);
    expect(new Set(icons).size).toBe(5);
    expect(icons).toEqual(["✔", "▲", "✖", "?", "!"]);
    for (const k of keys) {
      const s = signatureOf(k);
      expect(s.label.length).toBeGreaterThan(0);
      expect(s.icon.length).toBeGreaterThan(0);
    }
  });

  it("渲染出图标与文字（不是只靠颜色）", () => {
    const { container } = render(<Signature sig="unknown" />);
    expect(container.textContent).toContain("?");
    expect(container.textContent).toContain("未知");
  });

  it("unknown 与 incident 视觉可分（同一数据状态、两种成因，用户动作不同）", () => {
    const { container: a } = render(<Signature sig="unknown" />);
    const { container: b } = render(<Signature sig="incident" />);
    expect(a.textContent).toContain("未知");
    expect(b.textContent).toContain("事故");
  });

  it("text 覆盖默认标签（如技能 kind 徽标用中文名）", () => {
    const { container } = render(<Signature sig="degraded" text="工程" />);
    expect(container.textContent).toContain("工程");
    expect(container.textContent).not.toContain("降级");
  });
});

describe("Quantity —— 数值必须与单位/判据同时出现", () => {
  it("比值型渲染出判据后缀（后缀是独立 muted span，故分两段断言）", () => {
    const { container } = render(
      <Quantity of={measure(142.47, { unit: "%", criterion: "MVA" }, "call-1")} />,
    );
    expect(container.textContent).toContain("142.47%");
    expect(container.textContent).toContain("(MVA 判据)");
  });

  it("数值挂上来源（CallId）—— 证据可下钻", () => {
    const { container } = render(<Quantity of={measure(1, { unit: "MW" }, "call-42")} />);
    expect(container.querySelector("[title]")?.getAttribute("title")).toContain("call-42");
  });

  it("有量纲渲染「数值 空格 单位」", () => {
    render(<Quantity of={measure(958.49, { unit: "MW" }, "call-1")} />);
    expect(screen.getByText(/958\.49 MW/)).toBeInTheDocument();
  });

  it("delta 渲染为 Δ = 形式，且保留极小量级（不塌成 0）", () => {
    render(<Quantity of={measure(6.98e-11, { unit: "pu" }, "call-1")} delta />);
    expect(screen.getByText(/Δ = 6\.98e-11 pu/)).toBeInTheDocument();
  });

  it("物理越限**必须**渲染文字标签（不得只改颜色）", () => {
    const of = measure(142.47, { unit: "%", criterion: "MVA" }, "call-1");
    render(<Quantity of={of} alarm={{ level: "over" }} />);
    expect(screen.getByText("超限")).toBeInTheDocument();
  });

  it("measure() 拒绝非有限数值（NaN / Infinity / 字符串）", () => {
    for (const bad of [NaN, Infinity, "142.47", null, undefined]) {
      expect(() => measure(bad, { unit: "MW" }, "c")).toThrow(/只接受有限数值/);
    }
  });

  it("measure() 拒绝无判据的百分比（% 脱离判据无意义）", () => {
    const bad = { unit: "%" } as unknown as UnitSpec;
    expect(() => measure(98.16, bad, "c")).toThrow(/必须给出判据/);
  });
});

describe("Identifier —— 约定不得猜测", () => {
  it("按 server id 查表推导（实测过的三者）", () => {
    expect(deriveConvention("pandapower")).toBe("0-based");
    expect(deriveConvention("surge")).toBe("0-based");
    expect(deriveConvention("pypsa")).toBe("1-based");
  });

  it("未实测的引擎 → unknown（**不是**兜底 0-based）", () => {
    for (const e of ["andes", "egret", "opendss", "hope", "genx", "powerio"] as const) {
      expect(deriveConvention(e)).toBe("unknown");
    }
    expect(deriveConvention(undefined)).toBe("unknown");
  });

  it("渲染出约定后缀", () => {
    const { container: a } = render(<Identifier id={13} engine="pypsa" />);
    expect(a.textContent).toContain("13");
    expect(a.textContent).toContain("(1-based)");

    const { container: b } = render(<Identifier id={7} engine="andes" kind="bus" />);
    expect(b.textContent).toContain("(约定未知)");
  });

  it("显式约定与引擎事实冲突 → 抛错（不静默采信任何一方）", () => {
    expect(() => render(<Identifier id={1} engine="pandapower" convention="1-based" />)).toThrow(
      /冲突/,
    );
  });

  it("显式约定与引擎一致 → 正常渲染", () => {
    const { container } = render(<Identifier id={12} engine="pandapower" convention="0-based" />);
    expect(container.textContent).toContain("(0-based)");
  });
});

describe("三态 —— 区分空 / 加载 / 错误", () => {
  it("LoadingState 超过 delayMs 才出现（避免闪烁）", () => {
    vi.useFakeTimers();
    try {
      render(<LoadingState label="加载中…" delayMs={800} />);
      expect(screen.queryByRole("status")).toBeNull();
      act(() => vi.advanceTimersByTime(900));
      expect(screen.getByRole("status")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("delayMs=0 立即出现", () => {
    render(<LoadingState label="加载中…" delayMs={0} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("ErrorState 区分引擎崩溃（等重启）与调用失败（改参数）", () => {
    const { container: engine } = render(<ErrorState kind="engine" message="引擎挂了" />);
    expect(engine.textContent).toContain("fail-closed");
    expect(screen.getByRole("alert")).toBeInTheDocument();

    cleanup();
    const { container: call } = render(<ErrorState kind="call" message="参数不对" />);
    expect(call.textContent).toContain("调用未生效");
    expect(call.textContent).not.toContain("fail-closed");
  });
});

/* ────────────────────────── CaseCard（§4.7.2） ────────────────────────── */

const baseCase: Case = {
  id: "cd4cf1328477",
  label: "case39.m",
  source_path: "D:\\coding\\powerMcp_Pskills\\examples\\data\\case39.m",
  format: "m",
  size: 5371,
  sha256: "5b6549ace9da61121a40530bda828ed0bc0bbacc5d2ff40387543575f02e5d9b",
  registered_at: "2026-09-25T10:45:45Z",
  available: true,
  drift: false,
  within_allowed_roots: true,
};

const noop = () => {};

function renderCase(over: Partial<Case> = {}) {
  return render(
    <CaseCard
      c={{ ...baseCase, ...over }}
      selected={false}
      busy={false}
      onSelect={noop}
      onParse={noop}
      onUnregister={noop}
    />,
  );
}

describe("CaseCard —— 三条硬规则必须可见", () => {
  it("干净算例：显示 label / format / 大小，无任何告警徽标", () => {
    const { container } = renderCase();
    expect(container.textContent).toContain("case39.m");
    expect(container.textContent).toContain("m");
    expect(container.textContent).toContain("5.2 KB");
    expect(container.textContent).not.toContain("内容已变");
    expect(container.textContent).not.toContain("server 读不到");
    expect(container.textContent).not.toContain("文件不在了");
  });

  it("★ 硬规则 2：drift 必须说明**基准来自登记时**", () => {
    const { container } = renderCase({ drift: true });
    expect(container.textContent).toContain("内容已变");
    expect(container.textContent).toContain("5b6549ac"); // 登记时的 sha 前缀
    expect(container.textContent).toContain("2026-09-25");
    expect(container.textContent).toContain("登记时");
  });

  it("★ 硬规则 3：围笼外必须给**可执行指引**（含要加入的目录），而不是只说读不到", () => {
    const { container } = renderCase({ within_allowed_roots: false });
    expect(container.textContent).toContain("server 读不到");
    expect(container.textContent).toContain("POWERIO_MCP_ALLOWED_ROOTS");
    expect(container.textContent).toContain("examples\\data"); // 该加进变量的父目录
    expect(container.textContent).toContain("重启网关");
  });

  it("★ 反例的反面：available=false 时卡片**保留**并说明原因与路径（不得直接消失）", () => {
    const { container } = renderCase({ available: false });
    expect(container.textContent).toContain("文件不在了");
    expect(container.textContent).toContain("case39.m"); // 卡片没消失
    expect(container.textContent).toContain("case39.m"); // 路径仍可见
  });

  it("解析中：按钮禁用且文案变为「解析中…」", () => {
    render(
      <CaseCard
        c={baseCase}
        selected
        busy
        onSelect={noop}
        onParse={noop}
        onUnregister={noop}
      />,
    );
    const btn = screen.getByRole("button", { name: "解析中…" });
    expect(btn).toBeDisabled();
  });

  it("fmtBytes 三档与 MVP 同口径", () => {
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(5371)).toBe("5.2 KB");
    expect(fmtBytes(3 * 1048576)).toBe("3.0 MB");
  });

  it("parentOf 同时兼容反斜杠与正斜杠路径", () => {
    expect(parentOf("D:\\a\\b\\c.m")).toBe("D:\\a\\b");
    expect(parentOf("D:/a/b/c.m")).toBe("D:/a/b");
  });
});
