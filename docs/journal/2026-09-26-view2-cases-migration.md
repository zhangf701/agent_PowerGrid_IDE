# S1 视图迁移：② 算例库（+ F-2 字体令牌修复）

日期：2026-09-26 ｜ 前置：`2026-09-26-react-foundation-step.md`（地基步）
定位：第 2 步「逐视图迁移」的**第 2 个视图**（第 1 个是 ⑤ 技能手册）。串行顺序：⑤ → **②** → ③+⑥。

> 一句话：**算例库已迁完，数据与交互结构与 MVP 一致；围笼 409 分支第一次有了真实界面落点。**

---

## 一、F-2 修复：设计令牌 `fontFamily`（先修它，因为组件要用等宽）

### 缺陷

`tools/build_design_tokens.py` 的 `fontFamily` 生成**两个 bug 叠在一行**：
1. `by_prefix("--p-font-")` **过度匹配** `--p-font-size-*` → 7 个 `size-*` 键混进 `fontFamily`；
2. `var()` **二次包裹**（`by_prefix` 返回的值本身已是 `var(...)`）→ `var(var(--p-font-sans))`。

**后果**：Tailwind 的 `font-sans` / `font-mono` 产出**无效 CSS，浏览器直接丢弃**
（这正是 `App.tsx` 一直用内联 `style` 的原因）。
**两道护栏都拦不住** —— 它们只比对「名字与值的一致性」，**没有一道校验生成的 CSS 值是否合法**。

### 修复

- `by_prefix(prefix, *, exclude=())` —— 新增 `exclude`，并在 docstring 里钉住
  「**更长的前缀会同时匹配**」与「**值已是 `var(...)`，调用方不得再包一层**」两条；
- `fontFamily` 改为 `by_prefix("--p-font-", exclude=("--p-font-size-",))` 且**不再二次包裹**
  → 产物只剩 `sans` / `mono`，全文件 `var(var(` **0 次**；
- ★ **新增第三道护栏** `validate_artifacts()`：校验**产物内容合法性**。
  三条断言：`var(var(` 不得出现 · `fontFamily` 不得混入 `--p-font-size-*` · `fontFamily` 不得缺字族。
  在 `--check` 与写入**两条路径之前**执行 ⇒ 生成与校验都会响亮失败。

> **为什么必须新增第三道**：`build --check` 防「产物与真源漂移」，
> `check_design_tokens.py` 防「命名映射表漂移」—— 而**生成器稳定地吐垃圾时，漂移检查照样是绿的**。
> 三者互不重叠。

### 验证

| 项 | 结果 |
|---|---|
| 两道既有护栏 | ✅ 仍绿（88 令牌） |
| **新护栏变异探针** | ✅ **3/3 全红**（二次包裹 / 前缀过度匹配 / 字族全丢）；对真实产物**无误报** |
| 组件内联绕过 | ✅ 全部换回 `font-mono` 令牌类；产物 CSS 里确认出现 `font-family:var(--p-font-mono)` |

---

## 二、② 算例库迁移

### 交付

| 文件 | 内容 |
|---|---|
| `src/api.ts` | 新增 `CaseSchema` / `CasesResponseSchema` / `CaseRegisterResponseSchema` / `CaseParseResponseSchema` / `CaseUnregisterResponseSchema` |
| `src/components/CaseCard.tsx` | §4.7.2；导出 `fmtBytes`（与 MVP 逐字符同口径）· `parentOf` · `registrationBasis` |
| `src/views/CasesView.tsx` | 登记 / 解析 / 注销 / 选中；每次操作后**重新拉取**（不缓存 `available`/`drift`） |
| `src/App.tsx` | 左栏 `EnvView` 之下挂 `CasesView`（与 MVP 同布局：环境就绪 + 算例库同在 aside） |
| 夹具 | `cases.json`（**2 个算例，其中一个围笼外**）· `case-parse.json` —— 均从运行中的网关抓取 |

### ★ §4.7.2 三条硬规则在界面上的落点

| 硬规则 | 实现 |
|---|---|
| ① `available`/`drift` **现算、不得缓存** | 每次操作后重新 `GET /cases`；schema 不缓存任何派生值 |
| ② `drift=true` 必须显式呈现**且说明基准** | 徽标「内容已变」**+** 「与登记时的哈希不一致（基准 `5b6549ac`（2026-09-25 登记））—— 已解析的结果对应的是**登记时**那份文件」 |
| ③ `within_allowed_roots=false` 必须给**可执行指引** | 徽标「server 读不到」**+** 「该目录不在 `POWERIO_MCP_ALLOWED_ROOTS` 内，server 读不到它 —— 把 `<父目录>` 加入该变量后重启网关」 |

另：`available=false` 时**卡片保留**并说明原因与路径（§4.7.2 反例「卡片直接消失 → 用户以为被删了」的反面）。

### 用 `parse` 一次调用替代 MVP 的两次

MVP 解析流程是 `POST /parse` **再** `GET /ir`，只为读 `value_type` / `ir_bytes` / `ir_parsed`。
`/parse` 的响应已含 `value_type` / `ir_bytes` / `has_ir` ⇒ 少一次往返、少拉 52KB IR 全文，
**提示文案逐字符不变**。

### 与 MVP 的两处**有意差异**（规范强制，非回归）

1. 徽标之外**追加了可见的指引文字**（MVP 只有徽标）——
   §4.7.2 反例明确点名「只说读不到」这种写法。**不用 tooltip**（规范自己批评过
   「悬浮提示在截图/导出里不可见」）。
2. 操作反馈（已登记 / 已解析 / 已注销）**就地显示在面板内**，而 MVP 写进对话流 ——
   ③ 对话分析尚未迁移。**待 S2 落地后应改为 §4.6.4 的 `Toast`（`info` 类型）**。

---

## 三、验证

| 项 | 结果 |
|---|---|
| `npm run build` | ✅ 全绿（JS 250.20 kB / CSS 14.40 kB） |
| `npm run guard` | ✅ 88 令牌 |
| `npx vitest run` | ✅ **48 passed / 4 文件**（31 → +17：api +5 · CaseCard +7 · CasesView +6，另调 App 测试桩） |
| 原始色扫描 | ✅ 0 命中 |
| **A/B 对照 MVP** | ✅ 见下表 |

**A/B 对照**（同网关同数据；MVP 侧计数已扣除页内 `<script>` 模板串）：

| 指标 | MVP（真实渲染） | React | 判定 |
|---|---|---|---|
| 算例卡 | 2 | **2** | ✓ |
| label `case39.m` / `case5.m` | 1 / 1 | **1 / 1** | ✓ |
| 徽标 `server 读不到` | 1 | **1** | ✓ |
| 徽标 `文件不在了` / `内容已变` | 0 / 0（当前无此状态） | **0 / 0** | ✓ |
| 选中 / 解析 / 注销 按钮 | 2 / 2 / 2 | **2 / 2 / 2** | ✓ |
| 登记输入 placeholder | 1 | **1** | ✓ |
| 提示行「不复制文件」 | 1 | **1** | ✓ |

**唯一有意差异**：React 侧多一条**可执行指引**（`该目录不在 POWERIO_MCP_ALLOWED_ROOTS 内 … 把 <父目录> 加入该变量后重启网关`）。

### ★ 围笼 409 分支的验证链

| 环节 | 证据 |
|---|---|
| 网关确实返回 409 且文案可操作 | curl 实测（见 `2026-09-26-case6-closeout-and-fence-defect.md`） |
| 界面把它渲染成**可操作**的错误横幅 | `CasesView.test.tsx` 用**网关真实 409 文案**断言：含 `POWERIO_MCP_ALLOWED_ROOTS`、「加入该变量后重启网关」、「_科研项目」 |
| 该分支在真实浏览器里可达 | dev server + 无头 dump-dom 确认两张卡片渲染（含围笼外那张及其指引） |

⚠️ **诚实边界**：无头 `dump-dom` **不能点击**，故「真实点击解析 → 看到 409」这一步未在浏览器里跑过；
它由「网关返回真实 409（curl 实测）」+「视图渲染该文案（用真实文案的单测）」两段拼合而成。

---

## 四、未决与下一步

| # | 事项 | 状态 |
|---|---|---|
| 1 | **S2 ③ 对话分析**（SSE 流 + 工具轨迹） | **下一步**；前置 `api.ts` 的 Zod 边界已就位 |
| 2 | S3 ⑥ 校验层（B 组组件 `ContractBadge`/`ContractCard`/`ToolCallRow`） | 随 S3 |
| 3 | `Toast` §4.6.4 | 随 S2（操作反馈应从面板内改为 Toast） |
| 4 | 算例详情页 / `case.detail.tabs` 槽位 / `Identifier` 实战接入 | 算例详情在方案里属 ④ 实验矩阵前置，暂不展开 |
| 5 | 本轮**未提交** | `frontend/` 全部 + `tools/build_design_tokens.py` + 三份 journal + `_index.md` |

**DoD 三连（`frontend/` 下）**：`npm run build && npm run guard && npx vitest run` —— 三段全绿。
