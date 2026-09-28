/** SkillCard —— UI 规范 v2 §4.7.3。
 *
 *  ★ **v2 相对 v1.x 最重要的补口**：21 个技能在 v1.x 中零覆盖，而
 *    `Escalation triggers`（观测值 → 缓解手册的数字驱动映射）是**「研究方法」最直接的载体**。
 *
 *  ★ 三条硬规则：
 *    ① 健康度必须显示且**必须允许 unknown** —— 不得渲染成「正常」；
 *    ② `escalation` 必须展示 `observation` **原文**（含反引号内的字段名）——
 *       它是用户判断「我这次是否命中」的唯一依据，**转述会失真**；
 *    ③ 方法手册原文**就地折叠展开**（2026-09-28 张老师裁决，途径 B2）：
 *       数据仍来自网关 `GET /skills/{id}/doc`（磁盘 SKILL.md 唯一真源，**无副本漂移**）；
 *       progressive disclosure —— 摘要常驻、正文按需展开、会话内缓存；
 *       「新标签打开原文」降级为兜底小链接保留。
 *
 *  ⚠️ 展开失败（如 PowerSkills 不在场 → 404）如实显示错误，不吞 —— 与全局「错误可见」同口径。
 */
import { useState } from "react";

import { fetchSkillDoc, type Skill, type SkillDoc } from "../api";
import { parseSkillDoc, type DocBlock, type InlineRun } from "../skillDoc";
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

/** 行内片段渲染（React 转义文本 —— 解析器不产出 HTML，这里也不 innerHTML）。 */
function Runs({ runs }: { runs: InlineRun[] }) {
  return (
    <>
      {runs.map((r, i) =>
        r.code ? (
          <code key={i} className={`${MONO} rounded-sm bg-surface-sunken px-1`}>
            {r.text}
          </code>
        ) : r.bold ? (
          <strong key={i}>{r.text}</strong>
        ) : (
          <span key={i}>{r.text}</span>
        ),
      )}
    </>
  );
}

/** 块渲染（受限白名单：标题 / 段落 / 列表 / 表格 / 代码围栏）。 */
export function DocBlocks({ blocks }: { blocks: DocBlock[] }) {
  return (
    <div className="space-y-1.5 text-caption leading-relaxed">
      {blocks.map((b, i) => {
        switch (b.type) {
          case "heading":
            return (
              <div
                key={i}
                className={
                  b.level <= 1
                    ? "mt-2 text-bodySm font-medium"
                    : b.level === 2
                      ? "mt-2 font-medium text-text-primary"
                      : "mt-1 font-medium text-text-secondary"
                }
              >
                <Runs runs={b.runs} />
              </div>
            );
          case "paragraph":
            return (
              <p key={i} className="text-text-secondary">
                <Runs runs={b.runs} />
              </p>
            );
          case "list":
            return b.ordered ? (
              <ol key={i} className="ml-4 list-decimal space-y-0.5 text-text-secondary">
                {b.items.map((runs, j) => (
                  <li key={j}><Runs runs={runs} /></li>
                ))}
              </ol>
            ) : (
              <ul key={i} className="ml-4 list-disc space-y-0.5 text-text-secondary">
                {b.items.map((runs, j) => (
                  <li key={j}><Runs runs={runs} /></li>
                ))}
              </ul>
            );
          case "table":
            return (
              <table key={i} className="w-full border-collapse text-caption">
                <thead>
                  <tr>
                    {b.header.map((runs, j) => (
                      <th
                        key={j}
                        className="border-t border-border-subtle py-0.5 pr-2 text-left font-normal text-text-muted"
                      >
                        <Runs runs={runs} />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {b.rows.map((row, j) => (
                    <tr key={j}>
                      {row.map((runs, k) => (
                        <td
                          key={k}
                          className="border-t border-border-subtle py-0.5 pr-2 align-top text-text-secondary"
                        >
                          <Runs runs={runs} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            );
          case "code":
            return (
              <pre
                key={i}
                className={`${MONO} overflow-auto rounded-sm bg-code-bg p-2 text-caption text-code-fg`}
              >
                {b.text}
              </pre>
            );
        }
      })}
    </div>
  );
}

type DocState =
  | { phase: "closed" }
  | { phase: "loading" }
  | { phase: "open"; doc: SkillDoc }
  | { phase: "error"; message: string };

export function SkillCard({ skill }: { skill: Skill }) {
  // ★ 会话内缓存由 `fetchSkillDoc` 的模块级 Map 承担（SKILL.md 是磁盘静态文件，
  //   与「不得缓存」的 /cases 现算字段不同类）；这里只管展开状态。
  const [doc, setDoc] = useState<DocState>({ phase: "closed" });

  async function toggleDoc() {
    if (doc.phase === "open") {
      setDoc({ phase: "closed" });
      return;
    }
    if (doc.phase === "loading") return;
    setDoc({ phase: "loading" });
    try {
      setDoc({ phase: "open", doc: await fetchSkillDoc(skill.id) });
    } catch (err) {
      setDoc({ phase: "error", message: (err as Error).message });
    }
  }

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

      {/* ★ 方法手册入口（主路径 = 就地折叠展开；兜底 = 新标签看原文）。
          链接/取数都走网关 `GET /skills/{id}/doc`（按索引定位，无路径穿越）。 */}
      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-caption">
        <button
          type="button"
          onClick={() => void toggleDoc()}
          aria-expanded={doc.phase === "open"}
          data-testid="skill-doc-toggle"
          className="rounded-sm border border-border-subtle px-2 py-0.5 hover:bg-interactive-subtle"
        >
          {doc.phase === "open" ? "收起方法手册 ▴" : "方法手册（SKILL.md）▾"}
        </button>
        <a
          href={`/skills/${encodeURIComponent(skill.id)}/doc`}
          target="_blank"
          rel="noreferrer"
          className="text-text-muted underline hover:bg-interactive-subtle"
        >
          新标签打开
        </a>
        {skill.path && <span className={`${MONO} text-text-muted`}>{skill.path}</span>}
      </div>

      {doc.phase === "loading" && (
        <div className="mt-2 text-caption text-text-muted" data-testid="skill-doc-loading">
          读取方法手册中…
        </div>
      )}
      {doc.phase === "error" && (
        <div
          className="mt-2 text-caption text-contract-violated-fg"
          data-testid="skill-doc-error"
        >
          ✖ 文档读取失败：{doc.message}
        </div>
      )}
      {doc.phase === "open" && (
        <div
          className="mt-2 rounded-sm border border-border-subtle bg-surface-sunken p-2"
          data-testid="skill-doc-body"
        >
          <DocBlocks blocks={parseSkillDoc(doc.doc.content)} />
        </div>
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
