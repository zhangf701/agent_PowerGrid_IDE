/** CrossEnginePanel —— ⑥ 校验层 · 跨引擎一致性（方案 §5.2 · UI 规范 §6.3 前瞻规格）。
 *
 *  ★ 数据从哪来：**本会话的工具轨迹**（`useSession().rows` 的结构化结果）——
 *    不同引擎对**同一指标**的 Measured 值由 `crossEngineComparisons()` 配对。
 *    没有专门的「一致性端点」：一致性结论只能产生于真实跑过的工具调用，
 *    造不出也不该造一个假数据源。
 *
 *  ★ §6.3 的三条硬规则：
 *    ① **Δ 值必须显示**（PowerIO IR 往返保真的证据）—— 等宽 `e` 记法（§7.2）；
 *    ② **一致性判断不得只用颜色** —— 徽章（图标 + 文字）与 Δ 并列；
 *    ③ **排序靠 seq** —— 在数据层做死（`crossEngineComparisons` 内）。
 *
 *  ★ 诚实边界（比「慢」更危险的「错配」）：
 *    - 配对只在 `label + 单位 + 判据 + 算例标识` 全同时发生；
 *    - 参数里找不到算例标识的组标 `caseVerified=false` —— Δ 照显，**判定一栏
 *      是「无法判定」而不是拍一个结论**（unknown 哲学：宁可未知，不可猜错）。
 */
import type { CrossEngineComparison } from "../results";
import { CONSISTENCY_TOLERANCE } from "../results";
import { Quantity } from "./Quantity";
import { Signature } from "./Signature";

export function CrossEnginePanel({
  comparisons,
}: {
  comparisons: CrossEngineComparison[];
}) {
  if (!comparisons.length) {
    return (
      <div className="text-bodySm text-text-muted">
        本会话还没有可配对的跨引擎结果。让两个不同引擎（如 pandapower 与 surge）对
        <strong>同一算例</strong>跑同一类分析后，这里会自动出现 Δ 对比。
      </div>
    );
  }

  return (
    <div data-testid="cross-engine-panel">
      <div className="mb-1 text-caption text-text-muted">
        一致性阈值：相对偏差 ≤ {formatThreshold(CONSISTENCY_TOLERANCE)}（显式声明，非隐含判据）。
        算例标识取自调用参数；标识缺失时只显示 Δ，<strong>不给</strong>一致性判定。
      </div>
      {comparisons.map((c, i) => (
        <div
          key={i}
          data-testid="cross-engine-row"
          className="mb-1.5 rounded-md border border-border-subtle bg-surface-raised px-3 py-2 text-bodySm"
        >
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="font-medium">{c.label}</span>
            {c.caseKey && (
              <span className="font-mono text-caption text-text-muted">
                {c.caseKey}
                {c.caseKeyInherited && (
                  <span title="本次调用无参（操作已载入的网络），算例标识继承自该引擎会话内最近一次载入调用">
                    {" "}（会话内最近载入）
                  </span>
                )}
              </span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-baseline gap-x-4 gap-y-1">
            {c.entries.map((e) => (
              <span key={e.seq} className="whitespace-nowrap">
                <span className="text-text-secondary">{e.server}</span>{" "}
                <Quantity of={e.measured} />
              </span>
            ))}
            <span className="whitespace-nowrap">
              <span className="text-text-secondary">Δ</span>{" "}
              <span className="font-mono">{formatDelta(c.delta, c.unit)}</span>
            </span>
            {c.caseVerified ? (
              <Signature
                sig={c.consistent ? "satisfied" : "violated"}
                text={c.consistent ? "满足" : "不一致"}
              />
            ) : (
              <Signature sig="unknown" text="无法判定（算例一致性未核实）" />
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/** Δ 的等宽文本（§7.2：科学计数用 `e` 记法）。 */
function formatDelta(delta: number, unit: string): string {
  const v = Number(delta.toPrecision(3));
  return `${v} ${unit}`;
}

/** 阈值同样按 §7.2 用 `e` 记法（`0.0001` 在等宽字体下易数错零的个数）。 */
function formatThreshold(t: number): string {
  return t.toExponential();
}
