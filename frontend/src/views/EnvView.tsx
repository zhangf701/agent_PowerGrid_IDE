/** ① 环境就绪视图 —— 方案 v4 §4.1「能跑什么」。
 *
 *  ★ 刻意「廉价」：只消费 `GET /environment`（不得引入 `build_inventory` —— 那会真实拉起
 *    server，秒级/个；有静态断言钉住）。server **挂载状态**一律看 `/contracts/t0`。
 *  ★ 本步（地基）**保持输出逐字符等价**：图标仍与值同行内联渲染，只是图标不再来自本文件
 *    的局部表，而统一取自组件层 `signatureOf()` —— 输出不变，真源收敛。
 */
import { signatureOf, type SignatureKey } from "../components";
import type { Environment } from "../api";

/** ⚠️ 真实 `/environment` **不回传** `required_env`（2026-09-26 用真实响应夹具实测）——
 *  缺省时回落到网关启动脚本里的**文档化变量名**。
 *  TODO：待 `/environment` 回传该字段后删掉这个常量（前端不该硬编码后端契约）。 */
const LLM_KEY_ENV_FALLBACK = "POWERMCP_LLM_API_KEY";

function EnvRow({ k, sig, v }: { k: string; sig: SignatureKey; v: string }) {
  const s = signatureOf(sig);
  return (
    <div className="flex items-start gap-2 py-0.5">
      <span className="w-24 flex-none text-text-secondary">{k}</span>
      <span>
        <span aria-hidden>{s.icon}</span> {v}
      </span>
    </div>
  );
}

export function EnvView({ env }: { env: Environment }) {
  const rows: { k: string; sig: SignatureKey; v: string }[] = [
    {
      k: "网关",
      sig: env.gateway.python_ok ? "satisfied" : "degraded",
      v: `Python ${env.gateway.python}`,
    },
    {
      k: "PowerMCP",
      sig: env.powermcp.root_ok ? "satisfied" : "degraded",
      v: env.powermcp.root_ok ? "仓库根已找到" : "未找到仓库根",
    },
    {
      k: "LLM",
      sig: env.llm.configured ? "satisfied" : "degraded",
      v: env.llm.configured
        ? `${env.llm.model}（${env.llm.endpoint}）`
        : "未配置",
    },
    {
      k: "路径围笼",
      sig: env.paths.set ? "satisfied" : "degraded",
      v: env.paths.set ? `${env.paths.roots.length} 个根` : "未设置",
    },
    {
      k: "选题模块",
      sig: env.modules.failed.length === 0 ? "satisfied" : "degraded",
      v:
        `${env.modules.enabled.length} 个启用` +
        (env.modules.failed.length
          ? ` · ${env.modules.failed.length} 个装配失败`
          : ""),
    },
  ];

  return (
    <section aria-label="环境就绪">
      <h2 className="mb-2 mt-4 text-h2 font-medium">环境就绪</h2>
      {rows.map((r) => (
        <EnvRow key={r.k} {...r} />
      ))}
      {!env.llm.configured && (
        <div className="my-2 rounded-md border border-contract-degraded-border bg-contract-degraded-bg px-3 py-2 text-bodySm text-contract-degraded-fg">
          <strong>LLM 未配置</strong> —— 对话功能不可用。设置后重启网关：
          <br />
          <code>{(env.llm.required_env ?? [LLM_KEY_ENV_FALLBACK]).join(" · ")}</code>
        </div>
      )}
    </section>
  );
}
