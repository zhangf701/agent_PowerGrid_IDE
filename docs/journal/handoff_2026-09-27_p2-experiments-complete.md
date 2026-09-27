# 交接：P2 实验矩阵功能闭环（定义 → 执行 → 结果表 → 导出）（2026-09-27）

> 接手人请先读 `docs/journal/_index.md` 回溯，再读本文。
> 一句话状态：**实验矩阵的网关侧已全部交付**（①a 定义层 + ①b 步骤序列契约与串行执行器 + ①c 结果表与导出），
> 网关 **613 passed**、探针 **m38 11/11 · m39 11/11 全红**、真实网关 e2e 全过。
> **前端 `ExperimentsView` 未开始**；§11.2 并发隔离仍 0 实现（串行版不需要它）。

---

## 一、今天发生的事（按序）

1. **读交接日志 + 核实 ①b 硬前置**（目标工具真实 `input_schema`）—— **核出与日志不符的事实**（见 §二）。
2. **张老师裁决**：契约扩展为 `steps[]`，**不保留旧 `step` 单值形式**；**全部步骤须同一 server**。
3. **①b-1 契约扩展**：`Step` 数据类、`Experiment.steps`、`Cell.steps`、`cache_key` 改由 steps 序列构成。
4. **①b-2 串行执行器**：`POST /experiments/{eid}/run`（一格一会话 / 失败停本格 / remounted 判失败 / 无池显式 503）。
5. **①b-3 真实网关 e2e**：case39 真实跑通 surge N-1（46 场景 / 23 越限 / 52 条），3.1s。
6. **①c 结果表与导出**：`/results`（格级对比表）+ `/export?format=csv|md`；e2e 抓到并修掉一个真实缺陷（列 key 撞名）。
7. 变异探针 m38 扩到 11 条、新建 m39（11 条）；同步重定位提案 §4.4/§六 与 journal。

## 二、★ 关键事实（接手必读）

### 1. 引擎是**有状态**的 —— 这是 `steps[]` 存在的唯一理由

```
surge.run_n1_branch_contingency(monitored_branches)   # 只有这一个参数，无 file_path
```
它跑的是 server 进程内**已加载**的网络（函数体首行 `_require_network()`）。
⇒ 一次 N-1 分析 = `load_network(case)` → `run_n1_branch_contingency()` **两步**，
且两步必须落在**同一 server 会话**（`proxy.call_tool` 仅传 `sid + pool` 时复用进程）。
`pandapower.run_power_flow` 同理。**`powerio.*` 是无状态反例**（收 `path`，单调用即成）。

⚠️ 旧交接日志 §六 的 e2e 示例模板 `args_template:{"file_path","branch"}` 对
`run_n1_branch_contingency` **是错的**（会被契约 3 fail-closed 拒发）。**不要再照抄。**

### 2. 三条执行期硬 fail-closed（各有变异探针钉住）

| # | 规则 | 不这么做会怎样 |
|---|---|---|
| 1 | **一格一个会话** | 跨格复用 → 某格 `load_network` 失败后，下一格跑在**上一格残留的网络**上（结果张冠李戴） |
| 2 | **`remounted=True` 判该格失败** | 重连意味着 server 进程死过、会话状态已丢 —— 会让「可能是空网络跑出来的结果」冒充成功 |
| 3 | **多步实验无会话池 → 503** | 静默降级成「每步各起一个进程」→ 产出「跑成功但没加载网络」的**假结果** |

### 3. 结果按 `cache_key` 对齐（不是格子序号）

- 存：`~/.powermcp_gateway/experiments/<eid>/results.json`，键 = `cache_key`。
- 读：`/results` 把**当前**格子与存档按 key 对齐。算例/模板一改 → 该格 `never_run`、
  旧记录进 `orphaned`（**实测**：改前 `{'ok':1} orphaned=0` → 改后 `{'never_run':1} orphaned=1`）。
- 指标键统一带 `metric.` 前缀 —— 否则引擎内层 JSON 的 `status` 会与保留列撞名（**实测踩过**）。

### 4. 未引用因子会告警

`factors=[lv=1.0,1.1]` 而模板里没写 `{lv}` ⇒ 两格 `args` 相同 ⇒ `cache_key` 逐位相同
⇒「2 格都成功」看着正常，实际只跑了一种条件。登记响应里给 `unreferenced_factors` 告警。

### 5. 判据现状（方案 §12）

`#1 ✅ · #4 ✅ · #5 ✅ · #7 ✅`；**`#2 能组织研究` · `#3 能批量跑` 的网关侧已具备**
（定义 + 执行 + 结果表 + 导出），**前端视图未做**，故判据验收仍需界面落地；`#6` 卡 P3。

## 三、未决事项（按优先级）

| # | 事项 | 状态 | 入口 |
|---|---|---|---|
| 1 | **④ 实验矩阵前端视图** `ExperimentsView` + `ExperimentGrid` | 未开始；端点已就绪 | UI 规范 §4.7.5 三条约束 |
| 2 | **§11.2 并发隔离**五项措施 | 0 实现；**并发化前必须完成**（串行版不需要） | 方案 §11.2 |
| 3 | 越限明细级 `result_tables` 透视（模块列定义 / G-2 pivot） | 未做，属 **P3** 面 | 模块清单 `result_tables` |
| 4 | 挂起（不受本步影响） | opendss 挂载失败 · G-11 契约 1 静态判定 unknown · surge distributed-slack（未立项） | 各自 journal |

## 四、环境踩坑档案

- ★ **`create_app()` 会把全局 `_POOL` 重置为 `None`**：测试里若某个 fixture 走 HTTP（内部调
  `create_app`），会把 `pool_app` 刚装好的会话池**悄悄抹掉** → 多步实验测试全部假失败。
  ⇒ 夹具应**直接经 `CaseStore` 登记算例**，与 `_POOL` 解耦（本步已这么改）。
- ★ **探针不红先怀疑选择器**：本步 M3 又踩了一次（测试改名、`-k` 仍旧名 → `575 deselected`）。
  两个探针现已内建识别：**选择器一个测试都没选中 → 报「探针配置错误」**，不报「假护栏」。
- **curl 必须加 `--noproxy '*'`**；**pytest `--basetemp` 必须指向不存在的新目录**。
- **多步实验的 e2e 必须开 `POWERMCP_SESSION_POOL=1`**（run_gateway 脚本已默认设）。
- ⚠️ **Python 字符串里别写 ASCII 直引号**（中文引语用「」）—— 本步又踩一次，SyntaxError。
- 端口：8765 常驻（run_gateway），本会话 e2e 用 **8766**（有池）/ **8767**（无池，正反对照）。

## 五、仓库状态（截至本 handoff）

- 分支 `master`；工作区**有未提交改动**（本次 5 个文件 + journal/handoff）。
- 改动：`gateway/src/powermcp_gateway/experiments.py` · `api.py` · `proxy.py`（新增公开
  `result_excerpt`）· `tests/test_experiments.py` · `tests/test_api_experiments.py`。
- **按惯例不入库**：`.superpowers/sdd/m38-*.py` · `m39-*.py`（探针脚本，sdd 目录已 ignore）。
- 冻结/挂起分支未动：`PowerMCP/`（`fix/pandapower-deepcopy`）· `PowerSkills/`
  （`fix/pypsa-pandapower-api-drift`，用户指令冻结）。

## 六、快速验证命令（接手自检）

```bash
# 1) 网关全量（基线应为 613 passed）
cd gateway && ../PowerMCP/.venv/Scripts/python.exe -m pytest -q \
  --basetemp=../work/pt-<新目录名>

# 2) 两个变异探针（各应全红）
../PowerMCP/.venv/Scripts/python.exe .superpowers/sdd/m38-experiments-mutation.py
../PowerMCP/.venv/Scripts/python.exe .superpowers/sdd/m39-experiments-execution-mutation.py

# 3) 真实网关 e2e（8766；多步**必须**开会话池）
cd gateway
export POWERIO_MCP_ALLOWED_ROOTS="D:/coding/powerMcp_Pskills;C:/Users/Z/.powermcp"
export POWERMCP_SESSION_POOL=1
export POWERMCP_GATEWAY_CASES_ROOT="D:/coding/powerMcp_Pskills/work/e2e/cases"
export POWERMCP_GATEWAY_EXPERIMENTS_ROOT="D:/coding/powerMcp_Pskills/work/e2e/exp"
../PowerMCP/.venv/Scripts/python.exe -m uvicorn powermcp_gateway.api:create_app \
  --factory --host 127.0.0.1 --port 8766     # ← 用后台任务方式起，不要 `&`
# 登记 → 建两步实验 → run → results → export
curl -s --noproxy '*' -X POST http://127.0.0.1:8766/cases -H "Content-Type: application/json" \
  -d '{"path":"D:/coding/powerMcp_Pskills/examples/data/case39.m","label":"IEEE39"}'
curl -s --noproxy '*' -X POST http://127.0.0.1:8766/experiments -H "Content-Type: application/json" \
  -d '{"case_ids":["<cid>"],"steps":[
        {"server":"surge","tool":"load_network","args_template":{"file_path":"{case_path}"}},
        {"server":"surge","tool":"run_n1_branch_contingency"}]}'
curl -s --noproxy '*' -X POST http://127.0.0.1:8766/experiments/<eid>/run
curl -s --noproxy '*' http://127.0.0.1:8766/experiments/<eid>/results
curl -s --noproxy '*' "http://127.0.0.1:8766/experiments/<eid>/export?format=csv"
# 预期：201 · run 两步全 ok（case39 真实为 46 场景 / 23 越限 / 52 条）
```

## 七、下游依赖提示

- **前端尚未消费 `/experiments`**：无 `ExperimentsView` / `ExperimentGrid`。UI 规范 §4.7.5
  已固定三条约束（进度可观测且失败逐格可见 / 结果绑 `cache_key` / 串行优先）——
  现在端点齐了，可以动界面了。
- **`/results` 是格级对比表**，不是越限明细表。越限明细（`result_tables` 的列定义 / G-2 pivot）
  属 P3，别以为 `/results` 里漏了。
- **多步实验对会话池是硬依赖**：部署时若忘了 `POWERMCP_SESSION_POOL=1`，
  `/run` 会明确 503 而不是静默出错 —— 看到 503 先查这个变量。
