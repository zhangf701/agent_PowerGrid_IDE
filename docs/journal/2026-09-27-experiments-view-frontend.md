# 2026-09-27 — ④ 实验矩阵前端视图（ExperimentGrid + ExperimentsView）

> 状态：✅ 已交付。前端 vitest **172 passed / 8 文件**（+28）· `tsc --noEmit` 干净 ·
> `vite build` 通过 · tokens 护栏通过 · 真机 Chrome 目视 6 张截图。
> 前置：[handoff_2026-09-27_p2-experiments-complete.md](handoff_2026-09-27_p2-experiments-complete.md)（网关侧 ①b/①c）·
> UI 规范 §4.7.5 · 重定位提案 §4.4

## 一、为什么现在才做界面

①c 之前**不该**动界面（会对着不存在的端点定型）。①b/①c 交付后端点齐了：
`POST/GET /experiments` · `GET /experiments/{id}` · `POST /experiments/{id}/run` ·
`GET /experiments/{id}/results` · `GET /experiments/{id}/export?format=csv|md`。

## 二、交付内容

| 文件 | 内容 |
|---|---|
| `src/api.ts` | 新增 experiments 一组 zod schema（列表 / 详情 / 建实验 / 执行 / 结果表） |
| `src/components/ExperimentGrid.tsx`（新） | 网格组件 —— §4.7.5 三条约束的落点 |
| `src/views/ExperimentsView.tsx`（新） | ④ 视图：列实验 · 建实验 · 串行执行 · 结果表 · 导出 |
| `src/App.tsx` | 导航加「实验矩阵」标签 + `#experiments` / `#experiments/<eid>` 深链 |
| `src/gatewayPaths.ts` | **补上 `experiments`** —— 漏了的话 dev 下会回落 index.html（`/servers` 踩过同一个坑） |
| `src/__fixtures__/gateway/experiment*.json`（7 个新夹具） | 全部抓自**运行中的真实网关** |

## 三、§4.7.5 三条约束的落地（每条可指认）

1. **失败逐格可见**：`failed` 的格子**在行内**给出「失败于第 N 步 `server.tool`」+ 引擎错误原文；
   `remounted=true` 额外解释「server 进程此前已死，会话状态无法担保」。
   总计数只是补充。未映射的网关状态 → 原样显示 + `unknown` 签名（不静默当成功）。
2. **结果绑 `cache_key`**：每行显示 `cache_key`；`never_run` 说明"当前 key 无存档结果"；
   `orphaned` 单独标注**来自旧条件**，不与当前结果并列。
3. **串行优先**：无并行度/并发数控件，并写明「串行执行（不并发）」「一格一个会话」。

## 四、真实数据 e2e（Chrome headless 驱动，非静态截图）

`.superpowers/sdd/m40-experiments-ui-shots.js` 驱动**系统 Chrome**（`channel: "chrome"`，不下载浏览器）
走一遍 6 个场景，产物 `work/exp-ui-shots/`：

| 截图 | 断言到的真实数据 |
|---|---|
| `01-definition-grid.png` | 定义层网格（2 格，`cache_key` 已绑定） |
| `02-after-run.png` | `已串行执行 2 格: 成功 2 · 失败 0` |
| `03-results.png` | 指标 `metric.results.n_contingencies=46`、`n_converged=45`、「共 12 项指标，见结果表」 |
| `04-failed-cell.png` | `已串行执行 1 格: 成功 0 · 失败 1` + **失败于第 2 步 `surge.no_such_tool`** + 错误原文 |
| `05-stale.png` | `? 未跑 1` + **▲ 1 条陈旧结果** + 「当前 cache_key 没有存档结果」 |
| `06-dark-experiments.png` | 深色主题下的同一视图 |

★ **主题用 PIL 直方图核实，不凭目测**（项目规矩）：深色截图最大面积是 `(14,17,22)` 56.9% /
`(26,31,40)` 23.3%（深色表面），文字 `(237,241,246)`（亮色）；浅色反之。
⇒ **无主题泄漏**。⚠️ 目视时曾误以为"深色下半部偏亮"，采样后证明是看图缩放的错觉
—— 正是"不凭目测"这条规矩的价值。

## 五、开发过程中发现并修掉的问题（都是真的）

1. **`toGridCells` 会静默丢弃数据**：原先只按**当前定义**的 `cache_key` 取执行记录；
   定义变过之后取回的执行记录会**被丢掉**（用户刚跑完却什么都看不到）。
   → 改为取**并集**，不属于当前定义的格子标 `definitionChanged` 并由网格显式标出。
2. **React 重复 key**：`key={c.index}` 与 `key={c.cacheKey}` **都会重复** ——
   前者在"追加行"上撞，后者在**未引用因子的重复格**上撞（正是网关告警的那种情形）。
   → 改用 `行位置 + cacheKey` 组合，并补一条回归测试（重复 `cache_key` 的两行都要渲染）。
3. **dev 代理漏 `experiments`**：`gatewayPaths.ts` 少一项 → dev 下 `/experiments` 回落 index.html
   → 前端报「响应不是 JSON」。已补，并**同步加进 `api.test.ts` 的守卫清单**（否则将来被删也没人发现）。
4. **网关一处过时文案**：`/experiments` 的 `notes` 还写着「尚不执行；执行是 P2-①b」
   —— 夹具抓下来才看见。已改为指向 `/run` 与 `/results`。

## 六、验证

- 前端 vitest **172 passed / 8 文件**（新增 `ExperimentsView.test.tsx` 28 条）。
  ★ 夹具 ↔ schema 双向断言：7 个真实响应必须能通过 zod（防"schema 写的是想象中的字段"）。
- `tsc --noEmit` 干净 · `vite build` 通过（302.59 kB / gzip 94.32 kB）· `npm run guard` 通过（88 令牌）。
- 真机 Chrome 6 场景截图（见 §四）。

⚠️ **全量跑时遇到过间歇性失败**：`vitest` 报
`EPERM: operation not permitted, open '...\Temp\...\web\<hash>'`
（**沙箱的 `node-brokered-fs-shim.cjs` 拦下了 vite-node 的模块缓存写**），
表现为某个测试文件被中途中断、`chat.test` 的一条用例假失败。
**已用实验排除是本步引入**：① 排除本步新增的测试文件后仍复现；② 该文件隔离跑 32/32 稳过；
③ 换 `TEMP` 到项目内仍复现（与目录无关）。重跑即得 **8 文件 / 172 passed 全绿**。
⇒ 与本步改动无关，是**沙箱环境限制**。

## 七、遗留

1. **越限明细级的 `result_tables` 透视**（模块列定义 / G-2 pivot）—— 属 **P3**，未做。
2. **§11.2 并发隔离** —— 0 实现；**并发化前必须完成**（串行版不需要）。
3. 深链 `#experiments/<eid>` 只在**全新加载**时生效（hash 变化不重挂载）——
   与既有 `#skills` 深链同一行为，未改。
4. `index.html` 未配 favicon → dev 下 `/favicon.ico` 404（**既有**，非本步引入）。
