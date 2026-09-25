# PowerMCP 前端模块化架构

> **性质**：配套设计文档。回答「如何让工作台按需装配 UI 组件、方便后续对接任意选题方向」。
> 配套对象：[前端方案重定位提案](PowerMCP_前端方案重定位提案.md)（信息架构）· [UI 设计规范](PowerMCP_UI设计规范.md)（视觉与组件）
>
> | 项 | 值 |
> |---|---|
> | 日期 | 2026-09-25 |
> | 触发 | 张老师：「能否做成模块化的设计，想利用这个项目做任意一个具体方向的选题研究，可以按需求加入 UI 组件，方便后续对接选题」 |
> | 前提 | 前端已与论文选题解绑，定位为通用研究工作台 |
> | 状态 | **设计提案**（本文所有设计判断为推断，非实测） |

---

## 一、设计目标与一句话方案

**目标**：内核只做与选题无关的事；一个具体选题 = 一个可插拔模块，**按需**贡献 UI 组件、数据模型与能力约束。

**一句话方案**：

> **内核（Kernel）稳定，选题即模块（Module）。** 模块用**声明式 manifest** 装配能力与数据；
> 只有在声明不够用时，才写 UI 组件 —— 且**绝大多数选题不需要写组件**。

---

## 二、★ 核心机制：三层成熟度（可降级）

这是「按需加入」能够成立的关键。模块**不必一步到位**，可以从零 UI 开始，需要时才升级。

| 层 | 模块需要提供 | 选题能否立刻开工 | 成本 | 预计占比 |
|---|---|---|---|---|
| **L0 · 声明式** | 仅 `module.yaml` | ✅ **立即可用** | 极低（写 YAML） | **多数选题** |
| **L1 · 数据式** | + 实体 / 结果表 schema | ✅ 内核**自动渲染**成表与图 | 低（写 JSON Schema） | 部分选题 |
| **L2 · 组件式** | + React 组件 | ✅ | 高（写代码） | 少数选题 |

**L0 的实际含义**：一个选题只要声明「我用 surge 的这 12 个工具、关心这 2 个技能、提示词是这样、报告模板是那样」，
就能在内核里跑起来 —— **一行 UI 代码都不用写**。这直接回答了「方便后续对接选题」。

---

## 三、内核与模块的边界

### 3.1 内核（Kernel）—— 与选题无关

内核承载重定位提案 §四 的 6 类能力，**不得包含任何领域知识**：

| 内核模块 | 职责 | 对应视图 |
|---|---|---|
| `env` | server / 引擎 / 求解器 / 依赖 / 路径围笼 | ① 环境就绪 |
| `cases` | 算例登记 · 解析 · 诊断 · 版本 | ② 算例库 |
| `chat` | 会话 · 工具轨迹 · 结果呈现 | ③ 对话分析 |
| `experiments` | 参数网格 · 队列 · 结果表 · 导出 | ④ 实验矩阵 |
| `skills` | 技能索引 · Escalation triggers | ⑤ 技能手册 |
| `verification` | 8 类契约 · 跨引擎一致性 · 能力矩阵 | ⑥ 校验层 |

### 3.2 模块（Module）—— 一个选题

模块**只能**通过内核暴露的接口做事（§六）。硬约束：

- ❌ 不得直接访问 `PowerMCP/`（*zero source mutation* 的延伸）
- ❌ 不得绕过网关直连 MCP server
- ❌ 不得写 `~/.powermcp/`（那是上游的目录）
- ❌ 不得 import 内核内部模块（只能走 §六 的公开接口）

---

## 四、四类扩展点

### ① 装配扩展 —— 声明式，零代码

在 `module.yaml` 里声明，内核据此**收窄或注入**能力：

| 字段 | 作用 | 示例 |
|---|---|---|
| `servers` / `tools` | 本选题的工具白名单 | 只用 surge 的 N-1 / PTDF / LODF 相关工具 |
| `skills` | 本选题关心的技能子集 | `[contingency-mitigation, thermal-overload-mitigation]` |
| `solvers` | 允许的求解器 | `[HiGHS]`（排除 Gurobi） |
| `prompts` | 选题专属提示词 / 工作流模板 | 13 步流程的领域变体 |
| `checks` | 选题额外的**领域**自检规则 | 「Δ 值必须显示」「单位必须标注」 |
| `exports` | 选题的报告模板 | Markdown 骨架 + 数据绑定 |
| `charts` | 图表预设 | 排序条形图 / 热力图 |

### ② 数据扩展 —— L1，内核自动渲染

| 字段 | 作用 |
|---|---|
| `entities` | 领域实体（如 `contingency_set` / `mitigation_plan` / `experiment_factor`） |
| `result_tables` | 结果表列定义 → 内核**自动**渲染为表 + 导出 CSV |
| `metrics` | 领域指标（如「关键故障数」「最大负载率」） |

> **设计判断**：把「表」做成数据驱动而非组件驱动。研究结果 90% 是表格与数值，
> 用 schema 描述列即可自动渲染，**这是让 L1 覆盖大部分选题的原因**。

### ③ 视图扩展 —— L2，写组件

| 扩展点 | 位置 | 典型用途 |
|---|---|---|
| `nav.extra` | 主导航 | 新增一个**顶级视图** |
| `case.detail.tabs` | 算例详情页 | 领域算例视图（如拓扑图、故障集编辑器） |
| `chat.result.after` | 对话结果之后 | 领域结果卡片（如 N-1 排序表） |
| `experiment.result.columns` | 实验结果表 | 领域列 |
| `verification.extra` | 校验层 | 领域自检面板 |

> **槽位（slot）设计原则**：槽位是**内核预留的稳定锚点**，数量少而稳定。
> 新增槽位需要改内核 → 故槽位清单应**先由 2–3 个真实模块验证后再冻结**（见 §八-1）。

### ④ 交付扩展

| 字段 | 作用 |
|---|---|
| `exports` | 报告模板（按用户级规则：PDF 走 HTML + Chrome headless，**禁用 pandoc**） |
| `datasets` | 数据集导出（面向科研 8 的机器学习标注数据集） |

## 四之二、★ 2026-09-25 落地补记（G-1 / G-2 / G-4 / G-5，张老师四项裁决）

两个真实模块验证暴露的 10 条缺口中，4 条设计级缺口已裁决并落地（余见 `modules/README.md` §四）：

| # | 裁决 | 落地 |
|---|---|---|
| G-1 | 加「默认算例」字段 | 清单新增 `sample_cases`（指向算例库 id 或路径；运行时数据，**装配期不做存在性校验**） |
| G-2 | 加「动态列」字段 | `result_tables[].columns_source: <展开维度列名>`（如 `engine` → 每引擎一列）；清单只声明意图，**pivot 渲染归内核**（实现归 P1） |
| G-4 | prompts / checks 接线做**最小闭环** | ① `/chat` 每轮把**启用模块**的 prompts 并入 system 消息（全禁用 → 不注入，自证条件不破坏；总字符上限 8000 防撑爆上下文）；② 新增 `POST /checks/run` 执行引擎 |
| G-5 | 冻结 checks 契约第一版 | 见下 |

### G-5 契约第一版（全文见 `gateway/src/powermcp_gateway/checks.py` 模块 docstring）

- check 文件导出 `check(ctx)` + 模块级 `RULE_ID`（非空 str）+ `SEVERITY`（info/warning/error）。
- `ctx`：`rows`（绑定结果表的数据行）、`result_table`、`module_id`、`case`/`case_id`（可选，调用方自带）。
  **有什么给什么，不假装拿得到引擎状态**。
- 返回 `list[str]`（severity 用模块默认）或 `list[dict]`（`{message, severity?}`）；**空列表 = 通过**。
- 清单绑定：`checks[].result_table: <本模块的 result_table id>`（引用未声明表 → **装配失败**）。
  ★ **绑定键不叫提案里的 `on`** —— YAML 1.1 会把裸键 `on` 解析成布尔值 `True`
  （本仓库在 `id: on` 上踩过并写进了诊断信息），`on: rt1` 实际是 `{True: 'rt1'}`，绑定会**静默失效**。
- **未绑定的 check 被跳过并如实上报**（`skipped`），**绝不拿空行跑出虚假的"通过"**。
- 单个 check 崩溃 → 记一条 `severity=error` 的 Finding，**不中断**同模块其它 check。
- `ctx` 按鸭子类型使用：check 文件**不 import 内核内部模块**（硬约束 §六）。

验证：**487 passed**（447 → 487，+40）；变异探针 3/3 全红（`.superpowers/sdd/m22-g45-mutation.py`）；
真实模块端到端实测 `.superpowers/sdd/m21-checks-e2e.py`（脏数据报 4 条 / 干净数据 0 条且非跳过）。

---

## 五、模块清单格式（`module.yaml`）

```yaml
id: n1-ranking
name: N-1 关键故障排序与可复现研究
version: 0.1.0
kind: research            # research | engineering
maturity: L1              # L0 | L1 | L2  —— 声明当前成熟度，内核据此决定渲染方式

requires:
  core: ">=0.1"
  servers: [surge]
  solvers: [HiGHS]

tools:                    # 装配扩展：工具白名单
  - surge.run_n1_branch_contingency
  - surge.compute_ptdf
  - surge.compute_lodf

skills:                   # 技能子集
  - contingency-mitigation
  - thermal-overload-mitigation

entities:                 # 数据扩展（L1）
  - id: contingency_set
    schema: ./schema/contingency_set.json
  - id: mitigation_plan
    schema: ./schema/mitigation_plan.json

result_tables:            # 数据扩展（L1）—— 自动渲染 + 自动导出 CSV
  - id: n1_results
    columns: ./schema/n1_columns.json
    metrics: [binding_count, max_loading_percent, top1_branch]

prompts:                  # 装配扩展
  - id: n1-scan
    file: ./prompts/n1_scan.md

checks:                   # 领域自检规则
  - id: delta-must-be-shown
    file: ./checks/delta_shown.py

exports:                  # 交付扩展
  - id: n1-report
    template: ./templates/n1_report.md

slots:                    # 视图扩展（L2，本模块未使用）
  []
```

**目录结构**：

```
modules/n1-ranking/
├── module.yaml
├── prompts/n1_scan.md
├── schema/contingency_set.json
├── schema/n1_columns.json
├── checks/delta_shown.py
├── templates/n1_report.md
└── ui/                      # 可选，仅 L2 使用
```

---

## 六、内核公开接口（模块的唯一入口）

| 接口 | 作用 |
|---|---|
| `kernel.tools.call(server, tool, args)` | 经网关调用（含契约校验与审计） |
| `kernel.cases.get(id)` / `.parse()` / `.diagnostics()` | 算例访问 |
| `kernel.events.subscribe(sid)` | 事件流（含 `contract_violation` / `contract_unknown`） |
| `kernel.results.write(table_id, rows)` | 写结果表 |
| `kernel.export.render(template, data)` | 渲染导出 |
| `kernel.checks.register(rule)` | 注册领域自检 |

> **约束**：接口是**版本化**的（`requires.core`）。内核升级须保持向后兼容，破坏性变更必须升主版本。

---

## 七、装配与冲突规则

| 项 | 规则 |
|---|---|
| 扫描 | 内核启动时扫描 `modules/*/module.yaml` |
| 启用 | `enabled: true` 的模块被装配；可**单独禁用**而内核仍可用 |
| 工具白名单 | 多模块**取并集** |
| 技能子集 | 多模块**取并集** |
| 实体 / 结果表 **同名** | ❌ **禁止** —— 启动时报错并拒绝装配（不静默覆盖） |
| 槽位 | 多模块可注入同一槽位，按 `order` 排序 |
| 模块失败 | **fail-loud**：装配失败的模块被标记不可用并在环境视图显示，**不影响内核与其他模块** |

> **「可单独禁用而内核仍可用」是本架构的自证条件** —— 若禁用全部模块后内核不可用，说明内核被领域知识污染了。

---

## 八、设计风险（必须先讲清）

| # | 风险 | 缓解 |
|---|---|---|
| 1 | ★ **过度抽象** —— 只有 2–3 个模块时，扩展点可能猜错，做出无用的抽象层 | **先做 2 个真实模块**（N-1 排序 + 跨引擎一致性）验证扩展点，**再冻结**接口与槽位清单 |
| 2 | **L2 组件与内核隐性耦合** —— 组件偷偷依赖内核内部状态，内核一改就崩 | 组件只经 props + `kernel.*` 拿数据；加一条构建期检查禁止直接 import 内核内部路径 |
| 3 | **模块 checks 与契约层职责重叠** | 明确分工：**契约层管「接口可靠性」**（8 类）· **模块 checks 管「领域正确性」**（Δ 必须显示、单位必须标注、排序必须可复现） |
| 4 | **模块生态维护成本** | 只维护**在用**的模块；废弃模块归档而非删除 |
| 5 | **L0 表达力不足** —— 某选题在 L0 下装不下，被迫跳 L2 | 这是**预期行为**（L0 覆盖多数、非全部）；跳级本身是有效信号，说明该选题确有特殊需求 |

---

## 九、一个完整示例：把「N-1 关键故障排序」做成模块

取材于 `能力与场景总结` 科研场景 1（**已有实测素材**：`examples/01`，IEEE 39，
46 场景 / 23 越限 / 52 条越限，Top-1 `branch_26` = 161.84%（958.49 MW））。

| 模块贡献 | 内容 | 层级 |
|---|---|---|
| 工具白名单 | surge 的 N-1 / PTDF / LODF 相关工具 | L0 |
| 技能子集 | `contingency-mitigation` · `thermal-overload-mitigation` | L0 |
| 提示词 | `n1_scan.md` —— 「跑 N-1 扫描并按负载率排序，输出 Top-N 与越限明细」 | L0 |
| 结果表 | `n1_results`：场景 / 类型 / 越限元件 / 负载率 / 有功 | L1 |
| 领域指标 | `binding_count` · `max_loading_percent` · `top1_branch` | L1 |
| 领域自检 | 「Δ 值必须显示」「越限元件必须标注标识符约定（0-based / 1-based）」 | L0 |
| 报告模板 | `n1_report.md` | L0 |
| **自定义组件** | **无** | — |

> ✅ **本模块只需 L1** —— 零 UI 代码，选题即可开工。这正是「按需加入 UI 组件」的常态：
> **多数时候不需要加**。

**唯一需要 L2 的场景举例**：某选题要求**拓扑图上的故障高亮**（如把 `branch_26` 在单线图上标红）——
这时才写一个组件注入 `case.detail.tabs`。

---

## 十、脚手架：让新选题的启动成本接近零

```
create-module <id> --kind research
```

生成：

```
modules/<id>/
├── module.yaml          # 带注释的完整模板（默认 maturity: L0）
├── prompts/README.md    # 提示词占位
├── schema/README.md     # 实体与结果表占位
├── checks/README.md     # 领域自检占位
├── templates/README.md  # 报告模板占位
└── ui/                  # 空目录，L2 时才用
```

**默认生成 L0** —— 强制「先声明、后写码」的顺序，避免一上来就写组件。

---

## 十一、与重定位提案的关系

| 重定位提案 | 本文档 |
|---|---|
| §四 信息架构（5 视图 + 1 校验层） | 定义**内核的 6 个模块** |
| §六 网关缺口（新增端点） | 内核接口的实现层；模块**不新增**端点，只用内核接口 |
| §七 实施路线 | **新增 P1 前置**：模块架构与脚手架（否则后续每个选题都要改内核） |
| §九 待确认项 | 本文档 §八 的风险 1 给出了扩展点冻结的前置条件 |

**实施顺序建议**：

1. 内核 + 脚手架（P1）
2. **两个真实模块**验证扩展点（N-1 排序 · 跨引擎一致性）
3. 依据验证结果**冻结**槽位清单与内核接口版本
4. 再放开后续选题自由装配

> ✅ **2026-09-25 进度**：
> - **第 1 步（网关侧）已交付** —— `modules.py` + `GET /modules` + `scripts/create_module.py`；
>   **内核自证条件已可检验**（模块根不存在 / 为空 / 全失败 / 全禁用四种状态下内核端点全部正常）。
> - **第 2 步（两个真实模块）已交付** —— `modules/n1-ranking`（N-1 排序）与
>   `modules/cross-engine-consistency`（跨引擎一致性），**均停在 L1、零 UI 组件**。
>   **结论：L0/L1 装得下真实选题**（两个差异较大的选题都完整声明成功）。
>   ⚠️ **但逼出了 10 条扩展点缺口**，其中 4 条影响 P1 设计：
>   `prompts`/`checks`/`exports` **声明了却未接线** · `checks` 契约未定义且未绑定结果表 ·
>   `result_tables[].columns` 表达不了**动态列** · **无「默认算例」字段**。
>   → **第 3 步（冻结接口）暂缓**：G-4/G-5 一旦动手，`checks`/`prompts`/`exports`
>   的形状很可能要改。完整清单与实测复现见 [`modules/README.md`](../modules/README.md)。
> - ⏳ 第 3 步（冻结槽位清单与接口版本）与前端侧槽位注入待后续。

---

## 十二、本文档明确**未**做的事

- 未写任何代码，未新增任何实验或数据
- 未验证 `module.yaml` 的字段设计是否够用 —— **须由 §八-1 的两个真实模块实测**
- 未确定槽位清单的最终集合（刻意留待实测后冻结）
- 未设计模块的权限与沙箱边界（若未来模块来自第三方，需要额外机制）
- 未决定模块目录 `modules/` 是否纳入 git（与 `examples/` 同一类待决问题）
