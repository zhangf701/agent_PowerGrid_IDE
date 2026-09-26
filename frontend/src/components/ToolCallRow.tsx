/** ToolCallRow —— UI 规范 v2 §4.3「工具轨迹」的审计行。
 *
 *  ★ 呈现：`工具名 + 参数（原始 JSON）+ 状态徽标`。
 *  ★ 徽标文案与 MVP 逐字符一致（`已执行` / `失败`），便于 A/B。
 *  ★ **契约标注默认折叠**（v4 §4.3 变更：v3 的「契约状态**先于**图表渲染」已废除）——
 *    契约标注是**旁路**，不阻断结果呈现。`contract` 属性由 ⑥ 校验层在 S3 填充；
 *    S2 先留好位置（**可选**，未传则不渲染标注行）。
 *  ★ 状态徽标用 `Signature`（图标 + 文字），不靠颜色单独承载信息（P2）。
 */
import { Signature } from "./Signature";

export interface ToolCallRowProps {
  server: string;
  tool: string;
  status: "ok" | "bad";
  /** 调用参数（原始对象，按 JSON 展示） */
  args?: Record<string, unknown> | null;
  /** 失败原因 */
  error?: string | null;
  /** 契约标注（S3 由校验层注入）—— 默认折叠 */
  contract?: { label: string; sig: "degraded" | "incident" | "satisfied" } | null;
}

export function ToolCallRow({ server, tool, status, args, error, contract }: ToolCallRowProps) {
  return (
    <div data-testid="tool-call-row" className="py-0.5 text-caption">
      <div className="flex flex-wrap items-baseline gap-2">
        <Signature sig={status === "ok" ? "satisfied" : "violated"} text={status === "ok" ? "已执行" : "失败"} />
        <span className="font-mono">
          {server}.{tool}
        </span>
        {args && Object.keys(args).length > 0 && (
          <span className="text-text-muted">{JSON.stringify(args)}</span>
        )}
        {error && <span className="text-text-muted">{error}</span>}
      </div>

      {/* ★ 契约标注：默认折叠的旁路标注，不阻断结果呈现 */}
      {contract && (
        <details className="mt-0.5 ml-1">
          <summary className="cursor-pointer text-text-muted">契约标注</summary>
          <div className="mt-0.5 flex items-baseline gap-2">
            <Signature sig={contract.sig} />
            <span>{contract.label}</span>
          </div>
        </details>
      )}
    </div>
  );
}
