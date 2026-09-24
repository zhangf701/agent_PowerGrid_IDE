---
date: 2026-09-24
type: handoff
keywords: [子项目3关闭, 全分支审查, 4条Important, 收口, SDD教训, 子项目4/5待启动]
git_branch: master
git_head: c981f9f
previous_handoff: handoff_2026-09-24_gateway-t2-complete.md
note: 本 handoff 记录**子项目 3 的收尾审查与全部修复**，子项目 3 已可关闭。前序 handoff 记录 Task 0–7 的交付；本文件记录其后的两轮审查、修复与验收。
---

# Handoff: 子项目 3 收尾审查完成（可关闭）

## 项目定位

在本地把 **PowerMCP**（16 个 MCP server / 约 250 工具）+ **PowerSkills**（21 个技能）跑通、验证能力边界，
并在此基础上做「AI/Agent × 电力系统」的选题。当前处于**从调研转向工程落地**的阶段：
选题唯一存活候选是 **MCP / agent-tool 接口标准化**（新颖性专查**仍未做**）；
前端方案 v3 与 UI 规范 v1.2 已定稿；**网关（子项目 2 的 T0 契约 + 子项目 3 的 T2/审计/SSE）已交付并收尾**。

---

## 本周期增量

### 一、补做了两项此前欠下的审查

| 审查 | 范围 | 报告 |
|---|---|---|
| **Task 7 补审**（上轮因 429 缺失） | `5b786e3..c9bc5e7` | `.superpowers/sdd/task-7-review.md` |
| **最终全分支审查** | `5111d47..c9bc5e7`（40 commits） | `.superpowers/sdd/final-branch-review.md` |

- Task 7 补审的核心结论：生产代码正确，但**它的唯一生产改动（lifespan 钩子）当时没有真正的回归护栏** ——
  `test_shutdown_flushes_audit` 手搓 `api_mod._lifespan(app)` 绕过 FastAPI 生命周期（而 `_lifespan` 不使用 `app`），
  删掉 `lifespan=_lifespan` 该测试**仍全绿**（变异探针 1A/1B/1C 三重对照）。
- 全分支审查的 4 条 Important（详见下节）+ 台账 35 条 Minor 逐条分诊（**成立 33 / 不成立 2**）+ 台账外新发现 6 条。

### 二、4 条 Important（判据级改动**均经用户裁决**）

| # | 问题 | 裁决 | 处置 |
|---|---|---|---|
| **I-1** | 契约 3 违规事件不是 `ContractFinding` 形状（缺 `state`/`subject`/`detail`/`evidence`）→ 进不了 `summarize()` 双轨汇总 → **主徽标永远不会因契约 3 变红**（fail-open） | 补 `state`/`subject` 使之同形 | ✅ 改为用 `ContractFinding` **构造**再 `asdict`（形状由模型保证）；另立 `contract_unknown` kind 区分"无法判定"与"有违规" |
| **I-2** | 慢（未断开）SSE 客户端 → 该会话**所有** EVIDENCE 发布被拒 → 事件既不进历史也不落审计（由台账 T0-M5 的"设计取舍"**升级为可达缺陷**） | **根治：解耦「记录」与「投递」** | ✅ `publish` 不再因满队列拒绝；滞后订阅者被标记并计数（`lagged_queues` 现状量 / `lagged_deliveries` 累计量）；`gen()` 主动断流，由历史重放兜底 |
| **I-3** | `validate_args` 在 `try` 之外，畸形 schema 的 `TypeError` 逃出 → **HTTP 500**（= 台账 T4-M3 + T5-M6 的**同一条**，因拆记而长期未修） | 修 | ✅ `_accepted_types` 安全返回 `()` + `call_tool` 内 `try` 兜底；异常降级为 `contract_unknown`（**放行转发但不静默**） |
| **I-4** | 契约 4 值比较大小写敏感 → `{"status":"SUCCESS"}` **假阴性**；同处 `1 == True` 假阳性 | 授权修正 + 重测基线 | ✅ 大小写归一 + `is True`；**重测基线不变**（仍 6 条：pypsa×2 / andes×1 / egret×3）——修的是**潜在**缺陷 |

### 三、独立验证发现并收口的三条残留（提交 `c981f9f`）

| # | 问题 | 处置 |
|---|---|---|
| **C-2**（最重要） | 审计写失败是**静默降级**：`bus.publish` 成功而 `audit.append` 失败时，事件只在**内存历史**、NDJSON 里没有，**且无任何计数** —— I-2 之后唯一残留的静默路径（审计无轮转 + 长生命周期 → "磁盘满"只是时间问题） | ✅ `AuditLog.append()` 返回 `bool`；失败计数 `append_failures` + `last_error` + `logger.error`，**不抛**；新增 `stats()`；`GET /health` 暴露 `audit`；`proxy._emit` 检查返回值并补充定位告警 |
| **C-1** | 同类畸形"一个报告、一个沉默"：`{"properties":{"x":{"type":5}}}` 走"安全返回 `()`"路径 → 静默放行；而同类的 `{"properties":5}` 走异常路径**会**报 unknown | ✅ 新增 `params.schema_is_unusable()`（**不改** `validate_args` 的签名与行为），让 `call_tool` 对前者补发 `structural` unknown；两路径互斥、不重复 |
| **C-3** | `api.py` 两处注释仍写 I-2 **之前**的后果（"最终让整个会话的 EVIDENCE 发布失败"） | ✅ 修正为"只会让该订阅者自己滞后；轮询只是为及时回收名额" |

### 四、护栏补强（本周期最重要的方法教训）

审查的变异探针揭示：本周期的**高价值修复集中在错误路径，而恰恰错误路径的测试覆盖最差**——

| 探针 | 变异 | 修复前的实测 |
|---|---|---|
| **A** | `_dispatch` 删掉 `is_error` 回传 | `test_proxy.py` **仍 7 passed** —— 本周期最高价值修复无护栏 |
| **C** | 同时破坏 `gen()` 的 seq 去重与 `finally: unsubscribe` | **仍 10 passed** |

已补：`_dispatch` 的 `is_error` 与"超时补上下文"（用 monkeypatch **传输层**的方式真跑 `_dispatch`）、
`gen()` 的 7 条行为测试、`lifespan` 改走 `app.router.lifespan_context`（**真实接线**，并以"删掉 `lifespan=` 必须变红"反向验证）、
`REGISTRY` 契约集合断言、路由级 6 条端到端测试、审计降级与 C-1 的护栏。

> ★ **约定（务必沿用）**：修复错误路径必须与「钉住该错误路径的测试」**成对交付**，
> 且各自用变异探针自证 —— **把修复改回旧行为，那条测试必须变红**。

---

## 关键决策（仅增量）

| 决策 | 理由 |
|---|---|
| **`contract_unknown` 另立 kind，不沿用 `contract_violation`** | 把"无法判定"塞进"有违规"的 kind，会让任何按 kind 过滤的消费者产生**假警报** —— 与"假绿灯"是同一枚硬币的另一面 |
| **畸形 schema 选择"放行转发 + 上报 unknown"而非 fail-closed 拒发** | 畸形 schema 不是"这次调用有问题"的证据，拒发会打断合法调用；但也不能静默 |
| **`lagged_deliveries` 记"累计被跳过条数"而非"每队列计 1"** | 这是**丢失量级**的度量；否则卡死客户端丢了一万条后计数仍停在 1，看不出降级规模 |
| **`close()` 即使 flush 失败也必须关句柄** | 释放 fd 是第一职责，否则 T1-M7 的 fd 泄漏会在失败路径上原样复发 |

---

## 当前状态

- ✅ **子项目 3 的收尾审查与全部修复完成**：4 条 Important 闭合 + 3 条残留收口 + 9 条当期修 Minor
- ✅ **测试 138 → 180 passed, 1 deselected**（deselected = `tests/test_inventory.py:60` 的 integration 标记）
- ✅ `PowerMCP/` 仍 **0 行改动**
- ✅ 独立验证：4/4 Important 闭合、4/4 变异变红、交付声明与代码逐条吻合（`final-verification.md`）；F5 增量的独立验证见 `f5-verification.md`
- ✅ 文档已回填：计划 4 处勘误 + 文末「最终审查与修复」章节、`README.md` 补齐 3 个端点与契约 3 事件形状、台账收尾
- ⚠️ **opendss 无法经 mcp SDK 挂载**（唯一真阻塞，根因未定）
- ❌ **选题新颖性专查仍未做** —— 是"这些工程能否构成论文"的 gate
- ❌ Gurobi 许可过期（2026-03-31）；Ipopt 不可用
- 📋 子项目 1（设计系统落地）/ 4（进程监管）/ 5（前端视图）未开始
- 📋 `examples/` 仍未纳入 git

---

## 快速上手指令

```bash
cd d:/coding/powerMcp_Pskills

# 1. 文档中心（强制先读）
cat docs/journal/_index.md

# 2. SDD 进度台账（**接手必读**：含全部审查结论、Minor 分诊与仍开放项）
cat .superpowers/sdd/progress.md

# 3. 审查与验证报告
cat .superpowers/sdd/task-7-review.md          # Task 7 补审
cat .superpowers/sdd/final-branch-review.md    # 最终全分支审查（4 Important + 35 Minor 分诊）
cat .superpowers/sdd/final-verification.md     # 独立验证（4/4 闭合 + 4/4 变异变红）
cat .superpowers/sdd/f5-verification.md        # 收口补丁的独立验证

# 4. 验证测试仍全绿（期望 180 passed, 1 deselected）
#    ⚠️ --basetemp 必须指向「尚不存在」的新目录：指向已存在且含 >50 条目的目录时，
#    pytest 启动的 rm_rf 会被沙箱批量删除护栏拦截 → tmp_path 测试 setup 阶段 ERROR，
#    表现为「76 passed / 23 errors」，极易误读为代码回归。
cd gateway && ../PowerMCP/.venv/Scripts/python.exe -m pytest -q -m "not integration" \
  -p no:cacheprovider --basetemp=./.pytest_tmp/r1

# 5. 只读探针（可复用的独立复核工具）
cd d:/coding/powerMcp_Pskills
./PowerMCP/.venv/Scripts/python.exe .superpowers/sdd/probe-contract3-shape.py   # 契约 3 是否 ContractFinding 同形
./PowerMCP/.venv/Scripts/python.exe .superpowers/sdd/probe-backpressure.py      # I-2 背压不变式

# 6. 两个子仓库状态（应分别停在 fix/ 分支，工作区干净）
git -C PowerMCP   branch --show-current && git -C PowerMCP   status --short
git -C PowerSkills branch --show-current && git -C PowerSkills status --short
```

**本次修复的提交序列**：`68fbe22`（批次 1）→ `4732694`（批次 2）→ `ef23f64`（文档）→ `c981f9f`（收口）。

---

## 下一步（按优先级）

1. **【最高】选题新颖性专查**（用 `finding-research-gaps`）—— 至今未做，是"工程能否构成论文"的 gate。
2. **【高】子项目 4：进程监管**（心跳 / 退避重启 / 熔断 / 引擎状态端点）—— 方案 §八 列为 P1 必做；
   它同时承接两项延后项：`T6-M5`（每次 `/tools/call` 都重新拉起 MCP server）与 `T6-M6`（`_STORE` 无淘汰）。
3. **【高】子项目 1：设计系统落地**（tokens → CSS 变量 / Tailwind / 5 个签名组件 / Zod 边界）。
4. **子项目 5：前端视图**（聊天面板 + 契约面板），消费 `/sessions/{sid}/events`。
   ⚠️ **开工前须知**：契约 3 在事件流上有**两个 kind**（`contract_violation` / `contract_unknown`），
   payload 同为 `ContractFinding` 同形；Zod 入站边界须**按 `kind` 分派、按 `state` 汇入双轨汇总**。
5. **opendss 挂载缺陷**（唯一真阻塞）—— 且它本身是选题素材：一个尚无解释的**接口层**失效。
6. 决定 `examples/` 是否纳入 git。

---

## 给接手 agent 的提醒

- **journal 是唯一可靠的历史来源**，对话上下文不可依赖。但 ⚠️ **`2026-09-23-research-direction-summary.md` 的 §4 引用图数字已被推翻**（144→181、「人机协同仅 2 篇」证伪），该文档顶部有更正声明，**其 §4 不可作为论据**。
- **两个子仓库停在非 main 分支是有意为之**，不要切回。
- **计划 ≠ 事实**：子项目 2 的计划已回填为"已交付实现"；子项目 3 的计划是**前置规格 + 执行记录 + 收尾章节**。读计划时先看它的状态与勘误块（⛔ 标记）。
- ⚠️ **编辑器的坑（本周期踩过，会再踩）**：
  - `gateway` 以 **editable** 装进 `PowerMCP/.venv`（`.pth` 指向 `gateway/src`）→ **`git worktree` 副本跑测试 import 的仍是原目录**，用它做隔离/变异验证**无效**。
  - **不要并行跑两个会改文件的子代理** —— 共享同一份源码，变异探针会互相污染结论。
  - **`--basetemp` 必须指向尚不存在的新目录**（见上）。
  - 修改**尚未提交**的工作时，恢复用**反向 Edit 或文件备份**，**不要** `git checkout --`。
  - 测 SSE 端点：`ASGITransport` 测不了无限流（挂死）→ 直接调 `route.endpoint()` 手动迭代 `body_iterator`。
- ⚠️ **子代理消息会丢**（本周期发生过一次：连发三条只收到一条）—— 重要裁决请合并重发，并请对方复述确认。
- `.superpowers/sdd/` 是**脚手架目录**（已 gitignore），里面的 `t*-apply.py` / 探针脚本**不是幂等的**；复用前先恢复基线或改成幂等。
- 本周期有大量「我错了并更正」的记录（我自己的报错、删错行、消息丢失、探针并发污染）—— 这些**已写进台账与报告**，是方法教训，不是残留缺陷。
