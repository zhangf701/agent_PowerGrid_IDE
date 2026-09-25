# frontend —— PowerMCP 前端

> **当前状态（2026-09-25）：设计系统已落地，React 工程尚未起步。**
> 本目录现在只有**从 `design/tokens.json` 生成的产物**，零 npm 依赖、零构建步骤。

## 目录

```
frontend/
├── preview.html                      ← 设计令牌可视化预览（双击即可打开）
└── src/
    ├── styles/tokens.css             ← 生成：两套 CSS 变量（light / dark）
    └── design/tokens.generated.js    ← 生成：状态签名等数据 + Tailwind 主题扩展
```

> ⚠️ `src/` 下两个文件**都是生成的**，顶部有「勿手改」标记。
> 改设计要改 `design/tokens.json`，然后重新生成。

## 生成链（单一真源）

```
design/tokens.json  ──build_design_tokens.py──▶  tokens.css
      （真源）        │                            tokens.generated.js
                     │                            preview.html
                     └──check_design_tokens.py──▶  （校验：文档 ↔ JSON ↔ CSS 三者一致）
```

```bash
# 生成
python tools/build_design_tokens.py

# 校验产物是否与真源同步（护栏；可放进 pre-commit / CI）
python tools/build_design_tokens.py --check

# 校验「规范文档 ↔ tokens.json ↔ 生成的 CSS」三者一致
python tools/check_design_tokens.py
```

## 两道护栏分别防什么

| 护栏 | 防的失败模式 |
|---|---|
| `build_design_tokens.py --check` | **产物与真源漂移** —— 有人手改了 `tokens.css`，或改了 JSON 忘了重新生成 |
| `check_design_tokens.py` 第 4 项 | **命名映射表漂移** —— `build_design_tokens.py` 复制了一份「JSON 路径 → CSS 变量名」映射（与文档同源）。两处一旦不一致，生成的 CSS 会给前端**错的变量名**，而文档校验却是绿的 |

## 预览页

直接双击 `preview.html`（或 `preview.html#dark` 看深色）即可。

它**直接引用** `src/styles/tokens.css`，因此「预览页正常」本身就证明生成链是通的。
预览页展示：5 个状态签名 · 7 组语义色 · 间距 / 圆角 / 描边 / 阴影 / 动效 / 层级 / 字号阶梯。

## 下一步（未做）

1. **React + Vite + TypeScript 工程骨架** —— `package.json` / `vite.config.ts` / `tailwind.config.js`
   （后者 import `src/design/tokens.generated.js` 的 `tailwindTheme`）。
2. **通用基础件**：Button / Input / Select / Command / Dialog / Toast / EmptyState /
   LoadingState / ErrorState / EngineStatusIndicator（规格见
   [UI 设计规范](../docs/PowerMCP_UI设计规范.md) §4.6）。
3. **研究视图组件**（§4.7）：`VerificationLayer` / `CaseCard` / `SkillCard` /
   `ResultTable` / `ExperimentGrid` / `ModuleBadge`。

## 硬约束（来自 UI 设计规范 v2）

- **颜色只能引用语义层**（`--c-*`）；原始层颜色**不**暴露为 CSS 变量（否则深色主题失效）。
  尺寸 / 字体 / 动效 / 层级可以用 `--p-*`。
- **颜色不得单独承载信息** —— 每个状态必须同时含图标 + 文字（状态签名机制）。
- 主题切换靠根元素 `data-theme`，**不**跟随 `prefers-color-scheme`。
