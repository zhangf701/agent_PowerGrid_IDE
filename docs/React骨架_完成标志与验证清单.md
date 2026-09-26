# React 骨架：完成标志（DoD）与直观验证方法

> 2026-09-26 · 对应《MVP崩溃后技术栈评估与建议.md》第 1 步"React 骨架先行"。
> 原则：**每条完成标志都必须有一条可以当场执行的验证命令或动作**——
> "能跑起来"不算完成，"跑起来且被检查过"才算。

## 一、范围界定（先说清楚"骨架"不是什么）

骨架阶段 **只做** `frontend/README.md` "下一步"的第 1 项 + 一条真实数据链路：

- ✅ 工程：`package.json` / `vite.config.ts` / `tsconfig.json` / `tailwind.config.js`（import `tokens.generated.js` 的 `tailwindTheme`）
- ✅ 一条**真实数据**贯通：dev server 代理 → 网关 → 页面渲染（选一个只读端点）
- ✅ 主题双态 + 令牌护栏接入
- ❌ **不做**：基础件全家桶（§4.6）、研究视图组件（§4.7）、算例库/对话迁移——那是第 2 步
- ❌ **不动** MVP：`/ui/mvp.html` 保持原样可用（它仍是对照基准与回退手段）

## 二、完成标志（DoD，7 条）

| # | 标志 | 判定标准 |
|---|---|---|
| 1 | **工程可构建** | `npm run build`（tsc + vite build）**零错误零 TS 报警**；`npm run dev` 可启动 |
| 2 | **令牌单一真源接通** | `tailwind.config.js` import 的是 `src/design/tokens.generated.js`（生成的），**不得手抄色值**；`build_design_tokens.py --check` 与 `check_design_tokens.py` 双护栏全绿 |
| 3 | **语义色约束生效** | 代码中颜色只允许 `--c-*` 语义层 / Tailwind 语义 token；原始色值（hex/rgb）除生成物外**零出现** |
| 4 | **代理层打通** | vite dev proxy 把 `/` 转发到 `http://127.0.0.1:8765`；页面用**真实网关数据**渲染（非 mock） |
| 5 | **主题双态正确** | `data-theme` 切换 light/dark，两态下文字均可读；不跟随 `prefers-color-scheme`（UI 规范 v2 硬约束） |
| 6 | **状态签名机制落地** | 页面上至少一处状态展示做到**图标 + 文字**（不许颜色单独承载信息）；`contract-unknown` 态如实显示"未判定"而非绿/红 |
| 7 | **护栏进流程** | tokens `--check` 挂进 pre-commit 或 npm script（`npm run guard`）；React 侧至少 1 条 Testing Library 冒烟测试可通过 |

## 三、直观验证方法（每条 DoD 怎么查）

| DoD | 验证动作（当场可执行） | 通过长什么样 |
|---|---|---|
| 1 | `npm run build`；再 `npm run preview` 打开产物 | 终端无红；浏览器出页面 |
| 2 | `python tools/build_design_tokens.py --check && python tools/check_design_tokens.py`（**项目根下执行**；`frontend/` 下用 `npm run guard`） | 两脚本退出码 0 |
| 3 | 原始色扫描：`grep -rInE '#[0-9a-fA-F]{3,8}\|rgba?\(' frontend/src --include='*.ts' --include='*.tsx' --include='*.css' \| grep -v 'styles/tokens.css' \| wc -l`（**项目根下执行**）+ 人工抽查 2~3 个组件样式写法 | 扫描结果 **0**（生成物 `styles/tokens.css` 合法含原始色，已排除；勿扫 `node_modules/` 与 `dist/`）；只见语义 token |
| 4 | 启动网关 + `npm run dev`，打开页面，**对比 MVP 同一端点**（如 `/skills` 的卡片段数与统计行） | React 页与 `127.0.0.1:8765/ui/mvp.html` 显示**同一份真实数据**；网关停掉时页面显示错误态（不是白屏） |
| 5 | 点主题按钮 / 手改根元素 `data-theme`，两态截图对比 | 深色下无"黑底黑字"，浅色下无"白底白字" |
| 6 | 人为制造一次 unknown（如停掉一个 server 看降级提示） | 显示 `? 未判定` 类签名，非假绿灯 |
| 7 | 改一行 `tokens.json` → 跑 `npm run guard`；`npx vitest run` | 护栏对故意漂移**报红**（改回后恢复绿）；冒烟测试 passed |

**一条命令的终检**（骨架 DoD 全量自检，写进 README；**在 `frontend/` 下执行**）：

```bash
npm run build && npm run guard && npx vitest run
# 三段全绿 = 骨架完成；任何一段红 = 未完成
```

⚠️ **cwd 注意**：tokens 护栏脚本有两个等价入口，别混用目录——
- 在 **`frontend/`** 下：`npm run guard`（内部已是 `python ../tools/...`）；
- 在 **项目根** 下：`python tools/build_design_tokens.py --check`。
  在 `frontend/` 下直接敲 `python tools/...` 会报
  `can't open file 'frontend\tools\...'`（目录不对，不是脚本坏了）。

**无头冒烟**（复用 MVP 已验证的思路，防"有头能看、无头白屏"）：

```bash
chrome --headless=new --disable-gpu --dump-dom http://localhost:5173 | grep -c "环境就绪\|技能"
# 命中 ≥1 = 真实数据已渲染到 DOM
```

## 四、验收清单（张老师打勾用）—— ✅ 已于 2026-09-26 全部通过（张老师确认"react骨架已测试，全部通过"）

| 检查项 | 结果 |
|---|---|
| build / dev / preview 三命令可用，TS 零报错 | ✓ |
| tokens 双护栏绿；手写代码 grep 不到原始色 | ✓（原始色 0 命中；护栏篡改探针报红后恢复） |
| 页面显示的是网关真实数据（与 MVP 对照一致） | ✓（无头验证：`Python 3.12.6` / `22 个技能`） |
| 网关停掉 → 页面出错误态而非白屏 | ✓（`role="alert"` 错误横幅） |
| 深/浅主题切换正常、可读 | ✓（`#dark` 下根元素 `data-theme="dark"`） |
| 状态展示 = 图标+文字；unknown 如实显示 | ✓（健康度 unknown 未伪装） |
| `npm run guard` 能抓住故意篡改的令牌 | ✓ |
| 冒烟测试通过；无头 dump-dom 命中数据 | ✓（vitest 2/2） |
| `/ui/mvp.html` 仍正常可用（未被破坏） | ✓（200，一行未动） |

## 五、明确不在验收范围（防止范围蔓延）

- 组件库完整度、算例库/对话/校验层迁移 → 第 2 步（逐视图迁移，A/B 对照 MVP）
- 移动端适配、i18n、性能优化 → 未立项
- `?selftest` 式页面内自检 → React 版用 vitest 替代，不搬进页面
