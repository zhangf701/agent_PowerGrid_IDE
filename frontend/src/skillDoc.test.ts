/** parseSkillDoc 单测 —— 白名单解析器的行为与安全边界（2026-09-28 裁决 B2）。
 *
 *  ★ 用**真实 SKILL.md 的形状**做夹具（frontmatter / 表格 / 有序列表 / 行内 code），
 *    不发明语法；安全用例（HTML 注入当文本）必须有。
 */
import { describe, expect, it } from "vitest";

import { parseInline, parseSkillDoc } from "./skillDoc";

const SAMPLE = `---
name: thermal-overload-mitigation
description: Senior power-engineer playbook.
---

# Thermal overload mitigation

Start with the monitored element, the applicable rating.

## Preferred action order
1. Confirm the overload is real.
2. Redispatch generation to unload the corridor.

### Worked example
Line A-B sits at 105% of its normal rating, so shifting
40 MW off G3 onto G5 unloads it.

## Escalation triggers

| Observation | Escalate to |
|---|---|
| \`loading_percent\` > 100 | \`thermal-overload-mitigation\` |

\`\`\`
code block stays verbatim
\`\`\`
`;

describe("parseInline", () => {
  it("行内 code 与粗体", () => {
    const runs = parseInline("keep \`loading_percent\` under **100%**");
    expect(runs).toEqual([
      { text: "keep " },
      { text: "loading_percent", code: true },
      { text: " under " },
      { text: "100%", bold: true },
    ]);
  });

  it("不成对的反引号 → 整段普通文本（不猜）", () => {
    expect(parseInline("a ` b")).toEqual([{ text: "a ` b" }]);
  });
});

describe("parseSkillDoc", () => {
  const blocks = parseSkillDoc(SAMPLE);

  it("跳过 frontmatter（name/description 已是卡片摘要）", () => {
    const all = JSON.stringify(blocks);
    expect(all).not.toContain("Senior power-engineer playbook");
  });

  it("标题分级", () => {
    const headings = blocks.filter((b) => b.type === "heading");
    expect(headings.map((h) => (h.type === "heading" ? h.level : 0))).toEqual([1, 2, 3, 2]);
  });

  it("有序列表各项成块", () => {
    const list = blocks.find((b) => b.type === "list");
    expect(list?.type).toBe("list");
    if (list?.type !== "list") return;
    expect(list.ordered).toBe(true);
    expect(list.items).toHaveLength(2);
  });

  it("连续普通行合并成一段（SKILL.md 段落有手动换行）", () => {
    const paras = blocks.filter((b) => b.type === "paragraph");
    const joined = paras.map((p) => (p.type === "paragraph" ? p.runs.map((r) => r.text).join("") : ""));
    expect(joined.some((t) => t.includes("40 MW off G3 onto G5"))).toBe(true);
  });

  it("表格：表头 + 数据行，单元格保留行内 code", () => {
    const table = blocks.find((b) => b.type === "table");
    expect(table?.type).toBe("table");
    if (table?.type !== "table") return;
    expect(table.header.map((c) => c.map((r) => r.text).join(""))).toEqual([
      "Observation",
      "Escalate to",
    ]);
    const firstCell = table.rows[0][0].map((r) => r.text).join("");
    expect(firstCell).toBe("loading_percent > 100");
    expect(table.rows[0][0].some((r) => r.code)).toBe(true);
  });

  it("代码围栏逐字保留", () => {
    const code = blocks.find((b) => b.type === "code");
    expect(code?.type).toBe("code");
    if (code?.type !== "code") return;
    expect(code.text).toBe("code block stays verbatim");
  });

  it("★ 安全：HTML 标签只作为字面文本（不产出 HTML、不被解析）", () => {
    const blocks = parseSkillDoc("# t\n\n<script>alert(1)</script>");
    const para = blocks.find((b) => b.type === "paragraph");
    expect(para?.type).toBe("paragraph");
    if (para?.type !== "paragraph") return;
    expect(para.runs.map((r) => r.text).join("")).toBe("<script>alert(1)</script>");
  });

  it("无分隔行的 | 行保守当段落（不猜表格）", () => {
    const blocks = parseSkillDoc("| not | a table |");
    expect(blocks).toHaveLength(1);
    expect(blocks[0].type).toBe("paragraph");
  });
});
