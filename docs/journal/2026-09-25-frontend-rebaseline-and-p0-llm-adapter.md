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

## 五之二、P0-2a 交付：环境就绪 + 技能手册（`GET /environment` · `GET /skills`）

> 拆分理由：`/cases*` 要引入**新一级实体**（case/project）与存储决策，与这两个
> **只读索引端点**不是一回事 → 归 P0-2b，本单元只做 P0-2a。

### 新增文件

| 文件 | 行数 | 职责 |
|---|---|---|
| `gateway/src/powermcp_gateway/skills.py` | 300 | 索引 `PowerSkills/**/SKILL.md`；解析 frontmatter / kind / Escalation triggers；可计算健康信号 |
| `gateway/src/powermcp_gateway/environment.py` | 196 | **廉价**环境报告（不拉起任何 server） |
| `api.py`（附加式 +31） | — | `GET /environment` · `GET /skills` |
| `tests/test_skills.py` / `test_environment.py` / `test_api_p0_2.py` | 608 | 21 + 17 + 12 = **50 个新测试** |

### 关键设计

- **★ `GET /skills` 是 v4 相对 v3 最重要的补口**：实测 22 个技能（11 tool + 10 engineering + 1 meta），
  10 个 tool skill 带 escalation 表。surge 有 7 条（`vm_pu < 0.95` → `voltage-violation-mitigation` 等）。
- **★ 健康度只报可计算信号**，整体如实标 `unknown` —— **不转录人工审计结论**
  （🔴3/🟠4/🟡1 是人工阅读得出的，硬编码会立刻过期且无法复核）。
  三类信号：`escalation_missing` / `dangling_escalation` / `orphan_playbooks`。
  **独立复现了审计报告的三条结论**：`escalation_missing=["ltspice"]`、无悬空引用、无孤儿手册。
- **★ 环境报告刻意"廉价"**：不调用 `build_inventory`（那会真实拉起 server，秒级/个）。
  挂载状态由 `GET /contracts/t0` 给出，该分工**写进响应的 `notes`**，避免前端以为漏了。
  用一条**静态断言**（模块命名空间不得出现 `build_inventory`）把这条约束钉住。
- **★ 凭据安全**：`llm.endpoint` 只给 `scheme://host`（userinfo / path / query 都可能夹带凭据）；
  密钥只报 `api_key_set: bool`，**绝不回显值**。测试用 `json.dumps` **全文搜索**而非只查某字段。
- **不引入 PyYAML**：只需 `name` / `description` 两个标量，按**第一个冒号**切分即可
  （`description` 里含冒号是真实情况）。
- **PowerSkills 不在场 → 200 + 空清单**，不是 500（两仓库可分开 clone）。
- 两处「两个端点都报技能数」的不一致风险：`/environment` 的技能段**委托** `skills.build_report`，
  并用测试断言两者一致（单一真源）。

### ★ 变异探针逼出的一个真 bug

M3 一开始**未变红**（假护栏）——我的测试夹具让"任意标题即结束 escalation 节"这一分支
**不可达**（空行检查先命中）。深挖后发现真问题：节内一个 `### 子标题` 会让**整节被跳过**，
该技能随即被**误报为「缺 escalation 表」**（一条假健康警报）。

→ 修法：结束条件改为按**标题层级**判定（只有同级或更高级标题才结束本节），
并补测试 `test_triggers_survive_a_subheading_inside_the_section`。修正后 M3 变红。

### 验证

| 项 | 结果 |
|---|---|
| 测试 | **235 → 285 passed, 1 deselected**（+50），无回归 |
| 变异探针 | **11/11 全部变红**（`m5-p02-mutation.py`） |
| 端到端 | `m6-p02-e2e.py` —— 真实 app 打两个端点，断言廉价/不泄密/健康度 unknown/技能数一致 |
| 上游 | `PowerMCP/` 与 `PowerSkills/` 均 **0 行改动** ✓ |

## 五之三、★★ 一个阻塞级真缺陷 + P0-2b 算例库

### (a) 缺陷：MCP 子进程**拿不到**关键环境变量

P0-2b 要求"算例能被 server 读到"，故先做存储决策的实测（提案 §十四-4 的前置）。
实测（`.superpowers/sdd/m7-env-passthrough.py`）发现：

**MCP SDK 只继承一份白名单环境变量**（`mcp/client/stdio.py` 的
`DEFAULT_INHERITED_ENV_VARS`，Windows 上仅 APPDATA / HOMEDRIVE / HOMEPATH /
LOCALAPPDATA / PATH / PATHEXT / PROCESSOR_ARCHITECTURE / SYSTEMDRIVE / SYSTEMROOT /
TEMP / USERNAME / USERPROFILE），其余**一律不传**。

实测结果：父进程设 `POWERIO_MCP_ALLOWED_ROOTS` 与 `HIGHS_LIB_DIR` 后，
**二者都不在** `get_default_environment()` 里。后果：

| 变量 | 后果 |
|---|---|
| `POWERIO_MCP_ALLOWED_ROOTS` | **路径围笼形同虚设** —— server 只认默认根（`powerio.mcp.sandbox` 导入时的 cwd，即 `PowerMCP` 仓库根）→ **网关读不到算例目录**。表现为"读不到文件"而不是报错，极易误判为"路径写错了" |
| `HIGHS_LIB_DIR` | surge 的 DC OPF **永远拿不到求解器路径**。此前记为「仅在 shell 会话内有效」**不准确** —— 经网关调用时**从不生效** |

**修法**：
- `config.py` 加 `SERVER_ENV_PASSTHROUGH` + `server_env()`：**只传「已设置且非空」的项**
  （空串会被上游当作"未配置"而落到 legacy 变量）；另加逃生口
  `POWERMCP_GATEWAY_EXTRA_SERVER_ENV`（避免将来"某引擎需要某变量但清单里没有"只能改代码）。
- `proxy.py` 抽出 `_server_params()` 并显式传 `env` —— 让"传了什么"成为**可直接断言**的接缝。
- `environment.py` 新增 `server_env` 段：列出透传清单 + **本次实际会传哪些**。

✅ **同时回答了提案 §十四-4**：算例库放 `~/.powermcp_gateway/cases/` **不需要改动
`PowerMCP/` 一行** —— 网关只是把环境变量透传给子进程。

### (b) P0-2b：算例库（`case` 一级实体）

| 文件 | 行数 | 职责 |
|---|---|---|
| `gateway/src/powermcp_gateway/cases.py` | 343 | 登记 / 列举 / 详情 / 注销 + 现状视图 |
| `api.py`（附加式 +129） | — | `GET/POST /cases` · `GET/DELETE /cases/{id}` |
| `tests/test_cases.py` / `test_api_cases.py` | 527 | 29 + 18 = **47 个新测试** |

**三条关键设计决定**：

1. **按路径引用，不复制文件** —— 复制会在用户数据旁悄悄多出一份，且他改了原文件而库里还是旧的
   （**静默不一致**）。代价是"可复现依赖源文件在位"，故**登记时记录 sha256、读取时现算比对**，
   把 `drift` 显式报出来。
2. **`DELETE` 只注销登记，绝不删除源文件** —— 数据安全底线：
   一个 HTTP 动词不该能删掉磁盘上的算例。
3. **`within_allowed_roots` 与 `config.server_env()` 同源** —— 否则会声称"可读"而 server
   实际读不到（正是上面 (a) 那类"设了不生效"的坑）。并把 `CaseIndexError` 单列成类型，
   让端点**不靠匹配错误文本**区分 400 / 500。

**存储**：索引为可读 JSON + `os.replace` 原子替换。
**有意偏离 v4 §11.4 原写的「SQLite WAL」**（本地单用户、几十到几百条，JSON 可读可 diff 可手工核对），
**已同步更新 v4 文档**，避免文档与实现不一致。

### ★ 变异探针又逼出 3 条**测试**缺陷（这次是测试的问题）

M4 / M5 / M8 起初未变红，逐条归因：

| 变异 | 归因 | 修法 |
|---|---|---|
| M5 不校验路径是否存在 | **测试巧合通过** —— 夹具用 `不存在.m`，而兜底的 `is_file()` 报「必须是文件：…不存在.m」**恰好也含"不存在"** | 改用不含该词的 `ghost.m` |
| M8 更新时覆盖登记时间 | **测试依赖时间分辨率** —— 两次登记落在同一秒，`_now()` 返回相同字符串 | 用可控时钟（`monkeypatch` 一个递增 tick 迭代器） |
| M4 文件被删仍报 available | **代码有快路径**：`is_file()` 提前返回，避免"文件缺失"这种常见情形**每次列清单都刷 warning** | 补 `caplog` 断言：缺失不得告警；另补一条对照测试「真实读取失败**必须**告警」 |

> 三条都不是"代码有 bug"，而是**测试没区分力**。M4 那条还顺带说明了快路径的存在理由 ——
> 原本我以为它只是冗余防御。

### 验证

| 项 | 结果 |
|---|---|
| 测试 | **285 → 349 passed, 1 deselected**（+64），无回归 |
| 变异探针 | **16/16 全红**（env 5 条 `m8-env-mutation.py` + cases 11 条 `m9-cases-mutation.py`） |
| 端到端 | `m10-cases-e2e.py` —— 真实 app 走完 登记→更新→列举→漂移→注销，**源文件始终未被触碰**，真实 HOME 未被污染 |
| 上游 | `PowerMCP/` 与 `PowerSkills/` 均 **0 行改动** ✓ |

**提交**：`3dbb37d`（env 修复 + 算例库）。

## 五之四、P0-2b-2 算例解析为 PowerIO IR（**首个真实拉起 server 的单元**）

> 这一单元顺带**实测验证了上一轮的 env 透传修复** —— 正是它让"算例可被 server 读到"成立。

### ★ 实测：修复有效**且必要**（`m11-live-parse.py`）

| 情形 | 结果 |
|---|---|
| **修复后**（显式透传 env） | `powerio.parse` **成功**，返回 **59773 字符** |
| **反事实**（模拟修复前，`server_env()` 返回空） | `is_error=True: Error executing tool parse` |
| `parse` → IR → `diagnostics` 往返 | 成功（case39.m 诊断 0 条） |

**反事实那一行是关键**：它证明那次修复是**必要**的，而不是"恰好能跑"。
单测能证明"我们传了 env"，只有实测能证明"不传就会失败"。

### ★ PowerIO 返回值是**双层编码**（踩坑点，已写入代码注释）

```
parse 的文本 = {"value_type": "powerio.BalancedNetwork",
               "powerio_ir": "{\n  \"schema\": \"pio-ir\", ... }"}   ← 又一层 JSON 字符串
```

故产物**原样保存该字符串**；缺 `powerio_ir` 即 502 并指明"上游形态可能已变"。
任何"顺手解析一下"都会让 `diagnostics` 拿到错的东西。

### 交付物

| 文件 | 行数 | 职责 |
|---|---|---|
| `gateway/src/powermcp_gateway/case_ir.py` | 195 | 解析 + 产物落盘（`<cid>/parse.json`，记 `source_sha256`） |
| `api.py`（附加式 +164） | — | `POST /cases/{id}/parse` · `GET /cases/{id}/ir` · `GET /cases/{id}/diagnostics` |
| `tests/test_api_case_ir.py` | 399 | **19 单元 + 1 集成**（集成需 `-m integration`） |

**关键设计**：
- `parse` **会真实拉起 powerio**（秒级），故为 POST 且**每次重新解析**；响应**不内联 IR**（约 60KB），IR 走 `GET /ir`。
- `GET /ir` 解析失败时 `ir_parsed=false` 并**原样给字符串** —— 不假装成功。
- `GET /diagnostics` 的 `stale` **现算**：产物记的是解析时的哈希，源文件改了即报。
- **前置条件显式检查**：源文件不在 `POWERIO_MCP_ALLOWED_ROOTS` 内 → 409 且
  **指出该把哪个目录加进去**，而不是让用户看一个看不懂的沙箱错误。
- 错误映射：400 请求非法 / 404 未知 id / **409 状态不允许**（文件没了、不在允许根、未解析）/
  **502 引擎侧失败** / 500 索引损坏 / 503 配置失败。

### ★ mock 的经典坑（值得记住）

单元测试初次跑用了 **36 秒** —— 因为 `case_ir` 是 `from .inventory import build_inventory`，
而我只 patch 了 `api_mod.build_inventory`。**必须打在使用它的模块命名空间里**，
否则"单元测试"其实在真实拉起 server（慢且依赖环境）。
已修，并在测试里写明原因。修后默认套件 **2.15s**。

### ★ 变异探针又发现 1 条假护栏（M4）

M4 未变红：它瞄的是「合法 JSON 但**不是对象**」这条守卫，
而我的测试走的是「**根本不是** JSON」那条 —— **两条是不同守卫**。
补测试 `test_parse_reports_502_when_output_is_not_an_object` 后 M4 变红。

> 另外有两条断言是**提前**加固的（推理而非探针发现）：引擎失败若被后续字段校验掩盖，
> 错误信息会变成"缺少 powerio_ir"——上报的原因就不对了。故用**合法 JSON 的错误正文**
> 让两条路径的错误信息可区分。

### 验证

| 项 | 结果 |
|---|---|
| 测试 | **349 → 368 passed, 2 deselected**（+19 单元 + 1 集成），无回归 |
| 变异探针 | **11/11 全红**（`m12-caseir-mutation.py`） |
| 集成实测 | `-m integration` 真实拉起 powerio：parse → IR → diagnostics 往返通过（6.66s） |
| 上游 | `PowerMCP/` 与 `PowerSkills/` 均 **0 行改动** ✓ |

**提交**：`578b3f4`。

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
