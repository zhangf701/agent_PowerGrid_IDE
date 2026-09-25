---
date: 2026-09-25
type: journal
keywords: [前端重定位, 通用研究工作台, 模块化架构, 契约降级, P0-1, LLM Provider Adapter, Agent 循环, 网关无 LLM 层]
git_branch: master
git_head: 69b0960（本文档与代码改动尚未提交）
previous: handoff_2026-09-24_subproject3-closed.md
note: 本会话做了两件事：① 前端方案**定位级重定位**（与论文选题解绑）② 交付 P0 的第一个工程单元（LLM Provider Adapter + Agent 循环 + 对话端点）。
---

# 前端重定位 + P0-1（LLM 对话链路）

## 一、本会话的起点：一个定位级冲突

张老师明确前端目标是「**直观、方便地用 powermcp + powerskills 做电力系统相关的任何研究，
不限定于某一个具体科研方向**」。核查后发现《前端设计方案》v3 与该目标**在设计意图上冲突**：

| 证据（原文可复核） | 出处 |
|---|---|
| 该前端「是 L2 的可视化层，也是 L3 的呈现层 —— **而不是一个通用聊天前端**」 | 方案 v3 文末 |
| 「建议定位为『**需要审计时的专用界面**』，而非日常入口」 | 方案 v3 §十二-3 |
| 「前端只有在**作为 L3 校验套件的可视化层**时才与选题绑定」 | 方案 v3 §十二-5 |
| **契约状态是第一公民** | UI 规范 P1 |
| 实施路线 P1/P2/P3 **每一阶段均标注「对应选题 L2 / L3」** | 方案 v3 §八 |

**最硬的一条证据（词频）**：张老师点名要用 powerskills，但实测
《前端设计方案》全文 `skill` 仅 **1 次**（且只是契约 2 的比对对象），《UI 设计规范》**0 次**。
21 个技能（11 工作流 + 10 缓解手册）在方案中**零覆盖**。

→ 核查方法已沉淀为技能 `design-doc-goal-alignment`（目标拆清单 + 词频统计 + 原文引用自陈定位句）。

## 二、张老师的三次裁决

| # | 裁决 | 日期 |
|---|---|---|
| 1 | **重定位为通用研究工作台**（契约从「第一公民」降为可开关的校验层，能力一个不丢） | 2026-09-25 |
| 2 | **前端与论文选题解绑**，作为自用工具 | 2026-09-25 |
| 3 | 提案 §九 五项设计判断**全部采纳建议值**：契约层默认开且折叠 · 技能双轨触发 · 算例库独立目录 · 实验矩阵先串行 · 导出 Markdown+CSV+HTML→PDF | 2026-09-25 |
| 4 | P0-1 的两个设计决策：**仅 OpenAI 兼容接口** · **Agent 循环在网关侧** | 2026-09-25 |

## 三、本会话产出的文档

| 文档 | 内容 |
|---|---|
| `docs/PowerMCP_前端方案重定位提案.md` | 定位变更论证 + 逐条对照 + 五项判断（已标裁决） |
| `docs/PowerMCP_前端模块化架构.md` | 内核 + 可插拔选题模块；**三层成熟度 L0/L1/L2** |
| `docs/PowerMCP_前端设计方案.md` | **v4**（968 行）：重定位 + 5 主视图 + 1 可开关校验层 + 模块化 |
| `work/frontend-design/PowerMCP_前端设计方案_v3.1.md` | ⚠️ **归档修正**：原 `_v3.md` 是**过期**版本（缺 2026-09-24 实测校正），docs 版才是权威当前版 |

**v4 的关键写入**：
- **内核自证条件**：禁用全部模块后内核仍可用 —— 否则说明内核被领域知识污染。
- **废除 v3 的落地条款「契约状态先于图表渲染」**。
- **新增 P0（内核骨架+脚手架+设计系统）与 P1.5（2 个真实模块验证扩展点后冻结接口）**。
- **§11.2 并发隔离从 P2 提升**为实验矩阵的前置条件。
- **§十二 自用验收判据 7 条**（替代 v3 §九 的 12 人组间实验 —— 已解绑论文，不再适用）。

## 四、★ 本会话最重要的技术发现：网关**没有 LLM 层**

实测 `grep -rn -i "llm|provider|openai|chat_completion" gateway/src/` → **0 命中**。

| 端点 | 当时实际做什么 |
|---|---|
| `POST /sessions` | 只创建「server 列表 + id + created_at」 |
| `GET /sessions/{sid}/events` | SSE 事件流（EVIDENCE / TELEMETRY 双通道） |
| `POST /sessions/{sid}/tools/call` | 代理**一次**工具调用 |

→ **没有任何「自然语言 → 工具调用」的层，也没有流式回答。**
→ **「对话分析」（v4 §4.3，主界面）当时没有后端。**

**同时修正了 v4 的一处事实性标注错误**：§2.1 的 Layer 1 框原标注「（已交付 · 子项目 2/3）」，
把 LLM Adapter 与进程监管一并罩进"已交付"，易被读成已完成。已改为两段式（✅ / ⏳）。

## 五、P0-1 交付：LLM Provider Adapter + Agent 循环 + 对话端点

### 新增文件

| 文件 | 职责 |
|---|---|
| `gateway/src/powermcp_gateway/llm.py` | OpenAI 兼容流式适配器。跨 chunk 累积工具调用；坏 SSE 行隔离；超时补上下文；`httpx` 可注入（离线测试） |
| `gateway/src/powermcp_gateway/agent.py` | 网关侧 Agent 循环。工具名 `server__tool`（**契约 5 命名空间**要求）；`ExecuteTool` 可注入；失败语义明确 |
| `gateway/src/powermcp_gateway/api.py`（**附加式修改**） | 新增 `POST /sessions/{sid}/chat` + 5 个纯函数解析器 + Provider 单例 |
| `tests/test_llm.py` / `test_agent.py` / `test_api_chat.py` | 18 + 19 + 17 = **54 个新测试** |

### 关键设计

- **循环在网关侧**：工具执行经 `call_with_contracts` → `proxy.call_tool`，
  因此**契约 3 的 fail-closed 校验、契约 finding 的 EVIDENCE 发布、NDJSON 审计全部天然在环内**。
  端到端实测确认：缺必填参数 `network_name` 的调用**被拦下且未转发**，总线出现 `contract_violation`。
- **SSE 事件**：`text` / `notice` / `tool_call` / `tool_error` / `final` / `error`（白名单，不直通）。
- **可重放 vs 瞬时**：`user_message` / `tool_call` / `assistant_message` / `turn_error`
  **同时**写总线与审计；`text` 增量只在本流里。
- **HTTP 状态码只覆盖「请求能不能开始」**：404 / 400 / 503；
  **开始之后的失败一律走 `error` 事件**（`StreamingResponse` 发出响应头后状态码不可改）。
- **`tool` 角色不得由客户端注入** —— 否则可伪造工具结果污染审计。
- **`notice` 事件**：部分 server 拉不起来时必须说出来（v4 §4.1「装得上 ≠ 跑得动」）。
- **`servers` 收窄参数**：允许按轮指定 server 子集 —— 这是当前唯一不需要引入清单缓存的
  实用优化，也是"选题模块声明工具白名单"的雏形。
- **对话历史不持久化**：客户端传完整历史（LLM API 通行做法）；
  "刷新后恢复"明确落在**会话持久化**这个独立单元，不藏在端点里做半套。

### 验证

| 项 | 结果 |
|---|---|
| 测试 | **181 → 235 passed, 1 deselected**（+54） |
| 变异探针 | **18/18 全部变红**（llm 5 · agent 6 · chat 7），脚本在 `.superpowers/sdd/m{1,2,3}-*-mutation.py` |
| 端到端 | `.superpowers/sdd/m4-chat-e2e.py` —— SSE 帧序列 / 契约 fail-closed / 总线 EVIDENCE / NDJSON 审计 四项全过 |
| `PowerMCP/` | **0 行改动** ✓ |

## 六、仍未做 / 下一步

1. **《UI 设计规范》未同步至 v2** —— 已在 v4 §十四-1 声明「同步完成前，v1.2 与 v4 冲突处以 v4 为准」。
   需同步：P1 原则、5 个签名组件的位置、§5.1 应用骨架、§7.4（契约摘要改可选）、新增组件规格。
   ⚠️ **它是 P0 第 4 步（设计系统落地）的前置，但不阻塞 P0-2/P0-3。**
2. **P0-2：网关端点** —— `GET /environment` · `GET /skills` · `/cases*`。
   ★ `GET /skills` 解锁「技能手册」（v4 最重要的新增视图、v3 零覆盖的痛点）。
3. **P0-3：内核骨架 + 模块脚手架**。
4. **T6-M5 加剧**：`/chat` 每轮都 `build_inventory`（真实拉起 server，秒级/个）。
   当前用 `servers` 收窄缓解；**根因待子项目 4（进程监管）**。
5. **`_is_timeout` 已出现第三处消费者**（`proxy` / `inventory` / `llm`）——
   `proxy.py` 注释写明「若出现第三处消费者，再提取共享模块」。**应提取，但需独立单元 + 回归。**
6. 提案 §十四-4：算例库独立目录 `~/.powermcp_gateway/cases/` 是否构成对 `PowerMCP/` 的事实改动 —— **须实测**。

## 七、给接手 agent 的提醒

- **本会话的改动尚未提交**（HEAD 仍为 `69b0960`）。`git status` 会看到
  `gateway/src/powermcp_gateway/{llm,agent}.py`、3 个新测试、`api.py`（M）、
  3 份 docs 与 `work/frontend-design/` 下的 v3.1/v4 归档。
- **`work/frontend-design/PowerMCP_前端设计方案_v3.md` 是过期版本**，勿据它复原 v3。
- 本会话新技能：`design-doc-goal-alignment`（判定设计文档是否服务用户声明的目标）。
- 变异脚本 `m1/m2/m3-*.py` **不是幂等的**（自行备份/恢复目标文件）；复用前确认目标文件未被改动。
