/** SKILL.md 原文 → 受限块结构（技能手册折叠展开的数据基础，2026-09-28 裁决 B2）。
 *
 *  ★ 为什么自己写而不用 markdown 库：项目 Node 不走 `npm install`（毁依赖树），
 *    而 PowerSkills 的 SKILL.md 结构**封闭且简单**（frontmatter / 标题 / 表格 /
 *    有序无序列表 / 代码围栏 / 段落 / 行内 `code` 与 **粗体**）——
 *    一个 ~百行的**白名单解析器**比引入完整 markdown 引擎更可控、可测、可审计。
 *
 *  ★ 安全边界（硬规则）：**纯文本解析，绝不产出 HTML 字符串** —— 所有文本由
 *    React 转义渲染，`<script>` 之类只会作为字面文本出现（有测试钉住）。
 *    未认识的语法 → 原样作为段落文本（**不猜**、不丢字）。
 *
 *  ★ progressive disclosure 的数据面：卡片摘要（frontmatter description）是
 *    「有这个技能」；本解析器的输出是「技能内容」—— 两者同源（同一文件），无副本。
 */

/** 行内片段：`code` / **粗体** / 普通文本。 */
export interface InlineRun {
  text: string;
  code?: boolean;
  bold?: boolean;
}

export type DocBlock =
  | { type: "heading"; level: number; runs: InlineRun[] }
  | { type: "paragraph"; runs: InlineRun[] }
  | { type: "list"; ordered: boolean; items: InlineRun[][] }
  | { type: "table"; header: InlineRun[][]; rows: InlineRun[][][] }
  | { type: "code"; text: string };

/** 行内解析：先按反引号切 code 段，非 code 段再解析 `**粗体**`。
 *  ⚠️ 不支持嵌套（`**`code`**` 之类）—— SKILL.md 里没有，不猜。 */
export function parseInline(text: string): InlineRun[] {
  const runs: InlineRun[] = [];
  // 反引号必须成对才生效；不成对 → 整段按普通文本（不猜）
  const parts = text.split("`");
  if (parts.length % 2 === 0) {
    return text ? [{ text }] : [];
  }
  parts.forEach((part, i) => {
    if (i % 2 === 1) {
      if (part) runs.push({ text: part, code: true });
      return;
    }
    // 非 code 段：解析 **粗体**
    const pieces = part.split("**");
    pieces.forEach((piece, j) => {
      if (!piece) return;
      runs.push(j % 2 === 1 ? { text: piece, bold: true } : { text: piece });
    });
  });
  return runs;
}

/** 表格行：`| a | b |` → ["a","b"]；两端竖线可有可无（PowerSkills 的都有）。 */
function splitTableRow(line: string): string[] | null {
  const trimmed = line.trim();
  if (!trimmed.startsWith("|") || !trimmed.endsWith("|") || trimmed.length < 2) return null;
  return trimmed
    .slice(1, -1)
    .split("|")
    .map((c) => c.trim());
}

/** 分隔行：`|---|:---:|---|` */
function isTableSeparator(cells: string[]): boolean {
  return cells.length > 0 && cells.every((c) => /^:?-{3,}:?$/.test(c));
}

/** 解析 SKILL.md 全文 → 块数组。
 *  - 文件开头的 frontmatter（`---` … `---`）**跳过**：name/description 已是卡片摘要；
 *  - 未认识的行 → 段落文本原样保留。 */
export function parseSkillDoc(raw: string): DocBlock[] {
  const lines = raw.replace(/\r\n/g, "\n").split("\n");
  const blocks: DocBlock[] = [];

  // frontmatter：仅当**第一个非空行**是 `---` 时按元数据块跳过
  let i = 0;
  while (i < lines.length && lines[i].trim() === "") i += 1;
  if (lines[i]?.trim() === "---") {
    i += 1;
    while (i < lines.length && lines[i].trim() !== "---") i += 1;
    i += 1; // 跳过收尾 ---
  }

  let paragraph: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ type: "paragraph", runs: parseInline(paragraph.join(" ")) });
      paragraph = [];
    }
  };

  while (i < lines.length) {
    const line = lines[i];

    // 代码围栏：``` 到下一行 ```（不解析围栏内任何语法）
    if (line.trimStart().startsWith("```")) {
      flushParagraph();
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trimStart().startsWith("```")) {
        body.push(lines[i]);
        i += 1;
      }
      blocks.push({ type: "code", text: body.join("\n") });
      i += 1; // 跳过收尾 ```
      continue;
    }

    // 标题
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flushParagraph();
      blocks.push({ type: "heading", level: heading[1].length, runs: parseInline(heading[2]) });
      i += 1;
      continue;
    }

    // 表格：`|` 行起头 + 下一行是分隔行才成表（无分隔行 → 保守当段落）
    const row = splitTableRow(line);
    if (row) {
      const next = lines[i + 1];
      const sep = next ? splitTableRow(next) : null;
      if (sep && isTableSeparator(sep)) {
        flushParagraph();
        const header = row;
        i += 2;
        const rows: InlineRun[][][] = [];
        while (i < lines.length) {
          const r = splitTableRow(lines[i]);
          if (!r) break;
          rows.push(r.map((c) => parseInline(c)));
          i += 1;
        }
        blocks.push({ type: "table", header: header.map((c) => parseInline(c)), rows });
        continue;
      }
    }

    // 列表：`- ` / `* `（无序）与 `N. `（有序）；同标记连续行归一组
    const unordered = /^[-*]\s+(.*)$/.exec(line.trim());
    const ordered = /^\d+[.)]\s+(.*)$/.exec(line.trim());
    if (unordered || ordered) {
      flushParagraph();
      const isOrdered = Boolean(ordered);
      const items: InlineRun[][] = [];
      while (i < lines.length) {
        const m = isOrdered
          ? /^\d+[.)]\s+(.*)$/.exec(lines[i].trim())
          : /^[-*]\s+(.*)$/.exec(lines[i].trim());
        if (!m) break;
        items.push(parseInline(m[1]));
        i += 1;
      }
      blocks.push({ type: "list", ordered: isOrdered, items });
      continue;
    }

    // 空行 → 段落终结
    if (line.trim() === "") {
      flushParagraph();
      i += 1;
      continue;
    }

    // 其余：普通文本行，连续行合并成段（SKILL.md 的段落有手动换行）
    paragraph.push(line.trim());
    i += 1;
  }
  flushParagraph();
  return blocks;
}
