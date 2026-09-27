# 2026-09-27 — P2-①b/①c 实验矩阵：执行器 · 结果表 · 导出（实验矩阵功能闭环）

> 状态：✅ 已交付。网关 **567 → 613 passed**（+46）；变异探针 m38 **11/11 红** · m39 **11/11 红**。
> 前置：[handoff_2026-09-27_p2-experiments-definition.md](handoff_2026-09-27_p2-experiments-definition.md)（①a 定义层）·
> 方案 v4 §4.4 · 重定位提案 §4.4/§六 · 判据 #2/#3
> **本步把实验矩阵从「定义」做到「能跑、能看、能导」** —— 判据 #2/#3 的网关侧由此具备。

## 一、★ 开工前的硬前置核实：核出了与交接日志不符的事实

交接日志 §七-1 要求「先核实目标工具真实 `input_schema`」。核实结果**推翻了它自己的 e2e 示例模板**：

`PowerMCP/surge/surge_mcp.py:554-557`
```python
run_n1_branch_contingency(monitored_branches: Optional[List[Tuple[int, int, str]]] = None)
```
**只有 `monitored_branches` 一个参数 —— 没有 `file_path`、没有 `branch`。**
函数体首行 `net = _require_network()` ⇒ 它跑的是 **server 进程内已加载**的网络。
`pandapower.run_power_flow(algorithm, ...)` 同理（也无 `file_path`）。

三条推论（决定了后面所有设计）：
1. 交接日志 §六 e2e 里的 `args_template:{"file_path","branch"}` 对该工具**是错的**，
   会被契约 3 fail-closed 拒发（未知参数）—— 正是日志自己警告的「对着想象的接口定型」。
2. **一次分析 = 两步**：`load_network(file_path)` → `run_n1_branch_contingency()`。
   模块自身也是这么写的（`modules/n1-ranking/prompts/n1_scan.md`：load → info → dcpf → n1）。
3. **两步必须落在同一 server 进程**：`proxy.py:367-373` 明确只有传 `sid + pool` 才复用进程
   （注释原文「有状态工作流（载入 → 分析）才成立」）。

而 ①a 的 `Experiment` 是**单值** `{server, tool, args_template}` —— 表达不了它。
⇒ 张老师裁决：**契约扩展为 `steps[]`，且不保留旧 `step` 单值形式**；**全部步骤须同一 server**。

> 对照：`powerio.*` 是**无状态**的（`parse(path,...)` / `summarize(...)` 收 path、单调用即成），
> 可作为「不需要会话池」的低风险落点 —— 但 N-1 核心场景绕不开序列。

## 二、①b 契约扩展（`experiments.py`）

| 项 | 变化 |
|---|---|
| 数据模型 | 新增 `Step(server, tool, args_template)`；`Experiment.steps: tuple[Step, ...]`；`Experiment.server` 降为**派生属性**（`steps[0].server`） |
| `Cell` | `args` → `steps: tuple[{"server","tool","args"}, ...]`（每步**各自渲染**） |
| `cache_key` | `H(算例 sha256 + steps 规范化序列 + core_version)` —— ★ **步骤顺序参与身份**（`[load,run]` ≠ `[run,load]`） |
| 校验 | `_parse_steps`：非空数组、逐项校验、**全部同 server**（跨 server → 400，带可执行说明） |
| `derive_experiment_id` | 由 `steps` 派生（去掉单值 server/tool） |
| 语义不变 | 仍是**显式声明**：不替引擎自动注入 `load_network` 之类的前置步 |

★ **未被引用的因子会告警**（真实 e2e 暴露）：`factors=[lv=1.0,1.1]` 而模板里没写 `{lv}`
⇒ 两格 `args` 相同 ⇒ **`cache_key` 逐位相同** —— 「2 格都成功」看着正常，
实际只有一种实验条件被跑过。⇒ 登记响应里显式给出 `unreferenced_factors` 告警。

## 三、①b 执行器（`POST /experiments/{id}/run`）

**串行**（方案 §4.4 裁决）。三条硬 fail-closed（各配一条变异探针）：

1. **一格一个会话**。会话是引擎状态的边界。若跨格复用，某格 `load_network` 失败后，
   下一格的 `run_*` 可能跑在**上一格残留的网络**上 —— 「跑成功、但结果是别家的」。
   代价是每格重新挂载 server（秒级），对批量实验可接受：**宁可慢，不可错**。
2. **`remounted=True` 一律判该格失败**。重连意味着该 server 进程此前已死，
   会话状态（如已加载的网络）无法担保 —— 不让「可能是空网络跑出来的结果」冒充成功。
3. **多步实验缺少会话池 → 显式 503**，绝不静默降级成「每步各起一个进程」
   （那会产出「跑成功但没加载网络」的假结果）。单步实验不要求会话池。

其它：某步失败 → 本格 `failed` 且后续步不跑（后续步依赖前序状态），但**不中断其他格**；
每步经 `proxy.call_tool`（契约 3 fail-closed / EVIDENCE / NDJSON 审计天然在环内）；
同一实验**不并发执行**（`_RUNNING` 进程内标记，409）——§11.2 未做时的最小防护。

结果按 **`cache_key`** 落盘（`~/.powermcp_gateway/experiments/<eid>/results.json`）。
★ 键是 `cache_key` 而非格子序号：算例/模板一改，同一序号**已经不是同一条件**了。

## 四、①c 结果表与导出

- `GET /experiments/{id}/results` —— **格级对比表**：行 = 格子，列 = 各格指标的并集（按名排序）。
- `GET /experiments/{id}/export?format=csv|md` —— CSV / Markdown。
  ⚠️ **PDF 不在网关做**：须走「单文件 HTML + Chrome headless」，本项目**禁用 pandoc**（属渲染层）。

★ **陈旧结果的可观测形态**（真实网关实测）：算例一改 → 该格算出新 `cache_key`
⇒ 该格显示 **`never_run`**，旧记录进入 **`orphaned`**。改前 `{'ok':1} orphaned=0`，
改后 `{'never_run':1} orphaned=1` —— 不冒充当前条件，也不丢弃。

★ **指标只取标量与列表长度**（点号路径，如 `metric.results.n_contingencies`、
`metric.results.violations.count`），**不发明派生量**（「最大负载率」是模块语义，内核不猜）。
摘要被截断时**宁可空**，不给半截指标。

⚠️ **越限明细级的 `result_tables` 透视（模块列定义 / G-2 pivot）属 P3 面**，本步未实现 ——
不给「看起来像有、实际没映射」的假表。

## 五、真实网关 e2e（端口 8766，`case39.m`，会话池开启）

| 步骤 | 结果 |
|---|---|
| `POST /cases` 登记 case39 | `cd4cf1328477`，`within_allowed_roots=true` |
| 建 2 步实验（load → n1） | 201，1 格，`file_path` 渲染为真实绝对路径 |
| `POST /run` | **3.1s**，2 步全 `ok`，`remounted=false` |
| 真实 N-1 结果 | **46 场景 / 23 有越限 / 52 条越限**；`n_converged=45`，`solve_time=0.0102s` |
| 两格实验（2 步 × 2 格） | 4.0s，`{'ok':2}`；池统计 `mounted=5 calls=8 remounts=0` |
| **无池网关（8767）跑多步** | **503** + 可执行修复提示（`POWERMCP_SESSION_POOL=1`）；一步都没发出去 |
| **无池网关跑单步** | **200** —— 正对照，证明没有过度限制 |
| `/results` | 列 16 个、**无重复 key**；`metric.results.n_contingencies=46` |
| `/export?format=csv` / `md` | 200，`text/csv` / `text/markdown`，含 `factor.lv` 列 |
| `/export?format=pdf` | **400**（可用格式提示） |

产物：`work/exp-e2e-20260927/`（01-register … 08-export.md）。

★ **e2e 抓到一个真实缺陷**：引擎内层 JSON 顶层就有 `status`（值 `"success"`），
与结果表**保留列 `status`（格子执行状态）撞名** —— 实测列定义里出现两个 `status`，
按 key 取值的消费者必然取错一个。修复：指标键统一加 `metric.` 命名空间（并配 C5 探针）。

## 六、验证

- 网关 pytest **567 → 613 passed**（+46：定义层 8 · 执行层 17 · 结果表/导出 21）。
- 变异探针 **m38 11/11 红**（定义层，新增 M8 跨 server / M9 步骤顺序入 key / M10 丢步）·
  **m39 11/11 红**（执行层 E1–E6 + 结果表 C1–C5）。
  ⚠️ **探针再次因「选择器指错」假红**：M3 的 `-k` 还是测试旧名（我把它改名了）→
  pytest 只输出 `575 deselected`。已给两个探针都加上「一个测试都没选中 → 报探针配置错误」的识别。
- 全量业务端点：**21 个路径**（不含 FastAPI 自带 `/docs` `/redoc` `/openapi.json` `/docs/oauth2-redirect`）。

## 七、遗留（不在本步范围）

1. **④ 实验矩阵前端视图**（`ExperimentsView` + `ExperimentGrid`）—— 未开始。
   端点已就绪，UI 规范 §4.7.5 的三条约束（进度可观测且失败逐格可见 / 结果绑 `cache_key` / 串行优先）可落地。
2. **§11.2 并发隔离**五项措施 —— 0 实现。**并发化前必须完成**；串行版不需要它。
3. 越限明细级 `result_tables` 透视（G-2 pivot）—— P3 面。
4. 挂起（不受本步影响）：opendss 挂载失败 · G-11 契约 1 静态判定 unknown ·
   surge distributed-slack（冻结文档 §4.4 候选契约，未立项）。
