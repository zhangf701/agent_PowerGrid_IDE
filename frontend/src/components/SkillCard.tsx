/** SkillCard —— UI 规范 v2 §4.7.3。
 *
 *  ★ **v2 相对 v1.x 最重要的补口**：21 个技能在 v1.x 中零覆盖，而
 *    `Escalation triggers`（观测值 → 缓解手册的数字驱动映射）是**「研究方法」最直接的载体**。
 *
 *  ★ 两条硬规则：
 *    ① 健康度必须显示且**必须允许 unknown** —— 不得渲染成「正常」；
 *    ② `escalation` 必须展示 `observation` **原文**（含反引号内的字段名）——
 *       它是用户判断「我这次是否命中」的唯一依据，**转述会失真**。
 *
 *  ⚠️ **本步（地基）有意保持行为等价**，故健康度仍由视图级汇总行呈现（与 MVP A/B 一致）。
 *     §4.7.3 的 `health` 属性是**每技能**粒度 —— `/skills` 只给聚合信号
 *     （`escalation_missing` / `dangling_escalation` / `orphan_playbooks` 三个名单），
 *     逐卡片健康度可作为后续细化项，本步不擅自改可见行为。
 */
import type { Skill } from "../api";
import { Signature, type SignatureKey } from "./Signature";

/** kind → 中文徽标文案（与 MVP 逐项对齐，A/B 对照基准） */
export const KIND_LABEL: Record<string, string> = {
  tool: "工作流",
  engineering: "工程",
  meta: "meta",
};

/** kind → 签名键。★ 用规范的五签名键（`degraded` 的图标是 `▲`，不是 `⚠`）——
 *  同族符号 `✔ ⚠ ✖` 在灰度打印下会退化成三个相似方块（§3.8.1）。 */
export const KIND_SIG: Record<string, SignatureKey> = {
  tool: "satisfied",
  engineering: "degraded",
  meta: "unknown",
};

/** 等宽 —— ★ 用令牌类 `font-mono`（F-2 已修，此前只能写内联 `style` 绕过）。 */
const MONO = "font-mono";

export function SkillCard({ skill }: { skill: Skill }) {
  return (
    <div
      data-testid="skill-card"
      className="rounded-lg border border-border-subtle bg-surface-raised p-3"
    >
      <div className="mb-1 flex flex-wrap items-baseline gap-2">
        <span className={`font-medium ${MONO}`}>
          {skill.name}
        </span>
        <Signature
          sig={KIND_SIG[skill.kind] ?? "unknown"}
          text={KIND_LABEL[skill.kind] ?? skill.kind}
        />
        <span className="ml-auto text-bodySm text-text-muted">{skill.kind}</span>
      </div>

      {skill.description && (
        <div className="text-bodySm text-text-secondary">{skill.description}</div>
      )}

      {!!skill.escalation?.length && (
        <table
          data-testid="escalation-table"
          className="mt-2 w-full border-collapse text-caption"
        >
          <thead>
            <tr>
              <th className="border-t border-border-subtle py-0.5 pr-2 text-left font-normal text-text-muted">
                触发条件（观测到即升级）
              </th>
              <th className="border-t border-border-subtle py-0.5 pr-2 text-left font-normal text-text-muted">
                缓解手册
              </th>
            </tr>
          </thead>
          <tbody>
            {skill.escalation.map((e, i) => (
              <tr key={i}>
                {/* ★ 原文展示，不转述 */}
                <td className="border-t border-border-subtle py-0.5 pr-2 align-top">
                  {e.observation}
                </td>
                <td
                  className={`border-t border-border-subtle py-0.5 pr-2 align-top whitespace-nowrap ${MONO}`}
                >
                  {e.escalate_to}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
