# 交接：P2 进度盘点 + 实验矩阵定义层（P2-①a）落地（2026-09-27）

> 接手人请先读 `docs/journal/_index.md` 回溯，再读本文。
> 一句话状态：**P2 三缺二已定位（实验矩阵 / 并发隔离未做）；其中实验矩阵的**定义与登记层**已交付
> （`/experiments` 三端点 + 42 测试 + 8/8 探针 + 真实网关 e2e），提交 `ad6b50b`，工作区干净。
> **执行器（①b）尚未开工**，且开工前有一项必须先做的核实。**

---

## 一、今天发生的事（按序）

1. **进度盘点（只读，未改代码）**：读完方案 v4 §十/§4.4/§11.2/§12、重定位提案 §四/§六/§七、
   UI 规范 §4.7.5、模块化架构与接口冻结 v1，并**逐项核实代码现状**（不是照抄文档）。
2. **张老师裁决**：P2 剩余项先做 **① 网关 `/experiments` 端点**（四选一）。
3. **前置条件检查**：实测网关基线 **525 passed**（⚠️ 文档旧值 523，已过时）。
4. **交付 P2-①a**：新增 `experiments.py`（640 行）+ `api.py` 接线（+140）+ 2 个测试文件（+42 条）
   + 变异探针 `m38`（8/8 全红）+ 真实网关端到端（6 条路径）。
5. **提交 `ad6b50b`**，并同步更新《重定位提案》§六 端点表（文档不得与实现不一致）。

## 二、关键事实与裁决（接手必读）

### 1. P2 剩余两块 —— 均已用代码核实，非文档推断

| 项 | 核实方式 | 结论 |
|---|---|---|
| 校验层迁移 | journal 09-27 | ✅ 已交付 |
| **④ 实验矩阵** | `api.py` grep `/experiments` **0 命中**；`frontend/src/views/` 只有 4 视图 | ⏳ 定义层**已交付**，执行/结果/导出未做 |
| **§11.2 并发隔离** | gateway 源码 grep `portalocker/fcntl/runs_dir/staged_file_write/lease` **全 0 命中** | ⏳ 五项措施一项未做 |

⚠️ **并发隔离不阻塞串行版实验矩阵**：执行模型已裁决「先串行跑通，再评估并发」（方案 §4.4），
并发隔离只在**引入并发前**必须完成。

### 2. 三个设计决定（①b / ①c 必须延续，改了要回来改文档）

1. **一格 = 一次显式声明的工具调用**（`server`/`tool`/`args_template`），**因子只是标签维度**。
   ★ 刻意**不做**「负荷水平」这类语义因子 —— 那等于**替引擎声称一个未核实的能力**
   （需要某引擎真能按因子缩放负荷，本步未核实）。参数对不对由**契约 3 fail-closed** 在调用前兜住。
2. **`cache_key` 只含可确证的量**：`H(算例当前 sha256 + server + tool + 规范化 args + core_version)`。
   ⚠️ 方案原文还含**引擎版本 / IR 版本**，网关**无可靠来源**取得 ⇒ **不假装有**，缺的量不进 key，
   而在响应 `notes` 写明。宁可 key 保守失效，也不冒充可复现性。
3. **格子现算、不存快照**：每次 GET 按当前算例哈希与模板重算。
   副作用正是要的效果 —— **算例源文件一改，同一格算出新 key ⇒ 旧结果即为陈旧**。

### 3. 错误映射（用**类型**区分，不靠匹配错误文本）

400 定义非法 · **409 算例状态不允许** · 404 未知 id · 500 索引损坏 · 503 配置失败。

> 409 与 400 的分界：**算例未登记** = 请求体引用了不存在的东西（400，改请求）；
> **算例存在但不可读 / 不在围笼** = 环境状态不允许（409，改环境，与 `POST /cases/{id}/parse` 同口径）。
> 实现上分别用 `ExperimentError`（400）与 `ExperimentCaseStateError`（409）。

### 4. 判据现状（方案 §12）

`#1 ✅ · #4 ✅ · #5 ✅ · #7 ✅`；**`#2 能组织研究` · `#3 能批量跑` 卡在实验矩阵**；`#6` 卡 P3。
⇒ ①b（执行）+ ①c（结果表/导出）做完，#2/#3 才有望达标。

### 5. ★ 探针教训（最重要的一条方法论）

变异探针第一版 **M2 没变红** —— 不是实现没问题，是**我把 `-k` 选择器指错了测试**
（变异打的是「插值占位符」分支，选中的却是「整串占位符」那条测试）。拆成 M2a/M2b 后各自钉住。
⇒ **探针不红时，先怀疑"选择器指错 / 测试没覆盖"，再怀疑实现。**

## 三、未决事项（按优先级）

| # | 事项 | 状态 | 入口 |
|---|---|---|---|
| 1 | **核实目标工具真实 `input_schema`**（`surge.run_n1_branch_contingency` / `pandapower.run_power_flow` 等） | ⚠️ **①b 开工前的硬前置** —— 不核实就写执行器 = 对着想象的接口定型 | 真实拉起 server 取 inventory（`build_inventory`）或 `/contracts/t0` |
| 2 | **P2-①b 执行器** `POST /experiments/{id}/run` | 未开始；**串行**，逐格 `proxy.call_tool`，**进度可观测 + 失败逐格可见**（UI 规范 §4.7.5：不得只给总进度条） | journal 09-27 §七 |
| 3 | **P2-①c** `/experiments/{id}/results` + `/export` | 未开始；CSV / Markdown；**PDF 走 HTML+Chrome headless，禁用 pandoc** | 重定位提案 §六 |
| 4 | **④ 实验矩阵前端视图** | 未开始；`ExperimentsView` + `ExperimentGrid`（§4.7.5 三条约束：**进度可观测且失败逐格可见** / 结果绑 `cache_key` / **串行优先**） | UI 规范 §4.7.5 |
| 5 | **§11.2 并发隔离**五项措施 | 0 实现；**并发化前必须完成**（命名空间加 session 维度 / 租约锁 / 工作流级事务 / 引擎实例串行化 / 统一写入方式） | 方案 §11.2 |
| 6 | 挂起（不受 P2 影响） | opendss 挂载失败 · G-11 契约 1 静态判定 unknown · surge distributed-slack（冻结文档 §4.4 候选契约，**未立项**）· ResultTable 与 N-1 violations 完整表格化/导出（属 P3 面） | 各自 journal |

## 四、环境踩坑档案（本机迁移/重装时必读）

- ★ **后台网关进程会被回收**：用 `&` 起的 uvicorn 会随该次 shell 调用结束而终止（表现为 `HTTP=000`）。
  ⇒ 必须用后台任务方式启动（持久化），不要 `... &`。
- **curl 必须加 `--noproxy '*'`**（沙箱把 localhost 劫持成 502）。
- **pytest `--basetemp` 必须指向不存在的新目录**，否则 `rm_rf` 被护栏拦 → 假 errors。
- **测试里算例不在围笼会 409**：`POST /experiments` 的测试需 `monkeypatch.setenv(
  "POWERIO_MCP_ALLOWED_ROOTS", str(tmp_path))`；要覆盖 409 分支则**刻意不设**。
- **变异探针锚点必须唯一**：写探针前先 `count(anchor) == 1` 校验，否则静默打空。
- ⚠️ **Python 字符串里别写 ASCII 直引号**：我写中文文案时混入 `"…"`，直接 SyntaxError
  （字符串被截断）⇒ 中文引语一律用「」。
- 端口：8765 常驻（run_gateway），本会话 e2e 用 **8766**。

## 五、仓库状态（截至本 handoff）

- 分支 `master`；**HEAD = `ad6b50b`**（P2-①a），**工作区干净**，本地 master 未设 upstream。
- 本次提交 7 文件 / +1401 行：
  `gateway/src/powermcp_gateway/experiments.py`(新增 640) · `api.py`(+140) ·
  `tests/test_experiments.py`(新增) · `tests/test_api_experiments.py`(新增) ·
  `docs/journal/2026-09-27-p2-experiments-definition.md`(新增) · `docs/journal/_index.md` ·
  `docs/PowerMCP_前端方案重定位提案.md`（§六 端点表同步为"定义层已交付"）。
- **按惯例不入库**：`.superpowers/sdd/m38-experiments-mutation.py`（探针脚本，sdd 目录已 ignore）。
- 业务端点实测 **18 个路径**（新增 `/experiments`、`/experiments/{eid}`；不含 FastAPI 自带
  `/docs` `/redoc` `/openapi.json` `/docs/oauth2-redirect`）。
- 冻结/挂起分支未动：`PowerMCP/`（`fix/pandapower-deepcopy`）· `PowerSkills/`
  （`fix/pypsa-pandapower-api-drift`，用户指令冻结）。

## 六、快速验证命令（接手自检）

```bash
# 1) 网关全量（基线应为 567 passed）
cd gateway && ../PowerMCP/.venv/Scripts/python.exe -m pytest -q \
  --basetemp=../work/pt-<新目录名>

# 2) 变异探针（应 8/8 RED）
../PowerMCP/.venv/Scripts/python.exe .superpowers/sdd/m38-experiments-mutation.py

# 3) 真实网关 e2e（端口 8766；围笼须含项目根）
export POWERIO_MCP_ALLOWED_ROOTS="D:/coding/powerMcp_Pskills;D:/coding/powerMcp_Pskills/GridData;C:/Users/Z/.powermcp"
../PowerMCP/.venv/Scripts/python.exe -m uvicorn powermcp_gateway.api:create_app \
  --factory --host 127.0.0.1 --port 8766
# 登记算例 → 建实验 → 取回
curl -s --noproxy '*' -X POST http://127.0.0.1:8766/cases -H "Content-Type: application/json" \
  -d '{"path":"D:/coding/powerMcp_Pskills/examples/data/case39.m","label":"IEEE39"}'
curl -s --noproxy '*' -X POST http://127.0.0.1:8766/experiments -H "Content-Type: application/json" \
  -d '{"case_ids":["<上一步返回的 id>"],"factors":[{"name":"branch","values":["branch_1","branch_26"]}],
       "step":{"server":"surge","tool":"run_n1_branch_contingency",
               "args_template":{"file_path":"{case_path}","branch":"{branch}"}}}'
# 预期：201 · 2 格 · cache_key 互异 · args.file_path = 真实绝对路径 · status 全 pending
```

## 七、下游依赖提示

- **`experiments.py` 只做定义**：任何"执行"语义（结果落表、状态推进、重试）都还没有实现，
  不要以为 `status="pending"` 是 bug —— 那是本步的诚实边界，已写进响应 `notes`。
- **前端尚未消费 `/experiments`**：无 `ExperimentsView`、无 `ExperimentGrid`。
  UI 规范 §4.7.5 已固定三条约束，**①c 之后**才该动界面（否则对着不存在的端点定型）。
- **模块机制的 `result_tables` 是 ①c 结果表的落点**：列定义来自模块清单，
  内核 pivot 渲染（G-2）未实现 —— ①c 开工时需一并处理。
