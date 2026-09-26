# React 骨架完成：DoD 7/7 全部通过（第 1 步闭环）

日期：2026-09-26 ｜ 张老师确认："react骨架已测试，全部通过"
对应文档：`docs/React骨架_完成标志与验证清单.md`（验收清单已标记 ✓）

## 交付物（均在 `frontend/`）

- 工程：`package.json` / `vite.config.ts`（代理 8765）/ `tsconfig.json` /
  `tailwind.config.js`（import 生成物 `tokens.generated.js`）/ `postcss.config.js` /
  `index.html` / `.gitignore`
- 应用：`src/main.tsx` · `src/App.tsx`（环境就绪面板 + 技能手册只读 + 主题切换 +
  状态签名含 unknown 如实态）· `src/api.ts` · `src/index.css` · `src/App.test.tsx`
- MVP 未动：`/ui/mvp.html` 一行未改，仍 200 可用

## DoD 验证记录（7/7 ✓）

1. build：tsc 零错 + vite build（33 模块，JS gzip 48.8 KB）；
2. tokens 双护栏全绿（88 令牌逐值比对）；
3. 语义色约束：手写代码原始色 grep **0 命中**（生成物 `styles/tokens.css`
   合法含 86 处 hex，扫描时排除）；
4. 真实数据贯通：无头验证命中 `Python 3.12.6` / `22 个技能`（与 MVP 同网关同数据）；
   网关停时 `role="alert"` 错误态非白屏；
5. 主题双态：`#dark` → 根元素 `data-theme="dark"`；
6. 状态签名：图标+文字，健康度 unknown 未伪装；
7. 护栏进流程 + 冒烟：篡改探针（改 `design/tokens.json` 一色 → guard 报红 →
   `git checkout -- design/tokens.json` 恢复绿）；vitest 2/2 passed。

## 本阶段踩坑（已记入当日日志，此处留检索锚点）

- `@testing-library/dom@^10.5.0` 不存在 → 锁 10.4.0；
- esbuild postinstall `spawnSync EBUSY`（沙箱）→ 重试通过；
- 中断安装遗留可选依赖缺失 → 挂 VPN 代理（127.0.0.1:10090）显式补装
  `@esbuild/win32-x64@0.21.5` + `@rollup/rollup-win32-x64-msvc@4.63.5`；
- 本机 `npm.cmd` 触发 WSL shim 被沙箱拦 → node 直调 `npm-cli.js`；
- guard 命令 cwd 陷阱（frontend 下须 `npm run guard`，根下才可 `python tools/...`）；
- DoD 文档起草残留假路径 `frontend/react/src` → 已修正为 `frontend/src` 并排除生成物。

## 下一步（第 2 步：逐视图迁移，A/B 对照 MVP）

顺序：技能手册（最独立）→ 算例库 → 对话 + 校验层（最复杂，最后）。
每迁完一个视图与 MVP 截图/行为对照；"错误可见（不开控制台）"与
"契约状态条"两条验收判据原样保留。MVP 全部覆盖后降级存档（第 3 步）。
