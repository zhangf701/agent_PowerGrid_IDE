# 交接：实验矩阵 V2 研究闭环（提案 → 编译 → 不可变实验 → Observation）（2026-09-28）

> 接手人请先读 `docs/journal/_index.md`，再读本文。
> 本文是 2026-09-28 对实验矩阵 V2 重构的最新交接入口；与 2026-09-27 的 P2 handoff 相比，本文描述的是新增的研究层与兼容接线。
>
> 一句话状态：**实验矩阵已经从 V1 的「静态批量执行器 + 结果表」升级为 V2 的「提案 → 校验 → 确定性编译 → 不可变定义 → 串行执行 → Observation Store → 确定性分析」最小闭环**；V1 API 继续可用。

---

## 一、交付结论

本次依据：

```text
docs/chatGPT_PowerMCP_Agentic_Research_Experiment_Spec_Plan.md
```

完成了 V2 MVP 的核心研究层，不改变 V1 的确定性执行基座：

```text
ExperimentProposal
      ↓ validate
      ↓ preview + resource estimate
      ↓ explicit commit
Immutable Experiment
      ↓ serial executor / one session per cell / no LLM
Observation Store (observations.jsonl)
      ↓
Deterministic Analysis
```

关键原则已经落到代码：

- Agent 或用户可以先提出实验，但**提案不会自动 commit**；
- commit 前完成校验、资源估算和格子预览；
- commit 后固定算例 `case_sha256`、路径、因子展开结果、步骤序列、`cell_id` 和 `cache_key`；
- `definition.json` 不允许被不同内容覆盖；
- 执行期间不调用 LLM、不动态改参数、不自适应重规划；
- 每格独立会话，串行执行；
- Observation 与 compact metrics 分离，详细执行诊断落入 JSONL；
- 研究结论仍由 Agent 解释，确定性分析不冒充因果推断。

---

## 二、代码交付

### 1. V2 内核包

新增：

```text
gateway/src/powermcp_gateway/experiment_v2/
├── __init__.py
├── models.py          # ResearchQuestion / Hypothesis / Proposal / Experiment / Cell / Observation
├── validator.py       # schema / semantic / feasibility 校验
├── compiler.py        # 确定性展开、cell_id、cache_key、commit
├── resources.py       # cells / steps / duration / artifact size 估算
├── stores.py          # ProposalStore / ObservationStore(JSONL)
├── analysis.py        # summary / extreme / boundary / comparison / failure
├── proposals.py       # 提案层导出入口
└── observations.py    # 观察层导出入口
```

新增项目根契约：

```text
schemas/
├── research_question.schema.json
├── hypothesis.schema.json
├── experiment_proposal.schema.json
├── experiment.schema.json
├── cell.schema.json
├── observation.schema.json
└── artifact.schema.json
```

### 2. API 接线

新增提案端点：

```text
POST /experiment-proposals
GET  /experiment-proposals/{proposal_id}
POST /experiment-proposals/{proposal_id}/validate
POST /experiment-proposals/{proposal_id}/commit
```

新增 V2 查询端点：

```text
GET  /experiments/{eid}/summary
GET  /experiments/{eid}/design
GET  /experiments/{eid}/observations
GET  /experiments/{eid}/cells/{cell_id}
GET  /experiments/{eid}/cells/{cell_id}/artifacts/{artifact_id}
GET  /experiments/{eid}/analysis
POST /experiments/{eid}/cancel
```

V1 端点继续保留：

```text
POST   /experiments
GET    /experiments
GET    /experiments/{eid}
POST   /experiments/{eid}/run
GET    /experiments/{eid}/results
GET    /experiments/{eid}/export?format=csv|md
DELETE /experiments/{eid}
```

V2 实验通过 V1 的 `/experiments/{eid}`、`/results` 兼容视图读取，列表端点也会合并 V1/V2 实验。

### 3. 前端交付

新增：

```text
frontend/src/components/ExperimentProposalCard.tsx
```

修改：

```text
frontend/src/views/ExperimentsView.tsx
frontend/src/components/ExperimentGrid.tsx
frontend/src/api.ts
frontend/src/gatewayPaths.ts
frontend/src/api.test.ts
frontend/src/components/index.ts
```

前端现在可以：

1. 选择算例；
2. 填写研究问题和假设；
3. 填写因子与显式步骤；
4. 创建并校验提案；
5. 查看格数、资源估算和校验结果；
6. 明确点击 Review 后 Commit；
7. commit 后跳转到冻结的实验定义；
8. 继续使用原有矩阵、串行执行和结果表视图。

---

## 三、状态模型与执行边界

V2 Observation 至少区分：

```text
pending
running
completed
failed_environment
failed_execution
failed_validation
not_converged
cancelled
```

当前执行器仍遵守 2026-09-27 已核实的三条硬约束：

1. **一格一个会话**：防止跨格残留网络污染；
2. **`remounted=True` 判环境失败**：不把断裂后状态不可信的结果报成功；
3. **多步实验无会话池返回 503**：不静默拆成多个进程。

取消是协作式的：

- `POST /experiments/{eid}/cancel` 只设置取消请求；
- 当前工具调用完成后，在下一个格子边界停止；
- 已取消格子写入 `cancelled`，不冒充 `failed`。

当前仍不支持：

- 实验级并发执行；
- 跨机文件租约；
- 自动重试策略与 attempt 记录；
- Agent 自动从 session trace 生成 proposal；
- Agent 自动读取分析结果并生成 follow-up proposal；
- 真实 artifact 文件写入与 artifact 内容查询；
- `result_tables` 越限明细透视；
- 统计因果推断、Monte Carlo、Bayesian optimization、分布式执行。

---

## 四、存储布局

V2 实验存放在 V1 实验根目录下的独立子目录，避免覆盖既有 V1 索引：

```text
~/.powermcp_gateway/experiments/v2/
├── proposals/
│   └── proposals.json
└── <eid>/
    ├── proposal.json
    ├── definition.json
    ├── manifest.json
    └── observations.jsonl
```

`definition.json` 是 commit 后的不可变执行定义；`observations.jsonl` 一行一个 Observation。

---

## 五、验收结果

### 后端

```text
gateway 全量测试：651 passed
实验矩阵 V1/V2 相关测试：106 passed
```

新增测试：

```text
gateway/tests/test_experiment_v2.py
gateway/tests/test_api_experiment_v2.py
```

覆盖重点：

- 模型冻结与 JSON 往返；
- 空步骤、未知占位符、资源上限；
- 确定性编译；
- 算例身份固定；
- Proposal Store；
- Observation JSONL Store 与查询；
- 确定性分析；
- commit 后定义不可变；
- 提案 API；
- V2 执行、Observation 写入、结果兼容读取。

### 前端

```text
tsc --noEmit：通过
vite build：通过
```

全量 Vitest 当前仍受仓库既有测试环境问题影响：

- 根目录执行会把 `work/repo_eval/**` 下的测试一并收集；
- 出现既有 `Vitest failed to find the current suite`；
- 定向配置曾引用缺失的 `src/test-setup.ts`。

这不是本次 V2 代码的类型错误或构建错误；后续若要宣称前端全量测试恢复，需要单独修复测试配置与收集范围。

---

## 六、接手自检命令

```bash
# 网关全量
PYTHONPATH="D:/coding/powerMcp_Pskills/gateway/src" \
"D:/coding/powerMcp_Pskills/PowerMCP/.venv/Scripts/python.exe" -m pytest -q \
"D:/coding/powerMcp_Pskills/gateway/tests"

# 实验矩阵 V1/V2 定向回归
PYTHONPATH="D:/coding/powerMcp_Pskills/gateway/src" \
"D:/coding/powerMcp_Pskills/PowerMCP/.venv/Scripts/python.exe" -m pytest -q \
"D:/coding/powerMcp_Pskills/gateway/tests/test_experiments.py" \
"D:/coding/powerMcp_Pskills/gateway/tests/test_api_experiments.py" \
"D:/coding/powerMcp_Pskills/gateway/tests/test_experiment_v2.py" \
"D:/coding/powerMcp_Pskills/gateway/tests/test_api_experiment_v2.py"

# 前端
cd frontend
# 使用项目已有 Node 环境执行：
# tsc --noEmit -p tsconfig.json
# vite build
```

---

## 七、下一步建议

按 V2 原计划，下一轮优先级建议为：

1. 把 `propose_experiment_from_session` 接到 Agent session trace，但只生成 Proposal，不自动 commit；
2. 增加 Agent 查询工具：summary / design / observations / cell / analysis；
3. 完成真实 artifact manifest 与 hash 存储；
4. 在前端增加 Overview / Design / Execution / Observations / Analysis / Artifacts / Provenance 标签页；
5. 将 Observation 上下文注入 Agent，形成「结果 → 解释 → follow-up proposal」闭环；
6. 单独规划 `result_tables` 模块透视，不把领域语义硬编码进内核。

**不要**在下一步直接打开实验并发；并发开关仍应等 session 隔离、artifact 写入、cache 原子性和确定性排序再次验收后再评估。

---

## 八、仓库状态提示

- `PowerMCP/`、`PowerSkills/` 仍保持上游冻结约定，不应修改；
- 本次涉及网关、前端、schema、测试和文档；
- 本交接日志记录的是当前工作区事实，不代表已经创建 Git commit；
- 若提交，建议按「V2 网关内核 / API 接线 / 前端提案 UI / 文档」拆成逻辑单元。
