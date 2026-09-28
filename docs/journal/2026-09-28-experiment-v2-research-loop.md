# 2026-09-28 — 实验矩阵 V2 研究闭环实现

> 状态：✅ V2 MVP 已交付；Agent 结果回流与 session trace 自动提案仍为后续工作。
> 详细接手信息见 [handoff_2026-09-28_experiment-v2-research-loop.md](handoff_2026-09-28_experiment-v2-research-loop.md)。

## 一、背景

V1 实验矩阵已经具备确定性网格展开、串行执行、逐格失败可见、`cache_key` 对齐和 CSV/Markdown 导出，但 Agent 探索与批量实验之间需要人工手抄 JSON，批量结果也不能回流到 Agent。依据 V2 规格，本次选择「路线 C：Agent 探索与确定性执行分工」的第一阶段：先补提案、编译、Observation 和确定性分析，不把 LLM 放进执行循环。

## 二、交付

### 后端 V2 内核

新增 `gateway/src/powermcp_gateway/experiment_v2/`，包含：

- `ResearchQuestion`、`Hypothesis`、`ExperimentProposal`、不可变 `Experiment`、`Cell`、`Observation`、`Artifact`；
- 提案 schema / semantic / feasibility 校验；
- 确定性因子展开与 `linear_range` 生成器；
- commit 时固定算例 `case_sha256`、路径、步骤、显式 `cell_id`、`cache_key`；
- `definition.json` / `proposal.json` / `manifest.json`；
- `observations.jsonl` 追加式存储与按状态、算例、格子查询；
- summary、extreme、boundary、representative、pattern、factor comparison、failure analysis。

### API

提案生命周期：

```text
POST /experiment-proposals
GET  /experiment-proposals/{proposal_id}
POST /experiment-proposals/{proposal_id}/validate
POST /experiment-proposals/{proposal_id}/commit
```

V2 查询与控制：

```text
GET  /experiments/{eid}/summary
GET  /experiments/{eid}/design
GET  /experiments/{eid}/observations
GET  /experiments/{eid}/cells/{cell_id}
GET  /experiments/{eid}/cells/{cell_id}/artifacts/{artifact_id}
GET  /experiments/{eid}/analysis
POST /experiments/{eid}/cancel
```

V1 `/experiments*` 保留；V2 定义提供兼容读取视图，并合并到实验列表。

### 前端与契约

- 新增 `ExperimentProposalCard`：研究问题、假设、算例、步骤、因子、校验预览和显式 Review/Commit；
- `api.ts` 增加 V2 Zod schema；
- `gatewayPaths.ts` 增加 `experiment-proposals` 代理前缀与守卫；
- 根目录 `schemas/` 增加 7 个 V2 JSON Schema；
- `ExperimentGrid` 增加 V2 执行状态显示。

## 三、重要边界

- commit 后定义不可变；设计变化必须创建新 Proposal / Experiment；
- 执行仍串行、一格一会话、无 LLM；
- 多步实验没有会话池仍返回 503；
- 取消只在格子边界生效，写入 `cancelled`，不伪装成 `failed`；
- 当前未完成 session trace 自动提案、Observation 注入 Agent、follow-up proposal、真实 artifact 内容写入、`result_tables` 透视和实验级并发；
- 确定性分析不声称因果关系或统计显著性。

## 四、验证

```text
gateway 全量：651 passed
实验矩阵 V1/V2 定向：106 passed
frontend tsc --noEmit：通过
frontend Vite build：通过
```

全量 Vitest 仍受仓库既有配置/收集问题影响：根目录会误收集 `work/repo_eval/**`，并出现既有 suite 错误；定向配置曾引用缺失 `src/test-setup.ts`。该问题未归因于本次 V2 改造。

## 五、后续

1. `propose_experiment_from_session`：trace → Proposal，不自动 commit；
2. Agent 查询工具和结构化上下文注入；
3. follow-up proposal；
4. artifact manifest / hash / payload；
5. `result_tables` 模块透视；
6. 在上述基础稳定前不打开实验并发。
