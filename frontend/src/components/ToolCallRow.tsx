/** ToolCallRow —— UI 规范 v2 §4.3「工具轨迹」的审计行。
 *
 *  ★ 呈现：`工具名 + 参数（原始 JSON）+ 状态徽标`。
 *  ★ 徽标文案与 MVP 逐字符一致（`已执行` / `失败`），便于 A/B。
 *  ★ **契约标注默认折叠**（v4 §4.3 变更：v3 的「契约状态**先于**图表渲染」已废除）——
 *    契约标注是**旁路**，不阻断结果呈现。`contract` 属性由 ⑥ 校验层在 S3 填充；
 *    S2 先留好位置（**可选**，未传则不渲染标注行）。
 *  ★ 状态徽标用 `Signature`（图标 + 文字），不靠颜色单独承载信息（P2）。
 */
import { ResultSummary, type ResultItem } from "./ResultSummary";
import { Signature } from "./Signature";

/** 由**参数声明**的输出目标参数名。
 *
 *  ★ 白名单来自 PowerMCP **真实 server 代码**（2026-09-26 核实，已排除 `.venv` 与 `tests`）：
 *    `output_path` 14 处 · `output_dir` 10 处 · `out_path` 5 处。
 *  ★ **有意排除 `dest`**：它在电力语境里可能是「目标母线」，且实测只出现在测试代码里。
 *  ⚠️ **局限**：工具若用别的参数名声明输出，本组件标不出来（白名单制）。
 *     根治办法是让工具 schema 显式标注「写入目标」，那是上游改动，非本层能解决。
 */
export const OUTPUT_ARG_KEYS = ["output_path", "output_dir", "out_path"] as const;

/** 从参数里取出**声明的**输出路径。
 *  ⚠️ 这是**参数**而非**结果** —— 只说明「这次调用被要求写到哪」，
 *  **不等于**「确实写成功了」。渲染措辞必须守住这条边界。 */
export function declaredOutputs(args?: Record<string, unknown> | null): string[] {
  if (!args) return [];
  return OUTPUT_ARG_KEYS.flatMap((k) => {
    const v = args[k];
    return typeof v === "string" && v.trim() ? [v] : [];
  });
}

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
  /** ★ 结构化结果（由数据适配层 `extractResults()` 产出）——
   *  数值与标识符走 `Quantity` / `Identifier`，不转述模型的自述（F-4） */
  results?: ResultItem[];
}

export function ToolCallRow({ server, tool, status, args, error, contract, results }: ToolCallRowProps) {
  const outputs = declaredOutputs(args);

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

      {/* ★ 结构化结果：数值带单位与判据、标识符带编号约定 —— 由代码计算，非模型转述 */}
      {!!results?.length && <ResultSummary items={results} />}

      {/* ★ 工具会往**用户的数据目录**写文件 —— 必须让用户看见（判据 #1 验收暴露）。
          措辞严格守住「参数声明 ≠ 确实写入」这条边界。 */}
      {outputs.length > 0 && (
        <div className="mt-0.5 text-text-muted">
          输出文件（按参数声明）：
          <span className="font-mono">{outputs.join("、")}</span>
          {status !== "ok" && <span>（本次调用失败，未确认写入）</span>}
        </div>
      )}

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
