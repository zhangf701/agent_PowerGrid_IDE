# 2026-09-27 — ⑥ 校验层收尾：跨引擎一致性 · 能力矩阵 · IR 检查器 + N-1 violations 结构化

> 状态：✅ 已交付（前端 7 文件新增 + 10 文件修改；令牌真源 +2 条实测条目）
> 前置：`2026-09-26-f4-wiring.md`（F-4/F-5）。**React 迁移计划内的视图至此全部落地。**

## 交付概览

| 块 | 规范 | 数据源 | 形态 |
|---|---|---|---|
| N-1 violations 结构化 | §6.1（数值核对必须用表）· §7.2（阈值必须写出） | F-4 的 `result_excerpt`（复用，无新端点） | `ViolationTable`，挂在 `ToolCallRow` 下方 |
| 跨引擎一致性 | 方案 §5.2 · UI 规范 §6.3（前瞻规格） | **本会话工具轨迹**（`useSession().rows` 的结构化结果配对） | `CrossEnginePanel`，校验层标签 2 |
| 能力矩阵 | 方案 §5.3 | `GET /servers` + `GET /contracts/t0` + **v4 §5.3 文档知识** | `CapabilityMatrixPanel`，校验层标签 3 |
| IR 检查器 | 方案 §5.4 | `GET /cases` + `GET /cases/{id}/diagnostics` | `IrInspectorPanel`，校验层标签 4 |

校验层展开区从「只有契约卡片」改为**四标签**（契约 / 跨引擎一致性 / 能力矩阵 / IR 检查器）——
§4.7.1 要求的校验层详情四块至此**能力一个不丢**。

## 关键实现决定（按证据链）

### 1. F-5 延伸：`from_bus` / `to_bus` 入 `byOutput`（+2 条）
N-1 违规表要渲染支路两端母线。真实夹具（case39 N-1，2026-09-27 网关抓取）给出**决定性证据**：
`branch_1` 标签 `Line 1->39(ckt 1)`，`from_bus=1 / to_bus=39`，而 case39 仅 39 条母线
（0-based 最大只能是 38）⇒ **1-based**。已按项目规则写入 `design/tokens.json#byOutput`
（同工具同编号体系，与 `bus_number` 一致），并重新生成产物；guard 通过。
⚠️ 其余引擎/输出仍按「未实测 → unknown」处理，未批量臆测。

### 2. N-1 违规表：排序在数据层做死 + 截断必须可见
- `extractViolations()`（适配层）：排序 = 热越限按负载率降序 → 电压按 **|vm − vm_limit|** 降序
  （High/Low 同一把尺子）→ 孤岛/不收敛垫底。**渲染组件不自行排序**（单一职责，可单测）。
- 52 条全渲染会撑爆对话流 ⇒ 默认显示前 10 条，但**截断必须可见**（「共 52 条 · 显示前 10」）
  —— 静默截断 = 让读者以为看到的就是全部。
- 数值全走 `measure()`：负载率 `% (MVA 判据)`、`flow/limit MVA` 并排（§7.2）、电压 `pu` + 限值；
  越限用 `Quantity` 的 `alarm` 文字「超限」，不用纯色（P2）。

### 3. 跨引擎一致性：没有假数据源，配对在数据层且「算例不同永不配对」
- 网关没有「一致性端点」，一致性结论只能来自**真实跑过的调用** —— 面板从会话轨迹配对。
- 配对键 = `label + 单位 + 判据 + 算例标识`（算例标识从 args 白名单键提取：`file/path/case`）。
  **算例不同的两条永不配对** —— 错配的一致性结论比慢更危险（§11.7-③）。
- 参数里没有算例标识的组：`caseVerified=false` —— **Δ 照显，判定一栏是「无法判定」**
  （unknown 哲学：宁可未知，不可猜错），不是悄悄放行也不是悄悄不显示。
- 阈值**显式声明**：相对偏差 ≤ **1e-4**（依据：case118 实测 Δ=2.0e-06 pu，不应要求机器精度；
  工程上有意义的电压差异 ≥ 1e-3 pu —— 1e-4 介于两者之间）。阈值与 Δ 都按 §7.2 用 `e` 记法。
- `Measured` **原样传给渲染**（不复制重建）—— 杜绝绕过 `measure()` 品牌的旁路
  （首版曾用 `as` 强转重建展示对象，review 时自己否掉）。

### 4. 能力矩阵：动态列与静态列**来源分离且写明**
- 动态列 = 契约 1 / 契约 2 状态（`/contracts/t0` 真实 findings，可下钻看 detail）；
- 静态能力列（潮流/OPF/N-1/…）= **v4 §5.3 文档知识**（2026-09-24 实测校正版），页面标注
  「不是运行时探测」—— 不许把文档知识冒充探测结果。
- findings 没有的 server（如 powerio）显示「**无记录**」，不显示成正常（空集 ≠ satisfied）。

### 5. IR 检查器：本步落地范围**如实写进界面**
- ✅ value_type / 诊断（按 severity 排序 error→warning→remark→note，code/target/建议可见）/
  counts 摘要（status 原文）/ `stale` 陈旧标记（网关现算的哈希比对）。
- ⏳ selection 树 / fidelity 徽章 / edits 时间线：网关无对应数据源（edits 需网关记录编辑操作），
  现在做就是对着不存在的数据定型 —— 面板底部注明「尚未实现（如实标注，不假装）」。

## 夹具（全部抓自运行中的网关，2026-09-27）
`contracts-t0.json`（38 findings，summary=degraded）· `servers.json`（9 id）·
`case-diagnostics.json`（case118，**零诊断**，status=ok）。
⚠️ 「带条目的诊断」没有真实样本 —— 渲染排序测试用**按 `powerio.diagnostic_record()` 源码
字段集构造**的合成对象，用例注释已注明；真实空列表夹具负责证明 schema 与真实网关兼容。

## 验证
- 前端 vitest **126 passed / 7 文件**（95 → +31）；build ✅ · guard ✅（88 令牌）。
- api schema 三条新链路全部用**真实夹具**验证；`extractViolations` 钉住 52 条数、Top-1
  branch_26=161.84% (MVA 判据)、from/to_bus=(23,24,1-based)。
- ⚠️ **诚实边界**：① `chat.test` 的 seq 去重用例在两次全量跑中出现过**超时假失败**
  （与沙箱 EPERM unhandled error 同现；隔离跑与两次干净全量跑均稳定通过）—— 若复现优先查
  环境而非代码；② 无头 Chrome 本会话未验证，新面板走 vitest + 真实夹具渲染（同 S2 的做法），
  真机浏览仍待张老师按手测清单过一遍；③ 跨引擎一致性面板暂无真实多引擎同跑样本，
  配对逻辑由合成 `measure()` 数据单测覆盖。

## 下一步
- React 迁移计划内视图已全部落地 ⇒ 可请张老师**真机手测**（更新《React版测试命令.md》）。
- ResultTable（模块 `result_tables` 的界面落点）与 N-1 `violations[]` 的**完整**表格化
  （下载/导出）尚未做 —— 本次是严重度前 N 条的对话内呈现。
- opendss 修复、选题新颖性专查仍冻结/挂起（不受本步影响）。
