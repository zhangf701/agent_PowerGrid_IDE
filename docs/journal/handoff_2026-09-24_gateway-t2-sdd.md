---
date: 2026-09-24
type: handoff
keywords: [UI设计规范, 子项目3, 契约引擎T2, SSE审计, SDD执行]
git_branch: master
git_head: 6b2bc088951bf3f0d757a6e9627c8c120f33037a
previous_handoff: handoff_2026-09-23_powermcp-baseline.md
note: 前序 handoff 的 `git_head` 为 `N/A`（当时根目录**还不是 git 仓库**）。本周期内根目录已 `git init`，故本次可给出真实 hash；但因前序无基线 hash，**增量无法用 git 精确切分**，下面按"本会话直接产出"记录。
---

# Handoff: UI 设计规范定稿 + 子项目 3（T2/审计/SSE）计划与首两个任务交付

## 项目定位

在本地把 **PowerMCP**（16 个 MCP server / 约 250 工具）+ **PowerSkills**（21 个技能）跑通、验证能力边界，
并在此基础上做「AI/Agent × 电力系统」的选题。当前处于**从调研转向工程落地**的阶段：
选题唯一存活候选是 **MCP / agent-tool 接口标准化**（新颖性专查**仍未做**），
同时前端方案（《PowerMCP 前端设计方案》v3）与 UI 设计规范已定稿，网关开始实现。

---

## 本次增量（自 09-23 handoff 以来，**本会话直接产出**）

### 一、根目录终于有了版本控制

`d:\coding\powerMcp_Pskills` 此前**不是 git 仓库**（09-24 已发生过一次交付物被覆盖且无法恢复的事故）。
本会话给它 `git init`，并写了 `.gitignore`（忽略 `PowerMCP/` `PowerSkills/` 两个上游 clone、`GridData/` `work/` `.superpowers/`）。
现在根仓库 **38 个提交**。

### 二、《PowerMCP UI 设计规范》定稿（v1.0 → v1.2）

📄 [docs/PowerMCP_UI设计规范.md](../PowerMCP_UI设计规范.md) · 令牌真源 [design/tokens.json](../../design/tokens.json) · 校验 [tools/check_design_tokens.py](../../tools/check_design_tokens.py)

范围＝方案 §八 的 **P1**；技术栈 Vite + React + TS · shadcn/ui + Radix + Tailwind · ECharts；**双主题全做**；**不含 WCAG 章**（用户指定删除）。

**v1.1 —— 三份独立审查后的修订**（实现可行性 / 一致性 / **对抗性**；对抗审查**实际编译 TSX** 验证）
- 发现**规范在实现层重现了它要防的缺陷**：`tokens.json` 用 server id（`pypsa`）而规范表格用显示名（`PyPSA`）
  → 查表未命中 → 兜底 `0-based` → 一条**语气确定的假声明**
- 「类型约束」卖点实测兑现率约 **30%**（非首版宣称的"不可表达"）
- 已修 4 条高杠杆 + 7 处引文错 + P3 原则**改名**

**v1.2 —— 两条工程改进（用户提出）**
- **§8.4 新增 SSE 边界 Zod 运行时校验（强制）** —— 闭合 P3 逃逸表里的 `JSON.parse` 敞口
- **未知态两分 + 双轨汇总**：`structural`（引擎级、常态、**不升级**）/ `incident`（本可判定却拿不到、**必须升主徽章**）；
  主徽章承载"多严重"、次级标记 `+?N` 承载"多不确定" —— 解决**告警疲劳**（当时契约 4 长期 unknown 会淹没真正的降级）

### 三、子项目 2 的实现状态核查（已交付，非本会话实现）

📄 [docs/superpowers/plans/2026-09-24-gateway-contract-engine-t0.md](../superpowers/plans/2026-09-24-gateway-contract-engine-t0.md)

- 10/10 Task · 64/64 Step · 曾 76 单测通过；`PowerMCP/` **0 行改动**
- 实测快照：**已挂载 8/9** · 工具 117
- ⚠️ **Goal 有一条未达成**：Goal 写"拉起 9 个"，实际 **8 个**
- ❌ **opendss 无法经 mcp SDK 挂载**（裸 stdio 探针 1.86s 正常，经 SDK 握手 90/180s 超时）
  → 已立项 [opendss-sdk-mount-defect.md](../superpowers/plans/2026-09-24-opendss-sdk-mount-defect.md)，**根因未定**
- ⚠️ **计划已被"回填为已交付实现"**（提交 `3aba13c`/`75db52b`）：Task 1/5 的代码块现在是**交付版**，
  所以该计划读起来是"已经这么建了"，**不再是前置规格**
- 本会话修正了它 2 处陈旧的 `Interfaces` 声明（`describe_exception`/`split_sections` 已不在交付版里）

### 四、子项目 3 计划：契约引擎 T2 + 审计 + SSE

📄 [docs/superpowers/plans/2026-09-24-gateway-t2-audit-sse.md](../superpowers/plans/2026-09-24-gateway-t2-audit-sse.md) —— **8 个任务**

**★ 两处判据经实测重新界定（照抄方案会得到空转组件）**：

| 契约 | 方案的判据 | 实测结果 | 重新界定 |
|---|---|---|---|
| **3 参数** | 「声明的 `inputSchema` vs 实际函数签名不一致」 | **80 个工具差分 0 条** —— 两者由同一份签名生成，结构上不可能不一致 | **代理侧参数校验**：网关转发 tool call 前用 `input_schema` 校验，不符即拒绝转发（从"检视缺陷"变为"**阻止缺陷**"） |
| **4 状态映射** | 「求解器返回码 vs 引擎实际状态」，含糊且不可判定 | 改为可判定等价命题后**产出 7 条**，对照组正确 | **求解型工具若报告"成功"却从不读取引擎真实状态 → 有"失败被报成成功"风险**（`pypsa`×2 / `andes`×2 / `egret`×3；`pandapower`/`surge`/`andes` 的 `run_power_flow` 读 `converged`，**不得误报**） |

> `linearized` 的真相：**调用侧**把不存在的参数传给库函数，被 `**kwargs` 静默吞掉 —— 契约 3 想防的事发生在**调用方与库之间**。

**8 个任务**：0 会话与事件总线 · 1 NDJSON 审计 · 2 抽取共享映射表 · 3 契约 4 · 4 契约 3 校验 · 5 代理调用 · 6 SSE+端点 · 7 端到端

**预检发现并已处理**：计划原会引入**第三份** server→目录映射表（`doc_impl`/`api_version` 已有两份，
且初稿给 `hope` 写的 `HOPE/src` 与既有的 `HOPE` 不一致 —— **"同源"其实早破了**）→ 新增 Task 2 抽成单一真源。

### 五、子项目 3 执行：Task 0–3 完成

- **Task 0 会话与事件总线**：`bc555b8..a9a6aa6`，**3 轮审查 3 轮修复**后 Approved
- **Task 1 NDJSON 审计**：`e3f6150..6b2bc08`，**3 轮审查 3 轮修复**后 Approved
- **Task 2 抽取共享映射表**：`eae678d..b40fb93`，**1 轮审查 0 修复**后 Approved
  —— 派发前修正计划 3 处缺陷（陈旧验收数字 / 错误的事实陈述 / 冗余 noqa）
- **Task 3 契约 4 状态映射可信度**：`29403d9..e07deb6`，**1 轮审查 0 修复**后 Approved
  —— 派发前修正计划 **6 处**，其中 1 处经用户裁决**扩大了判据**（见下）
- 测试 **76 → 111 passed**（+1 integration deselected）

#### ★ Task 3 的关键发现：契约 4 的工具识别漏掉了整个 OpenDSS

`_tool_functions` 原本只认 `@xxx.tool` **装饰器**。实测 **OpenDSS 用 `mcp.tool()(fn)` 函数式注册，
55 个工具全部漏检**（`tools=0`），于是 `checked == 0` 报 `satisfied`，理由是
「0 个求解型工具均读取了引擎状态字段」—— 这是一条**假绿灯**（网关根本没看到 OpenDSS 的任何工具），
与 UI 规范 P5「禁止静默 fail-open」冲突。

经用户裁决：**同时识别两种形态** + **`checked == 0` 改报 `unknown / structural`**。
修正后实测覆盖 **8/8** server，risky 仍 **6** 条，仅 `genx` 报 `unknown`（识别 7 个工具、无一匹配求解型命名）。

> 另：计划原称实测 **7 条**并把 `andes.run_time_domain_simulation` 列为"无读取"——
> 实测为 **6 条**，该工具读的是 `"completed" if success else "failed"`（`success = ss.TDS.run()`）。

---

## 关键决策（仅增量）

| 决策 | 理由 |
|---|---|
| **不用 Next.js，用 Vite** | 方案 §六 形态 A 是本地单机（`powermcp ui` 绑 127.0.0.1），SSR 收益为零，成本全付 |
| **UI 规范不含 WCAG 章，但保留「颜色不单独承载信息」** | 前者用户指定删除；后者出自方案 §五.1，且是状态签名机制的载体 |
| **`incident` 必须升主徽章，`structural` 不升** | 事故的含义是"整体不可信"，降级为小标记等于把 P5 禁止的静默 fail-open 放回来 |
| **契约 3 不进 `REGISTRY`** | 它是**事件驱动**（finding 在代理层产生、进事件流与审计），不是周期性求值。硬塞进去会得到一个永远返回 `[]` 的绿灯组件 |
| **根目录 `git init`** | 09-24 已发生过交付物被覆盖且无法恢复的事故 |
| **在 `master` 上执行 SDD**（用户明确同意） | 本仓库 38 个提交均在 master；本地单人研究仓库，无协作者 |

---

## 核心文件变更（本次会话）

| 文件 | 操作 | 说明 |
|---|---|---|
| `docs/PowerMCP_UI设计规范.md` | 新增 | v1.2.0（85KB）—— UI 实现级规范 |
| `design/tokens.json` | 新增 | 令牌单一真源，88 个令牌 |
| `tools/check_design_tokens.py` | 新增 | 令牌一致性校验（含**反向测试**：注入漂移必须报错） |
| `docs/journal/2026-09-23-research-direction-summary.md` | 新增 | 选题方向总结（**§4 引用图数字已被后续复核推翻，顶部有更正声明**） |
| `docs/superpowers/plans/2026-09-24-gateway-t2-audit-sse.md` | 新增 | 子项目 3 计划（8 任务） |
| `gateway/src/powermcp_gateway/session.py` + `tests/test_session.py` | 新增 | Task 0 |
| `gateway/src/powermcp_gateway/audit.py` + `tests/test_audit.py` | 新增 | Task 1 |
| `.gitignore` | 新增 | 根仓库忽略规则 |
| `docs/journal/_index.md` | 修改 | 补 UI 规范条目 + **网关交付条目** + 引用图复核条目的更正标记 |

---

## 当前状态

- ✅ **UI 设计规范定稿**（v1.2.0，经 3 份独立审查）
- ✅ **根目录有版本控制**（38 提交，master）
- ✅ **子项目 2 已交付**（8/9 server 可挂载）
- ✅ **子项目 3 计划完成**（8 任务，含两处判据的实测重新界定）
- ✅ **子项目 3 的 Task 0–3 完成并通过审查**（111 tests）
- ⏳ **子项目 3 剩 4 个任务**（Task 4–7）
- ❌ **opendss 无法经 mcp SDK 挂载** —— 根因未定，影响契约 2/8、能力矩阵 OpenDSS 行
- ❌ **选题新颖性专查仍未做** —— 是"这些工程能否构成论文"的 gate
- ❌ Gurobi 许可过期（2026-03-31）；Ipopt 不可用
- 📋 子项目 1（设计系统落地）/ 4（进程监管）/ 5（前端视图）未开始
- 📋 **`examples/` 未被 git 跟踪** —— 它是 09-21 的交付物（4 个验证脚本），journal 与文档都引用它
- 📋 子项目 2 的计划 Goal 写"9 个 server"但实际 8 个（opendss 阻塞所致）

### ⚠️ 意外发现：本次 9 条 Important 缺陷**全部出在计划代码里**

实现者逐字照抄计划，缺陷是我的。分四类，接手时**按这四类去审剩余 6 个任务的计划代码**会省很多返工：

| 类型 | 实例 |
|---|---|
| **错误路径处理** | `close()` 吞 `QueueFull` → 订阅者永挂；`publish()` 循环中 `raise` → 半投递+重试致审计重复；`subscribe()` 缺 `_closed` 守卫 → 晚订阅挂死 |
| **静默数据丢失** | `replay()` 不 flush → 读不到刚写事件；**`splitlines()` 切碎含 U+2028 的完整合法事件** |
| **边界输入** | 撕裂多字节尾部 → `UnicodeDecodeError` 让**整个会话**审计不可读；合法 JSON 非对象 → `TypeError` |
| **断言无力的测试** | "双订阅者"测试从不创建订阅者；另两条在有 bug 的版本上**也通过** |

> **最刁的一条**：`json.dumps(ensure_ascii=False)` 不转义 ≥0x20 的 U+2028/2029/0085，
> 而 `str.splitlines()` 认它们为行边界 —— 两个各自正确的标准库行为，组合起来在"不可丢"通道上丢数据。
> **跑测试跑不出来**（写测试的人和写代码的人是同一个盲区），只能靠审查。

---

## 快速上手指令

```bash
cd d:/coding/powerMcp_Pskills

# 1. 文档中心（强制先读）
cat docs/journal/_index.md

# 2. 子项目 3 的进度台账（**接手必读**：SDD 的恢复依据）
cat .superpowers/sdd/progress.md

# 3. 计划本体
cat docs/superpowers/plans/2026-09-24-gateway-t2-audit-sse.md

# 4. 验证测试仍全绿（期望 111 passed, 1 deselected）
#    ⚠️ --basetemp 必须指向「尚不存在」的新目录。指向已存在且含 >50 条目的目录时，
#    pytest 启动的 rm_rf 会被沙箱批量删除护栏拦截 → tmp_path 测试在 setup 阶段 ERROR，
#    表现为「76 passed / 23 errors」，极易误读为代码回归。（2026-09-24 实测）
cd gateway && ../PowerMCP/.venv/Scripts/python.exe -m pytest -q -m "not integration" -p no:cacheprovider --basetemp=./.pytest_tmp/r1

# 5. 两个子仓库状态（应分别停在 fix/ 分支，工作区干净）
cd d:/coding/powerMcp_Pskills
git -C PowerMCP   branch --show-current && git -C PowerMCP   status --short
git -C PowerSkills branch --show-current && git -C PowerSkills status --short

# 6. 检查 opendss 缺陷是否有进展（当前应为 TimeoutError）
cd gateway && timeout 200 ../PowerMCP/.venv/Scripts/python.exe -c "
import asyncio,sys; sys.path.insert(0,'src')
from powermcp_gateway.config import GatewayConfig
from powermcp_gateway.inventory import build_inventory
cfg=GatewayConfig.discover()
inv=asyncio.run(build_inventory(cfg,['opendss']))
print('failures:', [(f.server, f.error[:80]) for f in inv.failures])
"
```

**SDD 续跑要点**（技能为 `superpowers:subagent-driven-development`）：
- 每个任务派**实现者子代理** → 生成审查包（`scripts/review-package BASE HEAD`）→ 派**审查者子代理** → 修复 → 复审
- 计划里的代码块是**待写代码**；修改计划后需用 `scripts/task-brief PLAN N` **重新生成任务简报**
- 计划代码若有缺陷，**实现者会逐字照抄**，缺陷会在审查阶段暴露 —— **改计划比改代码重要**

---

## 下一步（按优先级）

1. **【最高】继续子项目 3 的 Task 4–7**（SDD 流程）。台账在 `.superpowers/sdd/progress.md`，从 **Task 4（契约 3 参数校验）** 起。
   ⚠️ 派发前先做 **Pre-Flight 计划审查**：核实计划里的验收数字与事实陈述（Task 2 派发前查出 3 处缺陷，其中「既有 76」这个陈旧数字若照抄会误判回归）。
   ⚠️ 派发时**必须**带上 basetemp 环境事实（见下方"快速上手指令"第 4 条），否则测试会以「76 passed / 23 errors」的假回归形式失败。
   ⚠️ 派发前建议**先按上面四类缺陷模式审一遍 Task 5（代理，有错误路径）与 Task 6（SSE，有取消/断开路径）的计划代码** —— 它们最可能重复 Task 0 的失败模式。
   ⚠️ Task 6 已记录一条来自 Task 0 审查的设计后果：**`publish()` 对 EVIDENCE 是全有或全无，一个卡住的 SSE 客户端会阻塞整个会话的审计发布**。
2. **决定 `examples/` 是否纳入 git**（它是 09-21 的交付物，目前未跟踪）
3. **opendss 挂载缺陷**（唯一真阻塞）—— 且它本身是选题素材：一个尚无解释的**接口层**失效
4. **选题新颖性专查**（用 `finding-research-gaps`）—— 是"工程能否构成论文"的 gate，**至今未做**
5. 子项目 1（设计系统落地）/ 4（进程监管）/ 5（前端视图）

---

## 给接手 agent 的提醒

- **journal 是唯一可靠的历史来源**，对话上下文不可依赖。但 ⚠️ **`2026-09-23-research-direction-summary.md` 的 §4 引用图数字已被推翻**（144→181、
  「人机协同仅 2 篇」证伪），该文档顶部有更正声明，**其 §4 不可作为论据**。
- **两个子仓库停在非 main 分支是有意为之**，不要切回。
- **计划 ≠ 事实**：子项目 2 的计划已被回填为"已交付实现"，子项目 3 的计划是**前置规格**（尚未执行完）。读计划时先看它的状态。
- **本会话有大量"我错了并更正"的记录**（判据被证伪、docstring 拿不存在的组件当兜底、`splitlines()` 盲区…）。
  这些**已写进计划与台账**，是方法教训，不是错误残留。
- **`work/` 与 `work/cite/rerun-20260924/` 可直接复用**（分析脚本与原始 JSON）。
