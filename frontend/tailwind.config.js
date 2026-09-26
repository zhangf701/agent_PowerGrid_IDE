// ★ 设计令牌单一真源：这里只 import 生成物（src/design/tokens.generated.js，顶部带
//   「勿手改」标记），**禁止在本文件手抄任何色值/尺寸**。
//   改设计 → 改 design/tokens.json → python tools/build_design_tokens.py 重新生成。
//   护栏：npm run guard（= build_design_tokens.py --check + check_design_tokens.py）。
import tokens from "./src/design/tokens.generated.js";

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["selector", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: tokens.colors,
      spacing: tokens.spacing,
      borderRadius: tokens.borderRadius,
      borderWidth: tokens.borderWidth,
      fontFamily: tokens.fontFamily,
      fontSize: tokens.fontSize,
      boxShadow: tokens.boxShadow,
      zIndex: tokens.zIndex,
      transitionDuration: tokens.transitionDuration,
      transitionTimingFunction: tokens.transitionTimingFunction,
    },
  },
  plugins: [],
};
