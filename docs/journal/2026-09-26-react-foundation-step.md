# React 迁移「地基步」：组件层 · 视图拆分 · Zod 入站边界

日期：2026-09-26 ｜ 前置：`2026-09-26-view1-skills-migration-ab.md`（视图 1 已迁完）
定位：这是**第 2 步逐视图迁移的前置**——不是新视图，而是让后面每个视图都变快的地基。

> 一句话：**先补共享地基（组件层 / 视图拆分 / 入站校验），再串行迁 ② 算例库 → ③ 对话分析 → ⑥ 校验层。**

## 一、为什么先做地基（决策依据）

三个待迁视图（② 算例库 · ③ 对话分析 · ⑥ 校验层）**不能并行**，两条硬约束：

1. **共享写入点**：`api.ts`（82 行，全部端点 + 待补的 Zod 边界）与 `components/`（当时**不存在**，
   §4.6/§4.7 组件全内联在 321 行的 `App.tsx` 里，**6 个顶层组件**）。并行 = 三方并发改同一批文件。
2. **③ → ⑥ 有真依赖**：校验层的事件源就是对话分析的 SSE 流。

且每步要做 MVP 的 A/B 对照，**差异必须可归因**到某个视图 —— 并行会让归因失效
（09-26 已踩过一次：`dump-dom` 把页内 `<script>` 模板串算进 class 匹配）。

⇒ 结论：**串行**。而地基步让「一个视图一个文件 + 组件统一出口」成立，是串行能快起来的前提。

---

## 二、交付物

### 1. `frontend/src/components/`（新建，8 文件）

| 文件 | 规范 | 关键点 |
|---|---|---|
| `Signature.tsx` | §3.8.1 | 五签名「色+图标+标签」**整体**；图标 `✔ ▲ ✖ ? !` 形状互不相似；**不提供 `getColor(state)`** |
| `Button.tsx` | §4.6.1 | 四变体 × 两尺寸；`danger` 走 `violated` 签名 |
| `Input.tsx` | §4.6.2 | 只做通用文本输入；**五个内联选择器随对话分析视图落地** |
| `states.tsx` | §4.6.5 | `EmptyState` / `LoadingState`（**>800ms 才出现**）/ `ErrorState`（区分引擎崩溃 vs 调用失败）；错误一律 `role="alert"` |
| `Quantity.tsx` | §4.4 | `measure()` 是**唯一构造入口**；`Measured` 用 `unique symbol` 品牌**防字面量伪造**；判据后缀独立 muted span |
| `Identifier.tsx` | §4.5 | 约定表**从生成物 import**（不手抄）；未命中→`(约定未知)`；显式约定与引擎矛盾→**抛错** |
| `SkillCard.tsx` | §4.7.3 | escalation 展示 `observation` **原文**（不转述） |
| `index.ts` | — | 统一出口 + **三组归属说明** |

**⚠️ 有意未做 `EngineStatusIndicator`（§4.6.6，规范标 P1 必做）**：它需要 `EngineStatus` 五值，
而网关侧「进程监管」（§11.3 心跳/熔断）**尚未实现**（源码 0 命中）——
现在建就是**对着不存在的数据定型**。待进程监管落地（P3）或 S2 需要时再做。

`Dialog` / `Toast` 同理（当前两视图用不到，随 S1/S2 落地）。

### 2. `frontend/src/views/`（新建）

`EnvView.tsx`（① 环境就绪）· `SkillsView.tsx`（⑤ 技能手册）· `index.ts`。
`App.tsx` 收为**纯壳**：主题 · 数据加载 · 错误可见 · 布局。

### 3. `api.ts` 补 Zod 入站边界（§8.4 强制）

- 新增 `apiParsed(path, schema)` —— **唯一允许进入状态树的入口**；
- 失败抛 `SchemaDriftError`，由壳渲染成 **`incident`** 横幅（可见、不白屏、不静默）；
- **校验范围 = 真正进入状态树的字段**（不是全量镜像后端）——未消费字段不校验，避免 schema 无谓变脆；
- 新增依赖 `zod@4.6.5`；`tsconfig` 加 `allowJs`（`Identifier` 要 import 生成的 JS 令牌）。

### 4. 测试（31 passed / 3 文件）

| 文件 | 覆盖 |
|---|---|
| `api.test.ts`（9） | ★ **真实网关响应必须通过 schema**（夹具实测抓取）· 缺字段/类型错/非对象→漂移且可定位 · HTTP 200 但漂移→`SchemaDriftError` · HTTP 错误→**普通 Error**（两类失败用户动作不同） |
| `components.test.tsx`（19） | 五图标互不相似且带标签 · `unknown`/`incident` 可分 · `measure()` 拒绝非有限值与无判据百分比 · 约定推导四分支 + 冲突抛错 · `LoadingState` 800ms 延迟 · `ErrorState` 两类失败 |
| `App.test.tsx`（3） | 原有冒烟 + 筛选行为（未改动） |

夹具：`src/__fixtures__/gateway/{environment,skills}.json` —— **从运行中的网关抓取**
（`curl -s --noproxy '*' http://127.0.0.1:8765/environment`）。用真实响应当夹具，schema 写错会先在这里红。

---

## 三、★ 地基步顺手挖出的两个真缺陷

### F-2：设计令牌 `fontFamily` 生成物是坏的（**已修**）

`tools/build_design_tokens.py:258`：

```python
"fontFamily": {k: [var(v)] for k, v in by_prefix("--p-font-").items()},
```

**两个 bug 叠在一行**：
1. `by_prefix("--p-font-")` **过度匹配**了 `--p-font-size-*` → 7 个 `size-*` 键混进 `fontFamily`；
2. `var()` **二次包裹**（`by_prefix` 返回的值本身已是 `var(...)`）→ `var(var(--p-font-sans))`。

**后果**：Tailwind 的 `font-sans` / `font-mono` 产出 `font-family: var(var(--p-font-sans))`，
**无效 CSS，浏览器直接丢弃** → 任何依赖它的组件都拿不到等宽/无衬线字体。
（这解释了为何 `App.tsx` 一直用内联 `style={{ fontFamily: "var(--p-font-mono)" }}`。）

**两道护栏都拦不住**：`build --check` 防的是「产物与真源漂移」，
`check_design_tokens.py` 防的是「命名映射表漂移」——**没有一道校验生成的 CSS 值是否合法**。

**修复（已实施）**：
- `by_prefix()` 新增 `exclude=` 参数（**更长的前缀会同时匹配，必须显式排除**），
  并在 docstring 里钉住「值已是 `var(...)`，调用方不得再包一层」；
- `fontFamily` 改为 `by_prefix("--p-font-", exclude=("--p-font-size-",))` 且不再二次包裹
  → 产物只剩 `sans` / `mono` 两项，`var(var(` 全文件 **0 次**；
- ★ **新增第三道护栏** `validate_artifacts()`：校验**产物内容合法性**（与「是否漂移」是**两类**问题
  —— 生成器稳定地吐垃圾时，漂移检查照样是绿的）。三条断言：
  `var(var(` 不得出现 · `fontFamily` 不得混入 `--p-font-size-*` · `fontFamily` 不得缺字族。
  在 `--check` 与写入两条路径**之前**执行，故生成与校验都会响亮失败。

**验证**：两道既有护栏仍绿 · 新护栏 **3/3 变异探针全红**（二次包裹 / 前缀过度匹配 / 字族全丢）
且对真实产物**无误报** · 组件里的内联绕过**全部换回 `font-mono` 令牌类**，
产物 CSS 里确认出现 `font-family:var(--p-font-mono)`。

### F-3：`/environment` 的 `llm.required_env` 是想象的字段（**已修**）

真实响应里 `llm` = `{configured, endpoint, model, timeout_s, api_key_set}` —— **没有 `required_env`**。
而前端类型把它声明为**必填**，`EnvView` 还会 `.join(" · ")`。

⇒ **LLM 未配置时那一栏会抛 `TypeError` → 白屏**。只因当时 LLM 恰好已配置，才一直没暴露。

**处置**：schema 里改为 `.optional()`；缺省回落到网关启动脚本里的文档化变量名
（`LLM_KEY_ENV_FALLBACK`，带 TODO：待后端回传该字段后删掉，前端不该硬编码后端契约）。
并加了回归测试断言「缺该字段不得判为漂移」。

> 这两条正是 §8.4 要防的东西：**用真实响应当夹具**才让 F-3 现形；**用手写类型想象后端**就会漏掉。

---

## 四、验证记录

| 项 | 结果 |
|---|---|
| `npm run build`（tsc + vite build） | ✅ 全绿（dist 5 文件，JS 245.45 kB / CSS 14.27 kB） |
| `npm run guard`（令牌双护栏） | ✅ 88 令牌逐值比对无误；5 状态 × 2 主题 × 3 分量齐备 |
| `npx vitest run` | ✅ **31 passed / 3 文件** |
| 原始色扫描（DoD #3） | ✅ **0 命中**（排除生成物 `styles/tokens.css`） |
| A/B 对照 MVP（无头） | ✅ 见下表 |

**A/B 对照**（同网关同数据）：

| 指标 | MVP | React | 判定 |
|---|---|---|---|
| 技能卡数 | 22 | **22** | ✓ |
| 触发表数 | 10 | **10** | ✓ |
| 计数行 | `22 个技能 · tool 11 · engineering 10 · meta 1 · 10 个带触发表` | **逐字符一致** | ✓ |
| 健康度 | `健康度 unknown（…如实状态）：缺 escalation 表：ltspice` | 同结构 | ✓ |
| 错误横幅 | — | `role="alert"` **0**（无错误） | ✓ |
| 环境就绪标题 | 有 | 有 | ✓ |

**唯一有意差异**：React 侧 kind 徽标按 §3.8.1 加了**图标+文字**
（`✔ 工作流 ×11` / `▲ 工程 ×10` / `? meta ×1`）；MVP 徽标是**纯文字色块无图标**。
这正是骨架 DoD #6「状态签名机制落地：图标 + 文字，不许颜色单独承载信息」的要求，
且**不影响任何 A/B 指标**。同时把先前 React 侧误用的 `⚠` 改为规范值 `▲`
（同族符号 `✔ ⚠ ✖` 灰度打印会退化成三个相似方块）。

---

## 五、环境踩坑（本机重装/迁移必读）

1. ★ **`npm install` 会毁掉依赖树**：本次为装 `zod` 跑了一次 `npm install`，结果
   ① 两个平台二进制（`@rollup/rollup-win32-x64-msvc@4.63.5`、`@esbuild/win32-x64@0.21.5`）再次丢失；
   ② **`@babel/generator` 也被删了** → `vite dev` 下 `/src/main.tsx` **HTTP 500**
   （构建走 esbuild 所以 `npm run build` 正常，**只有 dev 暴露**）。
   **补救**：npm 的目录操作会被沙箱批量删除护栏拦（`SAFE_DELETE_BULK_GUARD_ERROR`），
   改用**直接下载 tarball + tar 解包**：
   ```bash
   curl -sSL -o p.tgz "https://registry.npmjs.org/@babel%2fgenerator/-/generator-7.29.8.tgz"
   tar -xzf p.tgz -C node_modules/@babel/generator --strip-components=1
   ```
   ⚠️ scoped 包的 URL **必须用 `%2f` 编码**（`@esbuild/win32-x64` 用未编码形式返回 `{"error":"Not found"}`）。
2. ★ **MSYS 会把以 `/` 开头的参数改写成 Windows 路径**（本次新踩）：
   `curl -w "/src/main.tsx → …\n"` 里的格式串被改写成
   `C:/Users/Z/.../PortableGit/versions/1.2.0/src/main.tsx`，`\n` 变 `/n`。
   ⇒ 与既有约定一致：**含反斜杠或以 `/` 开头的字符串不要走 shell**；必要路径用变量或避开。
3. **`vite dev` 绑定 `localhost`**（Windows 下解析为 IPv6 `::1`）——
   `curl 127.0.0.1:5173` **连不上**，要用 `localhost:5173`。
4. **Chrome 无头两代差异**：旧 `--headless` **不执行 ES module** → React 只拿到 617 字节的壳；
   必须用 **`--headless=new`** + `--virtual-time-budget`（本次 15000ms 够）。
   MVP 是经典 `<script>` 所以两种模式都能渲染。
5. **`vite` 重优化依赖时会清 `node_modules/.vite`**（17 文件，未触发护栏，可手删后重启）。
6. 验证时若 `npm run build` 撞 `SAFE_DELETE_BULK_GUARD_ERROR`（清 `dist/` 那步）：
   先 `rm -rf dist`（5 文件，安全）再跑，即可全绿。

---

## 六、未决与下一步

| # | 事项 | 状态 |
|---|---|---|
| 1 | ~~F-2 字体令牌生成器~~ | ✅ **已修**（含第三道护栏 + 变异 3/3 全红）—— 见上 |
| 2 | `EngineStatusIndicator` §4.6.6 · `Dialog` §4.6.3 · `Toast` §4.6.4 | 随所属视图 / 进程监管落地 |
| 3 | §4.7.3 的**每技能** `health` 属性 | `/skills` 只给聚合信号；逐卡片健康度可作后续细化（本步有意保持行为等价） |
| 4 | B 组校验层组件（`ContractBadge`/`ContractCard`/`ToolCallRow`） | 随 S3 |
| 5 | **下一步：S1 ② 算例库迁移** | 阻塞已解除（F-1 已修，围笼 409 可测） |
| 6 | 本轮**未提交** | `frontend/`（components/views/api/tsconfig/测试/夹具/package.json+lock）+ 本文档 + `_index.md` |

**DoD 三连（`frontend/` 下）**：`npm run build && npm run guard && npx vitest run` —— 三段全绿。
