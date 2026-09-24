---
date: 2026-09-23
type: handoff
keywords: [PowerMCP, PowerSkills, 环境搭建, 文献调研, 技能交付]
git_branch: N/A（根目录非 git 仓库，两个子仓库见下）
git_head: N/A
previous_handoff: null
sub_repos:
  PowerMCP:   {branch: fix/pandapower-deepcopy,   head: 563297ad489fc8f4d79494e9f6866f16bb8476db, uncommitted: 0}
  PowerSkills: {branch: fix/pypsa-pandapower-api-drift, head: 920b35a42c9fb89ec9ac41c4986e10f92b36a0b4, uncommitted: 0}
---

# Handoff: PowerMCP/PowerSkills 基线 —— 环境、验证、审计、技能

> **这是首次交接（基线文档）**，`previous_handoff: null`。因此"本次增量"记录的是**全量历史**，
> 后续交接只记增量。

## 项目定位

在本地建立 PowerMCP（电力软件 MCP server 集合）+ PowerSkills（21 个 Agent 技能）的可用环境，
验证其能力边界，并在此基础上寻找「AI/LLM/Agent × 电力系统」交叉领域的可做研究方向。

**资源位置**：
- 项目根：`d:\coding\powerMcp_Pskills`（**非 git 仓库**）
- `PowerMCP/` — 上游仓库克隆，含 `.venv` 隔离环境
- `PowerSkills/` — 上游仓库克隆
- `GridData/` — 5 套 CSEE 中文标准算例 + MATPOWER 算例集
- `examples/` — 4 个自包含验证脚本
- `docs/journal/` — **技术文档中心**（新对话应先读 `_index.md`）
- `work/` — 中间产物（语料库、分析脚本、原始结果）

---

## 本次增量（自项目开始，无前序 handoff）

### 一、仓库扫描与理解

- **PowerMCP**：16 个 server / 约 250 个工具；`powermcp/` 是声明式胶水层（`registry.py` 为单一真源）；
  `PowerIO IR`（`pio-ir` v2）是跨 server 交换格式
- ⚠️ **两种工具注册风格并存**（装饰器 vs `mcp.tool()(func)`），只扫 `@mcp.tool` 会漏掉 OpenDSS(55) 与 PSCAD(26)
- ⚠️ **工具名跨 server 冲突严重**（`load_network`/`add_bus`/`run_contingency_analysis` 等重名）
- 产出：[2026-09-21-powerMcp-repo-scan.md](2026-09-21-powerMcp-repo-scan.md)

### 二、环境搭建

- `PowerMCP/.venv`（Python 3.12.6，uv 建）装 **核心 + `[hope,surge]`**
- 未触碰任何 conda 环境、系统变量或 `.gitconfig`
- ⚠️ **本机默认 `python` 是 3.9.23，低于要求的 3.10** —— 必须用 `.venv`
- 产出：[2026-09-21-env-setup.md](2026-09-21-env-setup.md)

### 三、示例验证（4 个脚本，全部 EXIT=0）

| 脚本 | 内容 |
|---|---|
| `examples/01` | pandapower + surge 全流程（IEEE 39） |
| `examples/02` | PowerIO IR 跨格式转换 |
| `examples/03` | 商业 server 优雅探查 |
| `examples/04` | AC/DC OPF（pandapower `runopp`/`rundcopp`） |

**关键实测结论**：
- ⚠️ **PowerMCP 真实缺陷**：`panda_mcp.py:180,191` 的 `net.deepcopy()` 在 pandapower 3.x 已移除
- ✅ **IR 往返保真**：同 IR 经 pandapower 与 PyPSA，**Δ = 6.98e-11 pu**
- ⚠️ **PyPSA OPF 对 IR 导入算例 infeasible**，成因经 13 项假设排查**仍未定位**
- 产出：[2026-09-21-mcp-examples-verification.md](2026-09-21-mcp-examples-verification.md)

### 四、PowerSkills 审计 + PR

审计 4 个在役 skill 的 20 个脚本，发现 **3 个阻断级问题**：

| 缺陷 | 位置 |
|---|---|
| **语法错误**（markdown 围栏写进 docstring） | `pypsa/optimization_analysis.py:18` |
| `net.deepcopy()` 已移除 | `pandapower/contingency_analysis.py:56` |
| `Network.status` 已移除 → **误报"未收敛"** | `pypsa/contingency_analysis.py:117` |
| `mremove()` 已移除（修复第 3 项时暴露） | 同上 :93,104 |

**已提 PR**：https://github.com/Power-Agent/PowerSkills/pull/8 （**OPEN**，经 fork `zhangf701/PowerSkills` 提交）
- 产出：[2026-09-21-powerskills-audit.md](2026-09-21-powerskills-audit.md)

### 五、surge 求解器配置

- 新建 conda 专用环境 `powersolvers`（未动 `base`）
- ✅ **HiGHS 可用**：设 `HIGHS_LIB_DIR` 后 `solve_dc_opf` 3/3 稳定通过
- ❌ **Ipopt 未能解决**（试遍 7 种组合；有一次不可复现的成功 + 一次进程静默崩溃）
- ⚠️ **Gurobi 许可已过期**（`C:\gurobi\gurobi.lic`，`EXPIRATION=2026-03-31`），且版本为 12，而 surge 要 13
- 产出：[2026-09-21-surge-solver-setup.md](2026-09-21-surge-solver-setup.md)

### 六、case30 全流程验证

- IR 解析（`pio-ir` v2 / `BalancedNetwork` / **零诊断**）
- 跨引擎潮对比：**Δ 8.84e-11 pu**，编号偏移 **+1**
- PTDF / LODF + 三条独立证据链重合（图论桥 ≡ 对角 None 列 ≡ N-1 Islanding）
- N-1：**41 场景 / 32 越限 / 56 条**
- ⚠️ **两个判据陷阱**：编号约定（字面比对放大偏差 **3.1 亿倍**）；过载用 **MVA**（用 MW 会把 142% 看成 98%）
- 缓解结论：**只有加固 8–28 可行**
- 产出：[2026-09-23-case30-and-gap-research.md](2026-09-23-case30-and-gap-research.md)

### 七、文献空白调研（七轮）+ 技能交付

**六条候选全被推翻**：不确定性量化 / 静默失效 / 技能组合形式化 / 大网架可扩展性 / 人机协同 / 安全实证

**唯一存活：MCP 接口标准化** —— 有权威综述（Frontiers in AI 2026）明确背书 + 引用图验证

**交付技能**：`C:\Users\Z\.claude\skills\finding-research-gaps\`（全局，**未提交任何仓库**）
- RED-GREEN-REFACTOR 完整走完
- ⚠️ 其**限流保护路径未在未限流状态下端到端验证**

---

## 关键决策（仅增量）

| 决策 | 理由 |
|---|---|
| **N-1 走 surge，不改上游源码**（后修订为修复 `panda_mcp.py`） | 见 [mcp-examples-verification §7](../journal/2026-09-21-mcp-examples-verification.md) |
| **OPF 走 pandapower `runopp`**（Skill 侧 Python，非 MCP 调用） | 两条 MCP 路径均不可用；设一致性闸门保证结论对 MCP 侧成立 |
| **PowerMCP 修复放本地分支，不提 PR** | 用户明确只要本地修复 |
| **PowerSkills 修复提 PR** | 已提交 #8 |
| **文献检索改用「引文链 + 引用图」** | 关键词检索七轮错六轮 |
| **技能不提交仓库** | 用户指示「先正常使用即可」 |

---

## 核心文件变更（本次全部为新增）

| 文件 | 操作 | 说明 |
|---|---|---|
| `docs/journal/*.md`（7 个 + `_index.md`） | 新增 | 全部技术文档 |
| `examples/01~04_*.py` | 新增 | 4 个验证脚本 |
| `tools/{runtime_tool_census,dump_tool_schemas,test_patch_propagation}.py` | 新增 | 核验工具 |
| `work/{case30,fw,cite,lit}/` | 新增 | 中间产物与分析管线 |
| `C:\Users\Z\.claude\skills\finding-research-gaps\` | 新增 | 交付技能（全局） |
| `PowerMCP/pandapower/panda_mcp.py` | **修改** | 本地分支 `fix/pandapower-deepcopy` @ `563297a` |
| `PowerSkills/powerskills-tool/skills/{pandapower,pypsa}/scripts/*.py` | **修改** | PR #8 分支 @ `920b35a` |

---

## 当前状态

- ✅ 环境可用（`.venv`，核心 + `[hope,surge]`）
- ✅ 4 个示例脚本全部跑通
- ✅ PowerSkills 审计完成，PR #8 已提
- ✅ case30 全流程验证完成
- ✅ journal 已同步至 2026-09-23
- ⏳ **PR #8 等待维护者响应**（OPEN）
- ⏳ **`finding-research-gaps` 技能的限流保护未在未限流状态验证**
- ❌ **PyPSA OPF on IR-imported case 不可行，成因未定位**（13 项假设已排除）
- ❌ **Ipopt 不可用** → surge 的 AC-OPF 用不了
- ❌ **Gurobi 许可过期**（影响所有依赖 Gurobi 的工作流，**未逐一排查**）
- ❌ **CSEE-FS（BPA 格式）无法用 PowerIO 解析**（缺格式支持 + GBK 编码）
- 📋 **MCP 接口方向的下一步未定** ← **最重要**
- 📋 case30 的 21–22 走廊未做独立灵敏度分析
- 📋 两个 git 分支仍在非 main 上（**勿擅自切回**，见记忆 `powerskills-branch-frozen` / `powermcp-local-fix-branch`）

---

## 快速上手指令

```bash
cd d:/coding/powerMcp_Pskills

# 1. 先读文档中心（强制）
cat docs/journal/_index.md

# 2. 验证两个子仓库状态（应分别停在 fix/ 分支，工作区干净）
git -C PowerMCP   branch --show-current && git -C PowerMCP   status --short
git -C PowerSkills branch --show-current && git -C PowerSkills status --short

# 3. 验证环境
./PowerMCP/.venv/Scripts/powermcp.exe --version   # 期望 0.4.0
./PowerMCP/.venv/Scripts/powermcp.exe doctor

# 4. 冒烟测试（约 1 分钟，用最小算例）
PYTHONIOENCODING=utf-8 ./PowerMCP/.venv/Scripts/python.exe -c "
import os; os.environ['POWERIO_MCP_ALLOWED_ROOTS']=os.getcwd()
import surge; net=surge.load_builtin_case('case9')
print('surge OK:', net is not None)
"

# 5. 检查 PR #8 是否已合并
gh pr view 8 --repo Power-Agent/PowerSkills --json state
```

---

## 下一步（按优先级）

1. **【最高】确定 MCP 接口方向的下一步** —— 七轮筛选后唯一存活的候选。
   可考虑把问题表述为「面向工程软件的 agent-tool 接口标准应满足哪些可形式化验证的性质」，
   但**动手前必须先做新颖性专查**（用 `finding-research-gaps` 技能）
2. 检查 PR #8 状态；若维护者有反馈则响应
3. 决定是否排查 Gurobi 许可过期对**其他项目**的影响（本机多个 conda 环境可能依赖）
4. 排查 PyPSA OPF 在 IR 导入算例上不可行的成因（降级为可选）
5. CSEE-FS 的 BPA → RAW/MATPOWER 转换路径调研（若要用那 5 套中文算例）

---

## 给接手 agent 的提醒

- **journal 是唯一可靠的历史来源** —— 本次工作跨越多个会话，对话上下文不可依赖
- **两个子仓库停在非 main 分支是有意为之**，不要切回
- **本会话有大量"我错了并更正"的记录**（七轮里六轮误判、语料 1/3 误标、限流误判…）。
  这些更正**已写进各文档**，读文档时会看到 —— 它们是方法教训，不是错误残留
- **`work/` 下的脚本可直接复用**（`extract.py` / `aggregate.py` / `openalex.py` / `arxiv_gaps.py`）
