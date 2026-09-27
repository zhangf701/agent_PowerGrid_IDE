/** 前端会请求的网关路径前缀 —— **dev 代理与测试共用的单一真源**。
 *
 *  ★ 为什么独立成模块：`vite.config.ts` 会连带加载 esbuild（plugin-react），
 *    在 vitest 的 jsdom 环境里直接 import 它会崩（TextEncoder invariant violation）。
 *    故清单放这里，vite.config 与守卫测试各取所需。
 *
 *  ★ **dev 代理必须全覆盖**：漏一个，dev 下该路径会打到 vite 自己 → 回落 index.html
 *    （200 + HTML）→ 前端报「响应不是 JSON」。2026-09-27 实测 `/servers` 漏掉，
 *    能力矩阵面板因此「! 事故」。`api.test.ts` 有守卫测试钉住这份清单。
 *  ⚠️ 新增网关端点时**必须**同步加进来。 */
export const GATEWAY_PREFIXES = [
  "health",
  "environment",
  "skills",
  "servers",
  "cases",
  "contracts",
  "sessions",
  "modules",
  "checks",
  "ui",
] as const;
