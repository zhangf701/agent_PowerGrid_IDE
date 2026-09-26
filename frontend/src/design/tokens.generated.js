// 由 tools/build_design_tokens.py 从 design/tokens.json 生成 —— 勿手改
// 真源版本：1.0.0（2026-09-24）

/** 状态签名 —— 5 态 × (icon + label)。**不得**在组件里手写图标字符。 */
export const stateSignature = {
  "satisfied": {
    "icon": "✔",
    "label": "满足",
    "shortLabel": "满足",
  },
  "degraded": {
    "icon": "▲",
    "label": "降级",
    "shortLabel": "降级",
  },
  "violated": {
    "icon": "✖",
    "label": "违反",
    "shortLabel": "违反",
  },
  "unknown": {
    "icon": "?",
    "label": "未知",
    "shortLabel": "未知",
  },
  "incident": {
    "icon": "!",
    "label": "事故",
    "shortLabel": "事故",
  },
};

/** 未知态成因（structural / incident）—— 决定是否升至主徽章。 */
export const unknownReason = {
  "structural": {
    "examples": ["契约 4 无法推断引擎返回码语义", "OpenDSS 工具面未核实", "该引擎的编号约定未实测"],
  },
  "incident": {
    "examples": ["契约引擎进程崩溃", "契约引擎熔断已打开", "SSE 事件未通过 Zod 校验"],
  },
};

/** contractTypes —— 真源 design/tokens.json */
export const contractTypes = {
  "1": "API 版本契约",
  "2": "文档-实现一致性",
  "3": "参数契约",
  "4": "状态映射契约",
  "5": "命名空间契约",
  "6": "标识符契约",
  "7": "量纲契约",
  "8": "运行时依赖契约",
};

/** identifierConvention —— 真源 design/tokens.json */
export const identifierConvention = {
  "byOutput": {
    "surge.run_ac_power_flow.bus_numbers": "1-based",
    "surge.run_n1_branch_contingency.bus_number": "1-based",
  },
  "byEngine": {
    "pandapower": "0-based",
    "surge": "0-based",
    "pypsa": "1-based",
    "andes": "unknown",
    "egret": "unknown",
    "opendss": "unknown",
    "hope": "unknown",
    "genx": "unknown",
    "powerio": "unknown",
  },
  "suffix": {
    "0-based": "(0-based)",
    "1-based": "(1-based)",
    "unknown": "(约定未知)",
  },
};

/** engineChartColor —— 真源 design/tokens.json */
export const engineChartColor = {
  "pandapower": "cat-1",
  "pypsa": "cat-2",
  "surge": "cat-3",
  "andes": "cat-4",
  "egret": "cat-5",
  "hope": "cat-6",
  "genx": "cat-7",
  "opendss": "cat-8",
  "powerio": "cat-9",
};

/**
 * Tailwind 主题扩展。颜色与尺寸**一律引用 CSS 变量**（tokens.css），
 * 因此改 design/tokens.json 即全局生效，组件零改动。
 */
export const tailwindTheme = {
  "colors": {
    "surface": {
      "base": "var(--c-surface-base)",
      "raised": "var(--c-surface-raised)",
      "sunken": "var(--c-surface-sunken)",
      "overlay": "var(--c-surface-overlay)",
    },
    "text": {
      "primary": "var(--c-text-primary)",
      "secondary": "var(--c-text-secondary)",
      "muted": "var(--c-text-muted)",
      "inverse": "var(--c-text-inverse)",
    },
    "border": {
      "subtle": "var(--c-border-subtle)",
      "default": "var(--c-border-default)",
      "strong": "var(--c-border-strong)",
      "focus": "var(--c-border-focus)",
    },
    "interactive": {
      "default": "var(--c-interactive-default)",
      "hover": "var(--c-interactive-hover)",
      "active": "var(--c-interactive-active)",
      "subtle": "var(--c-interactive-subtle)",
    },
    "contract": {
      "satisfied": {
        "bg": "var(--c-contract-satisfied-bg)",
        "border": "var(--c-contract-satisfied-border)",
        "fg": "var(--c-contract-satisfied-fg)",
      },
      "degraded": {
        "bg": "var(--c-contract-degraded-bg)",
        "border": "var(--c-contract-degraded-border)",
        "fg": "var(--c-contract-degraded-fg)",
      },
      "violated": {
        "bg": "var(--c-contract-violated-bg)",
        "border": "var(--c-contract-violated-border)",
        "fg": "var(--c-contract-violated-fg)",
      },
      "unknown": {
        "bg": "var(--c-contract-unknown-bg)",
        "border": "var(--c-contract-unknown-border)",
        "fg": "var(--c-contract-unknown-fg)",
      },
      "incident": {
        "bg": "var(--c-contract-incident-bg)",
        "border": "var(--c-contract-incident-border)",
        "fg": "var(--c-contract-incident-fg)",
      },
    },
    "code": {
      "bg": "var(--c-code-bg)",
      "fg": "var(--c-code-fg)",
    },
    "chart": {
      "grid": "var(--c-chart-grid)",
      "axis": "var(--c-chart-axis)",
      "cat": {
        "1": "var(--c-chart-cat-1)",
        "2": "var(--c-chart-cat-2)",
        "3": "var(--c-chart-cat-3)",
        "4": "var(--c-chart-cat-4)",
        "5": "var(--c-chart-cat-5)",
        "6": "var(--c-chart-cat-6)",
        "7": "var(--c-chart-cat-7)",
        "8": "var(--c-chart-cat-8)",
        "9": "var(--c-chart-cat-9)",
      },
    },
  },
  "spacing": {
    "0": "var(--p-space-0)",
    "1": "var(--p-space-1)",
    "2": "var(--p-space-2)",
    "3": "var(--p-space-3)",
    "4": "var(--p-space-4)",
    "5": "var(--p-space-5)",
    "6": "var(--p-space-6)",
    "8": "var(--p-space-8)",
    "10": "var(--p-space-10)",
    "12": "var(--p-space-12)",
    "16": "var(--p-space-16)",
  },
  "borderRadius": {
    "none": "var(--p-radius-none)",
    "sm": "var(--p-radius-sm)",
    "md": "var(--p-radius-md)",
    "lg": "var(--p-radius-lg)",
    "xl": "var(--p-radius-xl)",
    "full": "var(--p-radius-full)",
  },
  "borderWidth": {
    "hairline": "var(--p-border-hairline)",
    "thick": "var(--p-border-thick)",
  },
  "fontFamily": {
    "sans": ["var(--p-font-sans)"],
    "mono": ["var(--p-font-mono)"],
  },
  "fontSize": {
    "display": "var(--p-font-size-display)",
    "h1": "var(--p-font-size-h1)",
    "h2": "var(--p-font-size-h2)",
    "body": "var(--p-font-size-body)",
    "bodySm": "var(--p-font-size-bodySm)",
    "caption": "var(--p-font-size-caption)",
    "mono": "var(--p-font-size-mono)",
  },
  "boxShadow": {
    "sm": "var(--p-shadow-sm)",
    "md": "var(--p-shadow-md)",
    "lg": "var(--p-shadow-lg)",
  },
  "zIndex": {
    "base": "var(--p-z-base)",
    "sticky": "var(--p-z-sticky)",
    "dropdown": "var(--p-z-dropdown)",
    "drawer": "var(--p-z-drawer)",
    "modal": "var(--p-z-modal)",
    "toast": "var(--p-z-toast)",
    "tooltip": "var(--p-z-tooltip)",
  },
  "transitionDuration": {
    "fast": "var(--p-duration-fast)",
    "base": "var(--p-duration-base)",
    "slow": "var(--p-duration-slow)",
  },
  "transitionTimingFunction": {
    "standard": "var(--p-easing-standard)",
    "enter": "var(--p-easing-enter)",
    "exit": "var(--p-easing-exit)",
  },
};

export default tailwindTheme;
