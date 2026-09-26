/** 三态 + 错误呈现 —— UI 规范 v2 §4.6.5。
 *
 *  ★ **三态必须区分**，不得用同一个灰色占位：
 *    - `EmptyState`：说明「为什么空」+ 下一步动作（最容易被写成「暂无数据」四个字）
 *    - `LoadingState`：骨架屏，**超过 800ms 才出现**，避免闪烁
 *    - `ErrorState`：区分**引擎崩溃**（fail-closed，等重启）与**调用失败**（改参数）
 *      —— 二者的用户动作不同，故用不同签名（`incident` vs `violated`）。
 *  ★ 错误必须在界面上可见（MVP 验收判据：不需要开控制台）→ 一律带 `role="alert"`。
 */
import { useEffect, useState, type ReactNode } from "react";

import { Signature, type SignatureKey } from "./Signature";

const BANNER_CLS: Record<"violated" | "degraded" | "incident" | "unknown", string> = {
  violated:
    "border-contract-violated-border bg-contract-violated-bg text-contract-violated-fg",
  degraded:
    "border-contract-degraded-border bg-contract-degraded-bg text-contract-degraded-fg",
  incident:
    "border-contract-incident-border bg-contract-incident-bg text-contract-incident-fg",
  unknown: "border-contract-unknown-border bg-contract-unknown-bg text-contract-unknown-fg",
};

/** 行内错误横幅。`sig` 决定签名 —— 入站结构漂移用 `incident`（本可判定却拿不到）。 */
export function ErrorBanner({
  message,
  sig = "violated",
}: {
  message: ReactNode;
  sig?: Extract<SignatureKey, "violated" | "degraded" | "incident" | "unknown">;
}) {
  return (
    <div
      role="alert"
      className={`mx-4 mt-2 rounded-md border px-3 py-2 text-bodySm ${BANNER_CLS[sig]}`}
    >
      <Signature sig={sig} />
      <span className="ml-2">{message}</span>
    </div>
  );
}

/** 区域级错误态。区分两类失败 —— 用户动作不同。 */
export function ErrorState({
  message,
  kind = "call",
}: {
  message: ReactNode;
  kind?: "call" | "engine";
}) {
  const engine = kind === "engine";
  return (
    <div className="p-4">
      <ErrorBanner
        sig={engine ? "incident" : "violated"}
        message={
          <>
            {message}
            <div className="mt-1 text-text-secondary">
              {engine
                ? "引擎进程不可用（fail-closed）—— 该引擎的调用会被直接拒绝，等重启后重试。"
                : "调用未生效 —— 检查参数或换一种做法后重试。"}
            </div>
          </>
        }
      />
    </div>
  );
}

/** 空态：必须说明「为什么空」，可选给下一步动作。 */
export function EmptyState({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="text-text-muted">
      {children}
      {hint && <div className="mt-1 text-bodySm text-text-secondary">{hint}</div>}
    </div>
  );
}

/** 加载态：**超过 `delayMs` 才出现**，避免快响应下的闪烁。 */
export function LoadingState({
  label = "加载中…",
  delayMs = 800,
}: {
  label?: ReactNode;
  delayMs?: number;
}) {
  const [show, setShow] = useState(delayMs <= 0);

  useEffect(() => {
    if (delayMs <= 0) return;
    const t = setTimeout(() => setShow(true), delayMs);
    return () => clearTimeout(t);
  }, [delayMs]);

  if (!show) return null;
  return (
    <div role="status" className="p-4 text-text-muted">
      {label}
    </div>
  );
}
