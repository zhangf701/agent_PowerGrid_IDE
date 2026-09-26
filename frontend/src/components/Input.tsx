/** Input —— UI 规范 v2 §4.6.2（文本输入部分）。
 *
 *  ⚠️ §4.6.2 的完整形态是控制头部的**五个**内联选择器（server 多选 / provider / model /
 *     算例 / 契约严格度），其中 server 多选需要 combobox + 多选 chip。
 *     那些选择器**随所属视图**落地（对话分析视图），此处只做通用文本输入。
 *  ★ 颜色只引用语义层；聚焦环走 `--c-interactive-default`（`outline-interactive-default`）。
 */
import type { InputHTMLAttributes } from "react";

export function Input({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={`rounded-md border border-border-subtle bg-surface-raised px-3 py-2 text-body text-text-primary placeholder:text-text-muted focus:outline focus:outline-2 focus:outline-interactive-default ${className}`}
      {...rest}
    />
  );
}
