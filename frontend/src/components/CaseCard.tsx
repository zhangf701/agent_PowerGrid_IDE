/** CaseCard —— UI 规范 v2 §4.7.2。
 *
 *  ★ 为什么需要：v3 只有 session 粒度，研究无法「组织」。**算例是实验矩阵的主语**。
 *
 *  ★ 三条硬规则（本组件的存在理由）：
 *    ① `available` / `drift` **必须现算**（服务端每次读取时计算），**不得缓存** ——
 *       存下来的「文件还在」会过期，而**过期的「还在」比不报更危险**。
 *    ② `drift=true` 必须**显式呈现**，且文案须说明「结论来自**登记时**的数据」。
 *    ③ `within_allowed_roots=false` 必须给出**可执行指引** —— 而不是只说「读不到」。
 *
 *  ⚠️ **与 MVP 的两处有意差异**（规范强制，非回归）：
 *    - MVP 只有徽标「server 读不到」，**没有指引**（§4.7.2 反例明确点名这种写法）；
 *    - MVP 只有徽标「内容已变」，**未说明基准**（硬规则 2 要求）。
 *    两处徽标**文案完全保留**，指引是**追加**的可见文字（不用 tooltip ——
 *    规范自己批评过「悬浮提示在截图/导出里不可见」）。
 */
import type { Case } from "../api";
import { Button } from "./Button";

/** 字节格式化 —— 与 MVP 逐字符同口径（B / KB / MB，各一位小数）。 */
export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

/** 登记时的哈希短前缀 + 日期 —— 硬规则 2 要求说明「结论来自登记时的数据」。 */
export function registrationBasis(c: Case): string {
  const short = c.sha256.slice(0, 8);
  const day = c.registered_at.slice(0, 10);
  return `${short}（${day} 登记）`;
}

export function CaseCard({
  c,
  selected,
  busy,
  onSelect,
  onParse,
  onUnregister,
}: {
  c: Case;
  selected: boolean;
  /** 正在解析的算例 id 集合 —— 用于禁用按钮并显示「解析中…」 */
  busy: boolean;
  onSelect: () => void;
  onParse: () => void;
  onUnregister: () => void;
}) {
  return (
    <div
      data-testid="case-card"
      className={`mb-2 rounded-lg border px-3 py-2 ${
        selected ? "border-interactive-default" : "border-border-subtle"
      }`}
    >
      <div className="font-medium">{c.label}</div>

      <div className="flex flex-wrap items-center gap-2 text-caption text-text-muted">
        <span className="font-mono">{c.format}</span>
        <span>{fmtBytes(c.size)}</span>
        {/* ★ 徽标文案与 MVP 逐字符一致（A/B 基准） */}
        {!c.available && (
          <span className="rounded-sm border border-contract-violated-border bg-contract-violated-bg px-1.5 text-contract-violated-fg">
            文件不在了
          </span>
        )}
        {c.drift && (
          <span className="rounded-sm border border-contract-degraded-border bg-contract-degraded-bg px-1.5 text-contract-degraded-fg">
            内容已变
          </span>
        )}
        {!c.within_allowed_roots && (
          <span className="rounded-sm border border-contract-degraded-border bg-contract-degraded-bg px-1.5 text-contract-degraded-fg">
            server 读不到
          </span>
        )}
      </div>

      {/* ★ 硬规则 2：drift 必须说明基准 —— 「对比的是登记时那份」 */}
      {c.drift && (
        <div className="mt-1 text-caption text-contract-degraded-fg">
          内容已变：与登记时的哈希不一致（基准 {registrationBasis(c)}）——
          已解析的结果对应的是**登记时**那份文件。
        </div>
      )}

      {/* ★ 硬规则 3：必须给**可执行指引**，而不是只说「读不到」 */}
      {!c.within_allowed_roots && (
        <div className="mt-1 text-caption text-contract-degraded-fg">
          该目录不在 <code>POWERIO_MCP_ALLOWED_ROOTS</code> 内，server 读不到它 ——
          把 <code>{parentOf(c.source_path)}</code> 加入该变量后重启网关。
        </div>
      )}

      {/* ★ 反例「available=false 时卡片直接消失」的反面：卡片**保留**并说明原因 */}
      {!c.available && (
        <div className="mt-1 text-caption text-contract-violated-fg">
          源文件现在不可读（已移动或删除）—— 登记信息仍在，路径：<code>{c.source_path}</code>
        </div>
      )}

      <div className="mt-2 flex gap-2">
        <Button onClick={onSelect}>{selected ? "取消选中" : "选中"}</Button>
        <Button onClick={onParse} disabled={busy}>
          {busy ? "解析中…" : "解析"}
        </Button>
        <Button variant="ghost" onClick={onUnregister}>
          注销
        </Button>
      </div>
    </div>
  );
}

/** 取父目录 —— 用于「把哪个目录加进允许根」的指引（不引 node:path，纯字符串处理）。 */
export function parentOf(p: string): string {
  const i = Math.max(p.lastIndexOf("\\"), p.lastIndexOf("/"));
  return i > 0 ? p.slice(0, i) : p;
}
