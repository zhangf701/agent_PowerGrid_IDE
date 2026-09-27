/** App —— **纯壳**：主题 · 数据加载 · 主区标签 · 校验层状态条 · 错误可见。
 *
 *  ★ 地基步的结构约定：视图在 `views/`（一个视图一个文件），通用件在 `components/`。
 *  ★ 数据入口唯一：`apiParsed(path, schema)`（UI 规范 §8.4 强制）。
 *  ★ 校验层的**顶部状态条放在 header** —— §4.7.1 要求它「所有视图共有」，
 *    故会话与 evidence 事件流由 `useSession()` 提到本层，而不是关在某个视图里。
 */
import { useEffect, useState } from "react";

import {
  EnvironmentSchema,
  SchemaDriftError,
  SkillsResponseSchema,
  apiParsed,
  type Environment,
  type SkillsResponse,
} from "./api";
import {
  Button,
  CapabilityMatrixPanel,
  ContractCard,
  CrossEnginePanel,
  ErrorBanner,
  IrInspectorPanel,
  LoadingState,
  VerificationLayer,
  summarizeFindings,
} from "./components";
import { crossEngineComparisons } from "./results";
import { useSession } from "./session";
import { CasesView, ChatView, EnvView, SkillsView } from "./views";

type ErrorSig = "violated" | "incident";
type Tab = "chat" | "skills";
/** 校验层展开区的标签（§4.7.1：契约面板 / 跨引擎一致性 / 能力矩阵 / IR 检查器） */
type VerifyTab = "contracts" | "cross-engine" | "capability" | "ir";

const VERIFY_TABS: readonly [VerifyTab, string][] = [
  ["contracts", "契约"],
  ["cross-engine", "跨引擎一致性"],
  ["capability", "能力矩阵"],
  ["ir", "IR 检查器"],
];

export default function App() {
  const [dark, setDark] = useState(() => window.location.hash === "#dark");
  // ③ 对话分析是**主界面**（默认标签）。支持 `#skills` 深链 —— 与 MVP 的
  // `?selftest` 同性质：既是可用性（可直接分享某个视图），也让无头验证能定位到各标签。
  const [tab, setTab] = useState<Tab>(() =>
    window.location.hash.includes("skills") ? "skills" : "chat",
  );
  const [env, setEnv] = useState<Environment | null>(null);
  const [skills, setSkills] = useState<SkillsResponse | null>(null);
  const [error, setError] = useState<{ message: string; sig: ErrorSig } | null>(null);
  const [verifyOpen, setVerifyOpen] = useState(false);
  const [verifyDisabled, setVerifyDisabled] = useState(false);
  const [verifyTab, setVerifyTab] = useState<VerifyTab>("contracts");

  const session = useSession();
  const { summary, worst, incidentUnknown } = summarizeFindings(session.findings);
  // ★ 跨引擎配对在 App 层算（rows 在这）—— 纯函数在 results.ts，可独立单测
  const comparisons = crossEngineComparisons(session.rows);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  }, [dark]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [e, sk] = await Promise.all([
          apiParsed("/environment", EnvironmentSchema),
          apiParsed("/skills", SkillsResponseSchema),
        ]);
        if (!alive) return;
        setEnv(e);
        setSkills(sk);
        setError(null);
      } catch (err) {
        if (!alive) return;
        setError({
          message: (err as Error).message,
          // ★ 结构漂移 = incident（本可判定却拿不到）；其余失败 = violated
          sig: err instanceof SchemaDriftError ? "incident" : "violated",
        });
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="flex h-full flex-col">
      <header className="sticky top-0 z-sticky flex items-center gap-3 border-b border-border-subtle bg-surface-raised px-4 py-3">
        <h1 className="m-0 text-h2 font-medium">PowerMCP 研究工作台</h1>
        <span className="text-bodySm text-text-muted">React 骨架</span>
        <span className="ml-auto" />
        <Button onClick={() => setDark((d) => !d)}>{dark ? "浅色" : "深色"}</Button>
      </header>

      {/* ★ 校验层：折叠 ≠ 隐藏 —— 状态条常驻，且 incident 必须升到状态条（§4.7.1） */}
      <VerificationLayer
        open={verifyOpen}
        onToggle={() => setVerifyOpen((o) => !o)}
        summary={summary}
        worst={worst}
        incidentUnknown={incidentUnknown}
        disabled={verifyDisabled}
        onEnable={() => setVerifyDisabled(false)}
        onDisable={() => setVerifyDisabled(true)}
      >
        {/* ★ 展开区 = 四标签（§4.7.1 校验层详情的四块能力，一个不丢） */}
        <div className="mb-2 flex flex-wrap gap-1">
          {VERIFY_TABS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setVerifyTab(key)}
              className={`rounded-sm border px-2 py-0.5 text-caption ${
                verifyTab === key
                  ? "border-interactive-default bg-interactive-subtle font-medium text-text-primary"
                  : "border-border-subtle text-text-secondary hover:bg-interactive-subtle"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {verifyTab === "contracts" &&
          (session.findings.length ? (
            session.findings.map((f, i) => <ContractCard key={i} finding={f} />)
          ) : (
            <div className="text-bodySm text-text-muted">
              本次会话还没有契约事件。契约 1/2/5/6/7 是 <strong>T0 静态</strong>的，
              不在事件流里 —— 看 <code>GET /contracts/t0</code>（能力矩阵标签）。
            </div>
          ))}
        {verifyTab === "cross-engine" && <CrossEnginePanel comparisons={comparisons} />}
        {verifyTab === "capability" && <CapabilityMatrixPanel />}
        {verifyTab === "ir" && <IrInspectorPanel />}
      </VerificationLayer>

      <nav className="flex gap-1 border-b border-border-subtle bg-surface-raised px-4">
        {(
          [
            ["chat", "对话"],
            ["skills", "技能手册"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-3 py-2 text-bodySm ${
              tab === key
                ? "border-interactive-default font-medium text-text-primary"
                : "border-transparent text-text-secondary hover:bg-interactive-subtle"
            }`}
          >
            {label}
          </button>
        ))}
      </nav>

      {error && <ErrorBanner sig={error.sig} message={error.message} />}
      {/* ★ SSE 边界校验失败（§8.4）：可见、不打断流 */}
      {session.boundaryIssue && (
        <ErrorBanner sig="incident" message={session.boundaryIssue} />
      )}
      <LoadingState label="加载中…（等待网关 /environment 与 /skills）" />

      <main className="flex min-h-0 flex-1">
        <aside className="w-[300px] flex-none overflow-auto border-r border-border-subtle bg-surface-raised p-4">
          {env && <EnvView env={env} />}
          <CasesView />
        </aside>
        {tab === "chat" ? (
          <ChatView session={session} />
        ) : (
          skills && <SkillsView data={skills} />
        )}
      </main>
    </div>
  );
}

/* 供冒烟测试断言用（导出仅为可测性，不影响运行时） */
export { md } from "./api";
