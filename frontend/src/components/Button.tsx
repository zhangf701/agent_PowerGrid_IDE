/** Button —— UI 规范 v2 §4.6.1。
 *
 *  变体：`primary` 主操作 · `secondary` 次操作 · `ghost` 行内操作 · `danger` 不可逆操作。
 *  高度：`sm` 32px · `md` 40px（走 `--p-space-8` / `--p-space-10`）。
 *
 *  ★ 颜色**只**引用语义层（`--c-*`），不出现任何原始色值。
 *  ★ `danger` 走 `violated` 状态签名 —— 与界面其它地方的「违反」同色，语义一致。
 *  ⚠️ 危险操作的**确认**不走通用弹窗，而用「影响面预评估」（§4.6.3 / §7.3）；
 *     本组件只承载确认后的最终执行按钮。
 */
import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

const VARIANT: Record<ButtonVariant, string> = {
  primary:
    "border-interactive-default bg-interactive-default text-text-inverse hover:bg-interactive-hover",
  secondary:
    "border-border-default bg-surface-raised text-text-primary hover:bg-interactive-subtle",
  ghost:
    "border-transparent bg-transparent text-text-secondary hover:bg-interactive-subtle",
  danger:
    "border-contract-violated-border bg-contract-violated-bg text-contract-violated-fg hover:border-contract-violated-fg",
};

const SIZE: Record<ButtonSize, string> = {
  sm: "h-8 px-3 text-bodySm",
  md: "h-10 px-4 text-body",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export function Button({
  variant = "secondary",
  size = "sm",
  className = "",
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={`inline-flex flex-none items-center justify-center gap-2 rounded-md border font-medium transition-colors focus:outline focus:outline-2 focus:outline-interactive-default ${VARIANT[variant]} ${SIZE[size]} ${className}`}
      {...rest}
    />
  );
}
