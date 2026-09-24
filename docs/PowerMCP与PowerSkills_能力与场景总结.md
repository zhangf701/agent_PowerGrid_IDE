# PowerMCP 与 PowerSkills 能力与场景总结

- **编制日期**：2026-09-21
- **依据**：本项目 `docs/journal/` 全部过程日志与 `docs/logs/` 运行日志（Claude 侧安装与验证的实际记录）
- **运行环境**：`PowerMCP/.venv`（Python 3.12.6，uv 建）· powermcp 0.4.0 · powerio 0.11.3 · mcp 2.2.0 · pandapower 3.5.4 · pypsa 1.2.4 · surge-py 0.1.9
- **证据来源**：
  - [PowerMCP 仓库扫描](journal/2026-09-21-powerMcp-repo-scan.md)
  - [运行环境搭建](journal/2026-09-21-env-setup.md)
  - [核心 Server 示例脚本验证](journal/2026-09-21-mcp-examples-verification.md)
  - [PowerSkills 审计](journal/2026-09-21-powerskills-audit.md)
  - [surge 求解器配置](journal/2026-09-21-surge-solver-setup.md)
  - [示例脚本运行日志](logs/)

> **编写原则**：本文只写日志中**实测得到**的结论。凡是推断、设想或未验证项，均显式标注。不编造数据、不编造验证过程。

---

## 一、结论摘要

| 维度 | 结论 |
|---|---|
| **PowerMCP 是什么** | 面向电力系统软件的 MCP server 集合（16 个 server / 约 250 个工具），让 LLM 直接操作潮流、优化、短路、动态等专业引擎 |
| **本机开箱可用** | **4 个 server 完整可用**：pandapower(8) / PyPSA(17) / PowerIO(10) / surge(44)，合计 79 个工具，全部经运行时 `list_tools` 核验 |
| **已实测打通的能力** | ①基态潮流 ②跨格式解析与矩阵 ③PTDF/LODF 与 N-1 ④AC/DC OPF（含 LMP）—— 前三项走 MCP，第四项走 Skill 侧 Python |
| **PowerSkills 是什么** | PowerMCP 之上的技能层：11 个软件工作流技能 + 10 个资深工程师缓解手册（playbook） |
| **PowerSkills 健康度** | 21 个 skill 中，4 个在役 tool skill 里 **3 个存在阻断级缺陷**；surge 质量完好。已提 PR #8 修复 4 处 |
| **最大可用性陷阱** | 「装得上 ≠ 跑得动」：闭源/外部引擎 server 包可导入、工具可注册，但真正调用才失败；**无 mock 降级路径** |
| **对科研最直接的价值** | 可复现的自动化算例扫描 + 跨求解器交叉校验（保真度达机器精度）+ 每个结论都带具体数值 |
| **对工程最直接的价值** | 把「N-1 扫描 / 越限定位 / 缓解措施」从人工点软件变成可脚本化、可批量、可留痕的流程 |

---

## 二、PowerMCP：当前可用功能

### 2.1 可用性分级定义

本机实测把 16 个 server 分为五级，**后续所有场景判断都以这五级为准**：

| 级别 | 含义 | 判据 |
|---|---|---|
| 🟢 **可用（已验证）** | 装好即可调用，且有实际运行结果 | 运行时 `list_tools` MATCH + 至少一次真实调用成功 |
| 🟡 **可启动（未验证功能）** | 包已装、server 能起，但本次未做功能验证 | 依赖 `ok` |
| 🔵 **装得上 ≠ 跑得动** | Python 包与工具已注册，但缺外部运行时/仓库本体 | 调用时才报错 |
| ⚪ **未安装（按需可加）** | 有 pip extra，本次未装 | `doctor` 报 `missing` |
| ⛔ **需商业软件/授权** | 依赖本机闭源软件与配置路径 | `doctor` 报 vendor engine 未配置 |

### 2.2 服务器级总表（16 个 server）

工具数为静态统计值；标 ★ 者已经过**运行时 `list_tools` 核验**。

| Server | 工具数 | 本机状态 | 级别 | 前置条件 |
|---|---:|---|---|---|
| **surge** ★ | 44 | 潮流 / PTDF / LODF / N-1 / N-2 / ATC 可用；DC OPF 需 `HIGHS_LIB_DIR` | 🟢 | 系统 C 库 HiGHS（非 pip 可装）；AC OPF 另需 Ipopt/Gurobi 13 |
| **PyPSA** ★ | 17 | 潮流、优化（原生算例）、导入导出可用 | 🟢 | 需 LP/NLP 求解器在 PATH |
| **powerio** ★ | 10 | parse / emit / summarize / diagnostics / calc_matrix / to_balanced 可用 | 🟢 | 无 |
| **pandapower** ★ | 8 | 潮流、建模、转换可用；N-1 需修复分支 | 🟢 | 无 |
| **HOPE** ★ | 20 | 包与工具已就绪，缺 Julia 运行时 | 🔵 | Julia + HOPE 仓库本体 |
| **GenX** | 7 | 包已就绪（无额外新包），缺 Julia | 🔵 | Julia + GenX.jl checkout |
| **OpenDSS** | 55 | 未装 `[opendss]` extra | ⚪ | `pip install powermcp[opendss]` |
| **ANDES** | 6 | 未装 `[andes]` extra | ⚪ | `pip install powermcp[andes]` |
| **Egret** | 5 | 未装 `[egret]` extra | ⚪ | 需 `pyomo`，较重 |
| **LTSpice** | 7 | 未装 `[ltspice]` extra | ⚪ | `pip install powermcp[ltspice]` |
| **PLEXOSDB** | 31 | 未装（该包**未上 PyPI**） | ⚪ | 需手动 git 安装 |
| **PowerWorld** | 14 | 软件已装，但为 **Education 版，无 SimAuto COM** | ⛔ | 需商业授权版 + `esa` 包 |
| **PSSE** | 5 | 未配置 | ⛔ | `psse.python_lib` / `psse.bin` |
| **PSLF** | 12 | 未配置 | ⛔ | `pslf.python_lib` |
| **PowerFactory** | 22 | 未配置 | ⛔ | `powerfactory.python_path` |
| **PSCAD** | 26 | 未装 `mhi-pscad` | ⛔ | PSCAD 软件 + `[pscad-windows]` |

> **约 250 个工具**中，本机**实际可用 79 个**（4 个开源 server），占约三成；其余受 extra 未装或商业授权限制。

### 2.3 开箱可用的四大能力支柱（实测）

| 支柱 | 状态 | 路径 | 实测证据 |
|---|---|---|---|
| **① 基态潮流** | ✅ | MCP | pandapower / PyPSA / surge 三引擎结果一致 |
| **② 跨格式解析与矩阵** | ✅ | MCP（PowerIO IR） | 跨求解器保真达机器精度 |
| **③ PTDF / LODF 与 N-1** | ✅ | MCP（surge，pandapower 修复后亦可） | 46 场景扫描，带完整数值 |
| **④ AC / DC OPF 与容量规划** | ✅ | ⚠️ **Skill 侧 Python**（`runopp`/`rundcopp`），非 MCP | 三项守恒校验残差 0.0000 MW |

#### 实测数值（IEEE 39 算例）

算例规模：**39 母线 / 35 线路 / 11 变压器 / 9 机组 + 1 平衡机 / 21 负荷**

| 指标 | 基态潮流 | AC OPF | DC OPF |
|---|---:|---:|---:|
| 发电合计 (MW) | 6297.8711 | 6298.4106 | 6254.2300 |
| 网损 (MW) | 43.6411 | 44.1806 | 0.0000（模型无网损） |
| 最低电压 (pu) | 0.9820（母线 30） | 0.9820 | — |
| 最高电压 (pu) | 1.0636（母线 35） | 1.0600（触上限） | — |
| 线路最大负载率 (%) | 73.3709（线路 21） | 87.6447 | 90.16 |
| 目标函数值 | （未优化） | **41,872.30** | **41,263.94** |

- AC vs DC 目标值差 **608.36（+1.474%）**，与 AC 计及 44.18 MW 网损、DC 不计的预期一致
- 守恒律校验（三项）残差均为 **0.0000 MW**
- 节点边际电价 `lam_p` 前 5 高：母线 38 = 14.1064、母线 8 = 14.0631、母线 0 = 14.0433、母线 7 = 13.9580、母线 6 = 13.9255

#### N-1 与灵敏度（surge）

- **N-1 扫描**：46 场景 / 23 有越限 / 52 条越限；线路负载率 >100% 的故障 19 个
  - Top-1 `branch_26`（Line 21→22）**161.84%**，`flow = 958.49 MW`
  - Top-2 `branch_17`（Line 13→14）**133.50%**
  - Top-3 `branch_37`（Line 10→32）**127.59%**
  - 母线电压 <0.95 pu 的故障 2 个，最低 `min_vm_pu = 0.9361`
- **PTDF**：46 × 39，非零元 1090，稀疏度 0.3924
- **LODF**：46 × 46，非零元 763，稀疏度 0.5261，Inf/None 506（对应开断后成孤岛、LODF 无定义）
- **物理自洽性核对通过**：对角线 = −1.0；同母线并联支路互为相反数 ±1.0

#### 跨格式保真（PowerIO IR）

同一份 PowerIO IR（`pio-ir` v2）不经文件分别喂给 pandapower 与 PyPSA：

- 母线电压最大偏差 **|Δ| = 6.98e−11 pu**
- 支路有功最大偏差 **|Δ| = 2.25e−07 MW**

> **结论**：IR 往返语义保真度**达到机器精度**。这是「跨求解器交叉校验」能成立的物理基础。

### 2.4 安全控制面（正向能力）

PowerMCP 的安全设计投入高于一般开源 MCP 项目，且**已随代码交付**：

| 机制 | 说明 |
|---|---|
| **路径围笼** | 工具参数视为「受攻击者影响的输入」；先解析后比较，`..` 与符号链接逃不掉。配置项 `POWERIO_MCP_ALLOWED_ROOTS` |
| **AST 静态强制检查** | 用 `ast.parse` 断言「每个接收路径参数的 tool 真的走了围笼」——新增工具忘了走围笼，CI 直接红 |
| **PSS/E 命令黑名单** | 22 条禁止命令（启动程序、执行命令文件、Python 代码注入、加载原生库等），拦截**早于引擎启动**，由测试强制 |
| **HOPE 只读模式** | `read_only=True` 只注册读工具，且拒绝非回环地址绑定 |

### 2.5 已知缺陷与工作区状态（必须随能力一起交付）

| # | 问题 | 影响 | 当前处置 |
|---|---|---|---|
| 1 | pandapower server 的 `run_contingency_analysis` 调用已移除的 `net.deepcopy()` | 该工具在 pandapower 3.5.4 下**必然失败** | 已在本地分支 `fix/pandapower-deepcopy`（`563297a`）修复，实测 46 故障 / 45 越限；**未提 PR** |
| 2 | PyPSA 的 `optimize_network` 对 **IR 导入算例**返回 infeasible | PyPSA 的 OPF 路径在 IR 导入场景不可用 | 已排除 13 项假设，**根因未定位**；已改用 pandapower `runopp` 绕过 |
| 3 | PyPSA 1.2.4 的 `optimize()` **没有 `linearized` 参数**，实参落进 `**kwargs` 被静默忽略 | 早期「DC OPF 亦不可行」的结论**作废** | 已更正；DC 路径需另寻 |
| 4 | 两侧元件编号约定不同（pandapower 0-based 整数 vs PyPSA 1-based 字符串） | 字面键对比会**拿错物理元件**（首次误报 0.068 pu） | 已改为自动探测偏移 |
| 5 | surge 的 AC OPF 需 Ipopt 或 Gurobi 13 | 本机 Ipopt 未解决（一次不可复现的成功 + 一次进程静默崩溃）；Gurobi 为 11.0.3 且**许可已于 2026-03-31 过期** | AC OPF 走 pandapower `runopp`（不受影响） |
| 6 | 工具名跨 server 严重冲突（`load_network`/`run_power_flow`/`run_contingency_analysis` 等多处重名） | 多 server 共存时模型**无法靠名字消歧** | 编排时必须**显式指定目标 server** |
| 7 | 无任何运行时 mock/stub 降级路径 | 依赖缺失时**只有调用才失败** | 需自建「可用性预检」步骤 |

> **工作区冻结状态（勿误操作）**：`PowerMCP/` 在 `fix/pandapower-deepcopy`；`PowerSkills/` 在 `fix/pypsa-pandapower-api-drift`（PR #8），按指令冻结勿切回 `main`。

---

## 三、PowerSkills：当前可用功能

### 3.1 结构与定位

PowerSkills 是 PowerMCP 之上的**技能层**，回答三个问题：**先用哪个工具 → 升级前验证什么 → 发现真问题时按什么手册处理**。

```
PowerSkills/
├── powerskills-tool/skills/          11 个软件工作流技能
│   ├── pandapower  pypsa  surge  potpourri   ← 有对应 PowerMCP server
│   └── andes  egret  ltspice  opendss
│       powerworld  pslf  psse                ← 对应 server 未装/需授权
├── powerskills-engineering/skills/   10 个缓解手册（playbook）
└── skill-creator/                    技能编写与校验工具（不属于任一插件）
```

**渐进式披露（progressive disclosure）**是 tool skill 的核心设计：强制顺序为
**载入算例 → 检查模型 → 求解基态 → 修改 → 高级研究**，
避免直接跳到故障分析、动态仿真或投资优化。

### 3.2 11 个软件工作流技能

| Skill | 覆盖范围 | 先暴露的工具 | 后续升级到的工具 |
|---|---|---|---|
| **surge** | 输电分析、灵敏度、OPF、故障、ATC、调度 | `load_builtin_case`/`load_network`、`get_network_info`、`run_ac_power_flow` | `compute_ptdf`/`compute_lodf`、`run_dc_opf`/`run_scopf`、`run_n1_branch_contingency`、`compute_nerc_atc`、`run_scuc` |
| **pandapower** | AC 分析与筛选研究 | `load_network`/`create_empty_network`、`get_network_info`、`run_power_flow` | `run_contingency_analysis` |
| **PyPSA** | 规划、OPF、扩建研究 | `load_network`/`create_network`、网络检查 | `optimize_network`、`optimize_investment`、导入导出 |
| **potpourri** | pandapower 配网的 AC/DC 与多时段 OPF（含柔性资源与储能） | `scripts/inspect_case.py`、`scripts/solve_opf.py --list-solvers` | `--formulation dc` → `--formulation ac`、`--horizon N --battery-penetration` |
| **ANDES** | 动态安全与小信号研究 | `run_power_flow`、`get_system_info` | `run_eigenvalue_analysis`、`run_time_domain_simulation` |
| **Egret** | 市场与运行优化 | `solve_dc_opf` | `solve_ac_opf`、`solve_unit_commitment_problem` |
| **OpenDSS** | 配电网馈线研究 | `compile_opendss_file`、`solve_snapshot` | 负荷倍率、日能量表、谐波（⚠️ 见 §3.5） |
| **PSLF** | 输电潮流与故障 | `open_case`、`solve_case`、越限检查 | 拓扑/设备编辑、`run_contingency_analysis` |
| **PSSE** | PSS/E 基态与 API 引导研究 | `open_case`、`solve_case` | `lookup_psspy_command`、`search_psspy_commands`、`run_psspy_command` |
| **PowerWorld** | 稳态分析与灵敏度 | `open_case`、`run_powerflow`、结果查询 | 故障、参数修改、PTDF/LODF/雅可比 |
| **LTSpice** | 电路仿真流程 | `create_simulation_session`、`run_simulation` | `list_available_traces`、`plot_specific_traces`、GUI |

> `potpourri` 是唯一**没有 PowerMCP server** 的技能，完全靠技能自带 Python 脚本驱动。

### 3.3 10 个资深工程师缓解手册

每个手册都是「从观测到的问题出发 → 按资深工程师真实会尝试的顺序列出纠正措施」：

| Skill | 适用时机 | 典型动作 |
|---|---|---|
| **voltage-violation-mitigation** | 低压/高压、无功支撑不足、分接头用尽 | AVR / Volt-VAR 检查、并联补偿、分接头、再调度、减少输电 |
| **thermal-overload-mitigation** | 线路或变压器过载 | 再调度、拓扑切换、移相器、加固筛选 |
| **contingency-mitigation** | N-1 / N-2 越限或校正措施薄弱 | 故障前修正、校正切换、RAS 筛选、长期升级 |
| **dynamic-stability-mitigation** | 阻尼差、暂态失稳、电压恢复慢 | 模型检查、出力缓解、AVR/PSS/调速器整定、动态无功 |
| **operations-planning-mitigation** | OPF/UC 不可行、高弃电、阻塞、备用不足 | 数据清洗、简化筛选求解、增加灵活性、约束复核 |
| **convergence-failure-mitigation** | 任何工具潮流发散/不收敛 | 数据检查、孤岛与平衡机复核、分阶段放宽控制、降低压力 |
| **short-circuit-mitigation** | 短路容量超断路器额定 | 研究复核、母联分裂、串联电抗器、断路器升级 |
| **frequency-response-mitigation** | 低惯量、频率最低点差、RoCoF 高、UFLS 风险 | 调速器裕度、快速频率响应、增加惯量、下垂/死区修正 |
| **interconnection-impact-mitigation** | 新增发电/储能/大负荷并网筛查 | POI 处 N-1 筛查、SCR/弱网检查、无功要求、升级定容 |
| **der-hosting-capacity-mitigation** | 分布式电源引起电压抬升、反向潮流、保护灵敏度下降 | 逆变器 Volt-VAR/出力限制、调压器整定、保护复核、加固 |

### 3.4 跨层契约：Escalation triggers（本仓库最扎实的设计）

每个 tool skill 末尾都有一张 **Escalation triggers** 表，把**具体观测值**映射到对应的缓解手册 —— 交接由**数字**驱动而非感觉：

| tool skill 触发行 | 目标 playbook | 对齐 |
|---|---|---|
| `res_bus.vm_pu < 0.95 or > 1.05` | `voltage-violation-mitigation` | ✓ |
| `loading_percent > 100` | `thermal-overload-mitigation` | ✓ |
| `run_n1_*` 有 binding contingency | `contingency-mitigation` | ✓ |
| 潮流不收敛 | `convergence-failure-mitigation` | ✓ |

**交叉一致性实测**：引用的 mitigation skill 10 个 ↔ 实际存在的 10 个，**无悬空引用、无孤儿 skill**（PASS）。

### 3.5 技能健康度审计结果

| 严重度 | 数量 | 代表问题 |
|---|---:|---|
| 🔴 **阻断** | 3 | `optimization_analysis.py` **语法错误**（markdown 围栏当 docstring 终止符）；pandapower 的 `net.deepcopy()`；pypsa 的 `Network.status`（**求解成功却误报「未收敛」**） |
| 🟠 **事实不符** | 4 | pypsa 自带算例**潮流失效**（无法复现声称的 87%）；线路/变压器数量写反（34/12 → 实为 35/11）；loads 数不符（19 → 实为 21）；脚本与自带算例命名不兼容 |
| 🟡 **引用错误** | 1 | `opendss/SKILL.md` + README 引用的 **6 个工具名全部不存在** |
| 🔵 **规范** | 5 | ltspice 缺 escalation 表；**仓库无 CI**；版本约束前后不一致 |
| ✅ **通过** | 3 | escalation 引用完整（10/10）· 工具名有效（除 OpenDSS）· 触发条件对齐 |

**根因共性**：代码写于旧版 API + 依赖无版本上界 + **仓库无 CI** → 缺陷长期存活。

> ⚠️ **特别提示**：pypsa 的 `Network.status` 问题是**误报失败**——比崩溃更隐蔽，因为 Agent 会据此**主动放弃一条其实可行的路径**。使用 pypsa 技能时务必注意。

**✅ 已提 PR #8**（https://github.com/Power-Agent/PowerSkills/pull/8）：修复 4 处同源 API 漂移缺陷（3 文件 +39/−12），其中第 4 处是**验证驱动**发现的（修完前 3 处重跑，错误才推进到 `mremove`）。

**审计范围局限（诚实声明）**：仅覆盖 4 个在役 tool skill 的动态验证 + 层次 3 交叉一致性；其余 17 个 skill 的静态文档审计**未做**。potpourri / surge-OPF / OpenDSS 因环境依赖缺失未做动态验证（报告中已区分「skill 缺陷」与「环境限制」）。

---

## 四、使用前必读：能力边界

| 边界 | 具体内容 | 应对 |
|---|---|---|
| **装得上 ≠ 跑得动** | HOPE/GenX 缺 Julia；PowerWorld Education 版无 SimAuto COM | 开工前先跑 `powermcp doctor` + 依赖预检脚本（示例 03） |
| **MCP 路径与 Python 路径并存** | OPF 能力是 Skill 侧 Python 调用，**不是 MCP 工具调用** | 用「一致性闸门」保证结论对 MCP 侧成立 |
| **工具名冲突** | 同名工具语义/参数/单位可能不同 | 编排时**显式指定目标 server** |
| **无降级路径** | 依赖缺失只有调用时才报错 | 自建可用性探测，不要假设工具可用 |
| **静默忽略参数** | 不存在的关键字参数会落进 `**kwargs` 被忽略（如 `linearized`） | 关键参数先核对函数签名 |
| **版本敏感** | 依赖无上界 → 新版 API 漂移即失效 | 钉版本；上游修复前不要盲目升级 |
| **许可到期** | Gurobi 许可 2026-03-31 已过期，版本为 12（surge 需 13） | 依赖 Gurobi 的工作流全部不可用；`pandapower.runopp` 不受影响 |
| **PowerSkills 未全覆盖** | 17 个 skill 未做静态审计；OpenDSS 工具名全部错误 | 使用前先按 §3.5 核对 |

---

## 五、潜在科研应用场景示例

> **可行性标注**：✅ 已具备（有实测素材可直接开工）· ⚠️ 需补环境/依赖 · 🚧 需先构造数据集

### 场景 1 ✅ N-1 扫描与关键故障排序的可复现研究

- **研究问题**：如何在可复现的自动化流程下，得到带数值的 N-1 关键故障排序，并验证其物理自洽性？
- **工具链**：surge `run_n1_branch_contingency`（MCP）→ 越限明细 → 按负载率排序
- **产出**：46 场景 / 23 越限 / 52 条越限的结构化结果；Top-1 `branch_26` = 161.84%（958.49 MW）
- **素材**：✅ 已有（`examples/01`，IEEE 39）
- **注意事项**：`Islanding` 类型无支路定位信息，需容错处理而非崩溃

### 场景 2 ✅ PTDF / LODF 灵敏度分析与阻塞归因

- **研究问题**：如何用灵敏度矩阵解释特定线路的阻塞成因与相互影响？
- **工具链**：surge `compute_ptdf` / `compute_lodf`（MCP）
- **产出**：PTDF 46×39（稀疏度 0.3924）、LODF 46×46（Inf/None 506）
- **校验手段**：对角线 = −1.0；同母线并联支路互为相反数 —— **物理自洽性可作为正确性证据**
- **素材**：✅ 已有（`examples/01`）

### 场景 3 ✅ AC / DC OPF 对比与网损对目标值的影响量化

- **研究问题**：AC 与 DC 模型的目标值差异有多少来自网损？节点边际电价的空间分布如何？
- **工具链**：pandapower `runopp` / `rundcopp`（Skill 侧，含 🔒 一致性闸门）
- **产出**：AC 41,872.30 vs DC 41,263.94，差 608.36（+1.474%）；LMP 前 5 高母线
- **校验手段**：三项守恒校验残差 0.0000 MW；闸门 Δ = 0.000e+00 pu
- **素材**：✅ 已有（`examples/04`）

### 场景 4 ✅ 跨求解器一致性与算例转换保真度研究

- **研究问题**：同一算例在不同引擎间转换后，结果能保持一致到什么精度？
- **工具链**：powerio `parse` / `emit` / `summarize` / `diagnostics` / `calc_matrix`（MCP）
- **产出**：母线电压 Δ = 6.98e−11 pu、支路有功 Δ = 2.25e−07 MW（机器精度）
- **使用陷阱**：**编号约定不同**（0-based vs 1-based），必须自动探测偏移，否则张冠李戴
- **素材**：✅ 已有（`examples/02`）

### 场景 5 ✅ 潮流不收敛的成因诊断（真实研究素材）

- **研究问题**：同一份数据，为何某引擎可解而另一引擎判不可行？
- **素材**：PyPSA 自带 `case39.nc` 潮流**发散**（p0 达 1e38 量级），而 `optimize()` 返回 `('ok','optimal')` —— **LOPF 可解、PF 不可解**
- **已做的排除**（6 项，均为实测）：`pf()` 本身可用、网络连通、无零阻抗支路、容量无缺失、LOPF 可解、手动设 Slack 仍不收敛
- **已定位但不充分**：`build_case39.py:93` 的 slack 机组从未设 `control="Slack"`
- **价值**：这是一份**根因未完全定位**的真实素材，适合作「求解器鲁棒性与数据自洽性」的研究起点
- **诚实边界**：**不得**把「根因未定位」写成「已定位」

### 场景 6 ✅ 求解器容错行为对比研究

- **研究问题**：面对不自洽的数据（机组电压设定值 1.0636 > 母线上限 1.06），不同引擎的容错策略如何？
- **实测对照**：pandapower **自动放宽该母线限值**后继续求解成功；PyPSA 在同一份数据上**直接判 infeasible**
- **诚实边界**：实测把 `v_mag_pu_max` 放宽到 1.20 后 PyPSA 仍不可行 → 该异常**不是充分原因**，只能作为对照记录
- **素材**：✅ 已有（`examples/04` 日志）

### 场景 7 ✅ LLM Agent 调用电力系统工具链的可靠性研究

- **研究问题**：LLM 驱动专业电力工具时，失效模式有哪些？如何量化？
- **已有失效模式清单**（全部实测）：
  1. **误报失败**——`Network.status` 不存在 → `hasattr` 为假 → 打印「未收敛」，而求解器实际返回 `('ok','optimal')`
  2. **静默忽略参数**——不存在的 `linearized` 落进 `**kwargs`，跑的一直是 AC OPF，「DC 路径从未被真正测试」
  3. **工具名冲突**——多 server 同名工具无法靠名字消歧
  4. **无降级路径**——依赖缺失只有调用才失败
  5. **编号约定不一致**——字面键对比拿错物理元件（首次误报 0.068 pu）
- **产出**：可量化的失效模式分类 + 缓解设计（一致性闸门、可用性预检、显式 server 指定）
- **素材**：✅ 已有（5 类模式均有实测记录）

### 场景 8 🚧 批量算例扫描与数据集构建

- **研究问题**：如何把上述流程扩展为跨算例（39/118/300 节点 × 负荷水平 × 故障集）的数据集？
- **工具链**：surge N-1 + PTDF/LODF + OPF，批量循环
- **产出**：可用于机器学习（如 N-1 快速筛选代理模型）的标注数据集
- **前提**：需先构造算例集合与统一的数据契约（建议以 **PowerIO IR** 作为跨算例的统一表示）
- **素材**：🚧 需先构造数据集

### 场景 9 🚧 机组再调度 / RAS 措施的量化评估

- **研究问题**：给定 N-1 越限，各类缓解措施（再调度、拓扑切换、RAS）的效果与代价如何量化？
- **工具链**：surge N-1 定位越限 → `powerskills-engineering` 手册给出措施顺序 → 修改后重算
- **产出**：措施-效果-代价对照表
- **前提**：需构造措施实施路径与代价模型

### 场景 10 ⚠️ 配电网分布式电源承载力（DER hosting capacity）

- **研究问题**：馈线可接入多少分布式电源而不引起电压越限/反向潮流？
- **工具链**：OpenDSS（55 工具）或 potpourri 的多时段 OPF（含储能与柔性资源）
- **前提**：⚠️ OpenDSS extra **未装**；potpourri 要求 `pandapower<3.5`，与在役环境 3.5.4 **冲突**（需降级，与既定决策冲突）
- **诚实边界**：当前**不具备**直接开工条件，需先解决环境

---

## 六、潜在工程应用场景示例

> 标注同上：✅ 已具备 · ⚠️ 需补环境 · 🚧 需先构造流程

### 场景 1 ✅ 规划算例自动体检与体检报告

- **业务问题**：拿到一份新算例，如何快速判断它「健康」还是「有问题」？
- **流程**：载入 → 基态潮流 → 电压越限统计 → 过载线路统计 → N-1 扫描 → 生成报告
- **实测产出模板**（IEEE 39）：收敛 ✓ / 最低电压 0.9820（母线 30）/ 最高 1.0636（母线 35）/ 最重载 73.37%（线路 21）/ 过载 0 条 / N-1 越限 23 个
- **工程价值**：把「人工点开软件逐个看」变成**可批量、可留痕、可版本对比**的流程
- **注意**：母线 35 的 1.0636 **恰等于该处机组电压设定值**（PV 母线维持设定点），反映的是**数据设定偏高**而非求解异常 —— 报告措辞必须区分这两者

### 场景 2 ✅ 商业软件资产盘点与自动化可行性预检

- **业务问题**：本机装了商业软件，是否就能自动化调用？
- **答案**：**不能**。PowerWorld Education 版**不注册 SimAuto COM 类**，即便装上 `esa` 也无法工作
- **流程**（三级探查，示例 03）：软件是否安装 → COM/授权是否注册 → 桥接包是否就位
- **实测结论**：`[SKIP] PowerWorld COM/License unavailable，缺失项：SimAuto COM 注册, esa 包`
- **工程价值**：**避免在不可自动化的资产上浪费排期**

### 场景 3 ✅ 算例格式批量迁移

- **业务问题**：历史算例散落在 MATPOWER / PSSE raw / pandapower JSON / PyPSA nc 等格式，如何统一？
- **工具链**：powerio `parse` → IR → `emit(format=...)`（MCP）
- **实测保真**：跨引擎 Δ = 6.98e−11 pu（**转换不引入可观测误差**）
- **前提注意**：⚠️ `Package` / `model-json` / `package_json` / `study_commit` 为**已退役格式**，需重新 parse 原算例
- **已知限制**：IR → PyPSA 导入**不携带** `q_min_pu`/`q_max_pu`（无功能力限值）

### 场景 4 ✅ 检修方式编排与 N-1 校验

- **业务问题**：某线路检修期间，系统是否仍满足 N-1？
- **流程**：用 PowerIO 的 **typed edits** 把检修状态写成结构化变更（`set_branch_in_service` / `set_switch_closed` / `set_transformer_tap_ratio` 等 12 类 op）→ 导入求解器 → N-1 扫描
- **工程价值**：检修方案**先验后执行**，且变更**可审计**（`edits` 报告按应用顺序列出变更元件）
- **素材**：✅ IR 的 edits 契约已在 README 中定义并实测可用

### 场景 5 ✅ 运行成本优化与阻塞定价分析

- **业务问题**：当前运行方式下的最小成本是多少？哪些母线电价最高（阻塞位置）？
- **流程**：AC OPF（`runopp`）→ 目标值 + 机组出力 + LMP
- **实测产出**：目标 41,872.30；LMP 最高母线 38 = 14.1064；4 台机组达出力上限（gen_2/3/5/6）
- **工程价值**：机组达上限清单 + LMP 空间分布 → 直接支撑**容量规划与阻塞缓解**决策

### 场景 6 ✅ 过载/低压问题的标准化缓解流程

- **业务问题**：N-1 发现线路过载，下一步做什么？
- **流程**：越限观测 → 按 Escalation triggers 表**自动匹配** playbook → 按手册顺序尝试措施
- **实测映射**：`loading_percent > 100` → `thermal-overload-mitigation`；`vm_pu < 0.95` → `voltage-violation-mitigation`
- **工程价值**：把「资深工程师的经验顺序」固化成**可执行、可复用**的 SOP，降低对个人经验依赖
- **边界**：手册给出的是**措施顺序**，具体效果仍需重算验证

### 场景 7 ✅ 并网影响筛查（新增发电/储能/大负荷）

- **业务问题**：新增一个电源/负荷接入某节点，POI 处是否仍满足 N-1？是否需要补无功？
- **流程**：`interconnection-impact-mitigation` 手册 → POI 处 N-1 筛查 → SCR/弱网检查 → 无功要求核算 → 升级定容
- **前提**：✅ 输电侧（surge）已具备；⚠️ 若涉及弱网短路比，需商业工具（PSSE/PSLF/PowerFactory 未配置）
- **注意**：需显式指定目标 server，避免工具名冲突

### 场景 8 ⚠️ 送电能力（ATC）评估

- **业务问题**：指定断面可增加多少输电能力？
- **工具链**：surge `compute_nerc_atc`（工具已在 44 个清单中，但**本次未做功能验证**）
- **状态**：⚠️ 工具存在但未实测 —— 使用前需自行验证
- **诚实边界**：不得把「工具已注册」等同于「已可用」

### 场景 9 ⚠️ 配电网分布式电源接入评估

- **业务问题**：台区/馈线电压抬升、反向潮流、保护灵敏度下降如何处理？
- **工具链**：OpenDSS（55 工具）或 potpourri 多时段 OPF → `der-hosting-capacity-mitigation` 手册
- **状态**：⚠️ OpenDSS extra 未装；potpourri 与在役 pandapower 版本冲突
- **前提**：需先补装 extra 并解决版本冲突（会与「不降级 pandapower」的既定决策冲突，**需先决策**）

### 场景 10 ⛔ 短路容量与断路器校核

- **业务问题**：故障电流是否超断路器额定？是否需要母联分裂或串联电抗器？
- **工具链**：`short-circuit-mitigation` 手册（措施清单完整）
- **状态**：⛔ 短路计算依赖商业引擎（PSSE/PSLF/PowerFactory/PSCAD 均未配置授权）
- **工程价值**：手册本身可作为**流程规范**先落地，待工具到位后接入

---

## 七、场景落地优先级

| 优先级 | 场景 | 理由 |
|---|---|---|
| **P0（立即可做）** | 科研 1/2/3/4、工程 1/2/3/5 | 全部有现成素材 + 实测数值 + 校验手段，**零前置依赖** |
| **P1（小成本）** | 科研 5/6/7、工程 4/6/7 | 有素材，需整理为正式研究/流程文档 |
| **P2（需决策）** | 科研 8/9/10、工程 8/9/10 | 需先构造数据集，或先决策环境变更（补装 extra / 降级 pandapower / 商业授权） |

### 落地前的前置条件检查清单

1. `powermcp doctor` —— 确认目标 server 依赖 `ok`
2. 依赖预检（示例 03 模式）—— 确认外部运行时/COM/授权就位
3. 求解器可用性 —— surge 的 DC OPF 需 `HIGHS_LIB_DIR`（当前**未持久化**，仅在 shell 会话内）
4. 版本核对 —— 目标 skill 的 requirements 是否与在役版本冲突
5. 工具名核对 —— 使用前确认工具真实存在于目标 server（尤其 OpenDSS）
6. 一致性闸门 —— 凡走 Python 侧路径，必须验证网络与 MCP 侧为同一个

---

## 八、依据与可追溯性

| 本文结论 | 证据来源 |
|---|---|
| 16 server / 约 250 工具 / 工具名冲突 | 仓库扫描报告（提交 `a21ea6b`，v0.4.0） |
| 运行时 `list_tools` MATCH（8/17/44/20/10） | 环境搭建记录 §4.3（`tools/runtime_tool_census.py`） |
| IEEE 39 基态 / N-1 / PTDF / LODF 数值 | 验证报告 §2 + `logs/01_*.log` |
| IR 保真 Δ = 6.98e−11 pu | 验证报告 §3.4 + `logs/02_*.log` |
| AC/DC OPF 与 LMP | 验证报告 §3.7 + `logs/04_*.log` |
| 商业 server 探查结论 | 验证报告 §4 + `logs/03_*.log` |
| pandapower `deepcopy` 缺陷与修复 | 验证报告 §7.2（`563297a`，46 故障 / 45 越限） |
| PyPSA OPF infeasible（13 项排除） | 验证报告 §3.5 |
| surge HiGHS 可用 / Ipopt 未解决 / Gurobi 阻塞 | surge 求解器配置记录 |
| 21 skill 健康度（3/4/1/5/3） | PowerSkills 审计报告 |
| PR #8 修复 4 处 | 审计报告 §8.5 |

### 本文明确**未**做的事

- 未新增任何实验或数据 —— 全部数值均转引自上述日志
- 未验证 OpenDSS / ANDES / Egret / LTSpice / PSSE / PSLF / PowerFactory / PSCAD / PLEXOSDB / PowerWorld / HOPE / GenX 的功能
- 未做 17 个 skill 的静态文档审计
- 未定位 PyPSA OPF 在 IR 导入算例上不可行的根因
- 第五、六章的场景为**基于已验证能力的设想**，除标注「✅ 已有素材」者外，**均未实际执行**
- 附录 A 的流程为**按已验证能力编排的操作规程**，其中的提示词未逐条实跑（流程中每一步用到的工具与判定方法均有实测出处）

---

# 附录 A：完整使用流程示例 —— 从零分析 `D:\GridData` 下的新算例

## A.0 场景设定与三个硬前提

**场景**：`D:\GridData\` 下放入了一份**全新的算例**，来源与格式未知（可能是 PSS/E `.raw`、MATPOWER `.m`、pandapower `.json`、PyPSA `.nc`、OpenDSS `.dss` 或 PowerWorld `.pwb`）。要求**从零走完全流程**，最终交付一份可复核的分析报告。

**三个硬前提**（不满足则流程必然中断，必须先解决）：

| # | 前提 | 为什么 | 检查方式 |
|---|---|---|---|
| 1 | 运行环境就绪 | 无 `powermcp` 则一切无从谈起 | `powermcp --version` / `doctor` |
| 2 | **路径围笼包含 `D:\GridData`** | PowerIO 的路径策略默认约束到「服务进程启动目录」，**读不到别处的文件**；`doctor` 会报黄但不会阻止启动 | 设置 `POWERIO_MCP_ALLOWED_ROOTS` |
| 3 | 求解器就位 | surge 的 DC OPF 需系统 C 库 HiGHS（非 pip 可装） | 设 `HIGHS_LIB_DIR` 后试跑一次 |

> ⚠️ **前置条件不满足时的告警模板**（本项目约定）：
> `⚠️ 前置条件不满足：[具体问题]。修复：[具体步骤]`
> 不要静默卡死，也不要盲目重试。

> 📌 **工具名免责声明**：下文出现的工具名均取自实测日志。但本项目已有先例——OpenDSS 技能引用的 **6 个工具名全部不存在**。因此**每一步执行前都应先以 `list_tools` 的实际返回为准**（见步骤 3）。

---

## A.1 全流程地图

六个阶段、13 步，严格遵循 PowerSkills 的**渐进式披露**原则：**载入 → 检查 → 基态 → 修改 → 高级研究**。不允许跳过基态直接做故障分析。

| 阶段 | 步骤 | 目的 | 关键产出 | 风险等级 |
|---|---|---|---|---|
| **A 环境就绪** | 1–3 | 确认能跑、能读、工具名对 | 可用性清单 | 低（只读） |
| **B 算例解析** | 4–5 | 拿到可信的统一表示 + 诊断 | PowerIO IR + 诊断报告 | 低（只读） |
| **C 基态与校验** | 6–7 | 建立基准 + 跨引擎交叉验证 | 潮流结果 ×2 引擎 | 低（只读） |
| **D 灵敏度与故障** | 8–9 | 找瓶颈与关键故障 | PTDF/LODF + N-1 排序 | 中 |
| **E 缓解与优化** | 10–12 | 给出措施 + 成本最优 | 措施对照表 + OPF | 中 |
| **F 归档** | 13 | 留痕、可复现 | 分析报告 | 低 |

---

## A.2 逐步详解（含提示词）

### 步骤 1 —— 环境预检

**目的**：先确认哪些 server 真能跑，避免在不可用的路径上浪费时间。

**提示词**：

```text
先用 powermcp doctor 检查本机环境，然后给我一份表格，列三组：
(1) 依赖 ok 的 server；
(2) 报 missing 的 server 及缺失的包名；
(3) 报 vendor engine / 需要配置路径的 server。
先只做检查，不要安装任何东西、不要改配置。
另外单独告诉我 surge 的 DC OPF 是否可用（看 HIGHS_LIB_DIR 是否已设）。
```

**验收判据**：能明确区分「可用 / 装得上≠跑得动 / 需商业授权」三类。
**失败处理**：若 `doctor` 本身不可用 → 环境未装好，回到环境搭建步骤。

---

### 步骤 2 —— 打通路径围笼（最容易漏的一步）

**目的**：让 server 能读到 `D:\GridData` 下的文件。

**提示词**：

```text
我后面要分析的算例放在 D:\GridData 下。
请先确认 POWERIO_MCP_ALLOWED_ROOTS 环境变量当前是否已设置、是否包含 D:\GridData。
如果没设置或不包含，**只告诉我应该怎么设置**，先不要动系统环境变量、不要改 .gitconfig。
同时说明：不设置的话，哪些操作会失败、失败时的报错大概是什么样。
```

**验收判据**：明确知道围笼当前状态 + 是否需要设置。
**失败处理**：若报「路径不在允许根内」→ 说明围笼未包含目标目录，**这是策略问题不是 bug**。
**⚠️ 纪律**：修改系统环境变量属高危操作，**必须用户确认后**才执行。

---

### 步骤 3 —— 盘点目录 + 工具名核对（防坑双检）

**目的**：①搞清算例有哪些文件；②确认后面要用的工具名真实存在。

**提示词**：

```text
两件事，都只读不改：

第一，列出 D:\GridData 下的全部文件（含大小、扩展名、修改时间），
并判断哪些是算例文件、哪些是附属数据（如负荷曲线、故障表、地理信息）。
如果有多个候选算例，按「最可能是主算例」排序并说明理由，先不要解析。

第二，对 powerio、pandapower、pypsa、surge 四个 server 各调一次 list_tools，
把工具名清单完整给我。我要用这份清单核对我后面要调的工具名是否真实存在。
```

**验收判据**：拿到文件清单 + 四份真实工具名清单。
**为什么必须做**：工具名跨 server 严重冲突（`load_network`/`run_power_flow`/`run_contingency_analysis` 等多处重名），且已有 OpenDSS 技能 6 个工具名全部失效的先例。

---

### 步骤 4 —— 解析为 PowerIO IR（统一数据契约）

**目的**：把任意格式的算例转成**跨 server 通用的统一表示**，后续所有引擎都从这一份 IR 出发，避免「各引擎各读各的格式」导致结论不可比。

**提示词**：

```text
用 powerio server 的 parse 工具解析 D:\GridData\<第 3 步确定的主算例文件>。
要求：
1) 把返回的 powerio_ir 完整保存下来（后面每一步都要复用同一份，不要重新解析）；
2) 告诉我返回的 schema 与 version；
3) 告诉我 value_type 是什么（BalancedNetwork 还是多导体/其它）；
4) 如果返回里带 diagnostics，先原样贴出来。

先不要做任何求解。
```

**验收判据**：拿到一份 `pio-ir` v2 的 IR 文本，且 `value_type` 明确。
**失败处理**：
- 若是**多导体网络**（配电网）→ 平衡求解器会拒绝，需先调 `to_balanced_report` / `to_balanced` 做降维，**并注意**：保留某元件 ≠ 所选求解器能建模它。
- 若是**已退役格式**（`Package` / `model-json` / `package_json` / `study_commit`）→ 需重新 parse 原始算例。

---

### 步骤 5 —— 摘要与诊断（先判断算例是否可用）

**目的**：在花时间跑潮流之前，先看这份算例**本身有没有问题**。这是最省钱的一步。

**提示词**：

```text
对刚才那份 IR 调 summarize 和 diagnostics，给我：

A. 摘要：母线数 / 支路数 / 机组数 / 负荷数、连通分量个数、参考母线、是否辐射状。
B. 诊断：逐条列出全部 diagnostics 记录（code、severity、target、suggested action）。

然后给结论：
- 如果 severity 里有 error 级别的问题，**停下来**，先告诉我要不要继续；
- 如果只有 warning，继续，但把 warning 记下来，后面解释结果时要带上。
```

**验收判据**：知道算例规模、拓扑特征、以及是否存在必须先修的问题。
**为什么这一步重要**：后面所有数值结论都建立在「算例可信」之上。算例数据自身不自洽是有先例的——IEEE 39 算例里机组 5 的电压设定值 1.0636 **高于**该母线上限 1.06。

---

### 步骤 6 —— 基态潮流（建立基准）

**目的**：得到**基准工况**。后面所有的「越限」「恶化」都是相对这一基准而言的。

**提示词**：

```text
把这份 IR 用 pandapower 的 load_network_from_json 导入，然后 run_power_flow。
报告以下内容，全部要给具体数值和元件编号：

1) 是否收敛；
2) 最低电压：数值 + 母线编号；最高电压：数值 + 母线编号；
3) 最重载线路：编号 + 负载率（%）；
4) 低于 0.95 pu 的母线有几个、分别是哪些；
5) 高于 1.05 pu 的母线有几个、分别是哪些；
6) 过载（>100%）的支路有几个。

最后做一个守恒校验：总发电 -（总负荷 + 网损）= ？给出残差数值。
```

**验收判据**：
- 收敛 = True
- 守恒残差 ≈ 0（IEEE 39 实测为 **0.0000 MW**）
- 电压、负载率均有具体数值和元件编号（**不接受「有若干越限」这种模糊结论**）

**⚠️ 解释纪律**：若最高电压**恰等于某台机组的电压设定值**，那是 PV 母线在维持设定点，反映的是**算例设定偏高**，**不是求解异常**。报告中必须区分这两者。

---

### 步骤 7 —— 跨引擎交叉校验（科研级必做）

**目的**：用第二个独立引擎复算，证明结果**不依赖于某一个求解器的实现**。

**提示词**：

```text
用同一份 IR（不要重新解析）调 pypsa 的 import_case_from_json 导入，再跑一次潮流。

然后做逐项对比：
- 母线电压 vm_pu：两边逐个母线比
- 支路首端有功：两边逐条支路比

⚠️ 关键：两侧的元件编号约定不同（pandapower 用 0-based 整数索引，
pypsa 沿用 IR 里的 1-based 标识）。请**自动探测编号偏移**，
搜索使最大残差最小的那个偏移量，**不要按字面键直接对比**——
按字面比会拿不同的物理元件做对比，得出假差异。

给出：最大偏差、平均偏差、以及是否落在 1e-06 pu 的判定阈值内。
```

**验收判据**：
- 编号偏移探测结果明确（IEEE 39 实测为「pypsa 键 = pandapower 键 + 1」）
- 最大偏差落在机器精度量级（实测 **电压 6.98e−11 pu / 有功 2.25e−07 MW**）
- **若出现 0.0x pu 量级的「差异」，先怀疑编号错位，而不是物理差异**

**这一步的价值**：IR 往返保真度得到实测证实，后续所有跨引擎结论才有基础。

---

### 步骤 8 —— PTDF / LODF 灵敏度矩阵

**目的**：从「单点结果」升级到「结构性认识」——哪些线路对哪些注入最敏感。

**提示词**：

```text
用 surge 对这份算例计算 PTDF 和 LODF。

给我：
1) 两个矩阵的维度、非零元个数、稀疏度；
2) PTDF 里对几个关键母线注入最敏感的前几条支路；
3) LODF 里的 Inf / None 有多少个，并解释它们对应什么物理场景。

然后做**物理自洽性核对**（这是正确性的证据，不是可选步骤）：
- LODF 对角线是否 = -1.0？为什么？
- 同一对母线之间的并联支路，LODF 是否互为相反数？
```

**验收判据**：
- LODF 对角线 = −1.0（开断自身即全失）
- 同母线并联支路互为相反数（如 IEEE 39 的 `1->2` 与 `1->39` 为 ±1.0）
- Inf/None 有物理解释（实测 506 个，对应开断后成孤岛、LODF 无定义）

> **为什么自洽性核对重要**：矩阵算错了也能给出「漂亮的数字」。只有物理约束能证伪它。

---

### 步骤 9 —— N-1 故障扫描（找关键故障）

**目的**：找出**最危险的单一元件失效**，并给出可排序、可定位的数值。

**提示词**：

```text
用 surge 的 run_n1_branch_contingency 做 N-1 扫描。

给我：
1) 总共扫描了多少个场景、多少个场景出现越限、越限条目总数；
2) 线路负载率 >100% 的故障有几个，按最大负载率**降序**排前 5，
   每个都要给出：断号、支路两端母线、最大负载率、对应 flow (MW)；
3) 母线电压 <0.95 pu 的故障有几个，最低电压是多少、在哪条支路；
4) 越限类型有哪些（ThermalOverload / VoltageHigh / Islanding 等）。

注意：Islanding 类型可能没有支路定位信息，遇到时请容错标注，不要报错退出。
```

**验收判据**：Top-N 故障有**断号 + 数值**（不接受「有几个故障越限」这种不可排序的结论）。

**实测参照**（IEEE 39）：46 场景 / 23 越限 / 52 条越限；Top-1 `branch_26`（Line 21→22）**161.84%**、`flow = 958.49 MW`；低电压故障 2 个，最低 **0.9361 pu**。

**失败处理**：若 pandapower 的 `run_contingency_analysis` 报 `'pandapowerNet' object has no attribute 'deepcopy'` → 说明当前不在修复分支上，**改用 surge**（surge 的输出还更完整，自带 `loading_pct` / `flow_mw` / `min_vm_pu`）。

---

### 步骤 10 —— 越限 → 自动匹配缓解手册

**目的**：把「发现问题」推进到「知道下一步做什么」。这是 PowerSkills 的核心价值。

**提示词**：

```text
根据第 6 步和第 9 步的越限结果，对照 powerskills-tool 技能里的 Escalation triggers 表，
告诉我每个越限应该匹配哪个 powerskills-engineering 缓解手册，并说明匹配依据是哪条具体规则。

预期映射：
- 母线电压 < 0.95 或 > 1.05 pu  → voltage-violation-mitigation
- 支路负载率 > 100%              → thermal-overload-mitigation
- N-1 有 binding contingency      → contingency-mitigation
- 潮流不收敛                      → convergence-failure-mitigation

然后**按手册给出的顺序**列出建议措施（先试什么、再试什么），
并说明每一项措施需要改动哪些元件、预期改善哪个指标。
先只给方案，不要动手改算例。
```

**验收判据**：每个越限都映射到具体手册 + 具体规则；措施**有先后顺序**（而不是一堆并列选项）。

---

### 步骤 11 —— 实施缓解措施并复算（用结构化变更）

**目的**：验证措施是否真的有效，且**变更过程可审计**。

**提示词**：

```text
我要试验第 10 步里的第 <N> 项措施。

请用 PowerIO 的 typed edits 把这次改动写成结构化的变更列表
（例如 set_branch_in_service / set_switch_closed / set_transformer_tap_ratio /
set_generator_active_power 等），而不是直接改文件。

要求：
1) 先告诉我你打算下发的 edits 列表（op + 目标元件 + 新值），等我确认；
2) 确认后再执行导入，并报告返回的 edits 报告（按应用顺序列出被改动的元件）；
3) 在同一份新网络上重跑基态潮流 + N-1 扫描；
4) 给出「措施前 vs 措施后」对照表：最重载支路、最低电压、越限故障数。

注意：edits 是整批先校验、再按顺序应用的，请确认列表本身没有内部矛盾。
```

**验收判据**：
- 返回的 `edits` 报告按应用顺序列出变更元件（**可审计**）
- 措施前后对照表有具体数值
- 若措施无效 → **如实报告无效**，不要换个说法让它看起来有效

---

### 步骤 12 —— 运行优化（AC / DC OPF，含一致性闸门）

**目的**：给出成本最优的运行方式，以及阻塞位置的定价信号。

**提示词**：

```text
现在做最优潮流，AC 和 DC 各做一次。

⚠️ 路径说明：本机 pandapower server **没有 OPF 工具**，PyPSA 的 optimize_network
对 IR 导入的算例返回 infeasible（成因未定位）。所以这里走 **pandapower 的
runopp / rundcopp**，这是 **Python 侧调用、不是 MCP 工具调用**。

为保证结论对 MCP 侧成立，请先做一致性闸门：
1) 从**与 MCP 相同的那个算例文件**本地重建网络；
2) 逐母线比对基态潮流电压与第 6 步的 MCP 结果；
3) 若最大偏差 > 1e-06 pu，**中止**，不要在来历不明的网络上做优化。

闸门通过后给我：
- AC OPF：目标函数值、网损、电压范围、线路最大负载率；
- DC OPF：目标函数值、线路最大负载率；
- 两者目标值之差及其占 AC 的比例，并解释这个差是否合理；
- 达到出力上限的机组清单（这是容量规划的直接依据）；
- 节点边际电价 lam_p 最高的前 5 个母线。

最后做守恒校验：AC 的「发电 -（负荷 + 网损）」、DC 的「发电 - 负荷」，给出残差。
```

**验收判据**：
- 闸门偏差 ≤ 1e-06 pu（实测 **0.000e+00 pu**）
- 三项守恒残差 ≈ 0（实测 **0.0000 MW**）
- AC 目标值 > DC 目标值（因为 AC 计及网损），差值可解释

**实测参照**（IEEE 39）：AC 目标 **41,872.30** / 网损 44.18 MW / 最高电压 1.0600；DC 目标 **41,263.94**；差 608.36（**+1.474%**）；LMP 最高母线 38 = 14.1064。

**失败处理**：若 pandapower 打印 `gen vm_pu > bus max_vm_pu for gens [5]` → 这是**算例数据自身不自洽**，pandapower 会自动放宽限值继续求解。要如实说明这是容错行为，**不是求解错误**。

---

### 步骤 13 —— 归档与报告

**目的**：让结论**可复核、可复现**。

**提示词**：

```text
把整个分析过程整理成一份报告，必须包含：

1) 算例档案：文件名、格式、母线/支路/机组/负荷数、IR 的 schema 与 version；
2) 环境档案：powermcp / powerio / pandapower / pypsa / surge 的版本号；
3) 基态结果：收敛状态、电压极值及其母线、最重载线路、守恒残差；
4) 交叉校验：两引擎对比的最大偏差、编号偏移探测结果；
5) 灵敏度：PTDF/LODF 维度与稀疏度、自洽性核对结论；
6) N-1 结果：扫描规模、Top-5 关键故障（含断号与数值）、低压故障清单；
7) 缓解措施：匹配的手册、措施前后对照表；
8) OPF：AC/DC 目标值、LMP 前列母线、达上限机组、守恒校验；
9) **诚实声明**：本次哪些步骤实测通过、哪些失败或被跳过、哪些结论是推断。

⚠️ 报告中每一条数值结论都要能追溯到具体的工具调用。
如果某一步没做成，就写「未做」并说明原因，不要用推测填充。
```

**验收判据**：报告里的每个数字都能对上前面步骤的输出；未完成项被显式标注。

---

## A.3 懒人版：一次跑完的总提示词

若不想分步交互，可把下面这段整体发出（**但不建议**——分步能及时止损）：

```text
请对 D:\GridData 下的算例做一次完整分析，严格按下面的顺序，每完成一步先向我汇报再继续：

1. powermcp doctor 环境预检（只读，不安装任何东西）
2. 确认 POWERIO_MCP_ALLOWED_ROOTS 是否包含 D:\GridData（只报告，不改系统变量）
3. 列出 GridData 全部文件 + 对 powerio/pandapower/pypsa/surge 各调一次 list_tools 核对工具名
4. 用 powerio parse 解析主算例，保存 IR，报告 schema/version/value_type
5. 对 IR 调 summarize + diagnostics，有 error 就停下问我
6. 导入 pandapower 跑基态潮流，给电压极值/最重载/越限统计 + 守恒校验
7. 用同一份 IR 导入 pypsa 复算，自动探测编号偏移后逐项对比（阈值 1e-06 pu）
8. surge 算 PTDF/LODF，做对角线 = -1 的物理自洽性核对
9. surge 做 N-1 扫描，给 Top-5 关键故障（断号 + 负载率 + flow）
10. 按 Escalation triggers 表匹配缓解手册，按手册顺序给措施方案（先不改算例）
11. 实施第 1 项措施（用 typed edits），复算并给前后对照表
12. 走 pandapower runopp/rundcopp 做 AC/DC OPF，先过一致性闸门（1e-06 pu）
13. 汇总报告，含环境档案、全部数值、以及「未做/失败/推断」的诚实声明

纪律要求：
- 不许跳过基态潮流直接做故障分析
- 不许在编号未对齐的情况下跨引擎对比
- 不许把推断写成实测结论
- 每一步都要有具体数值和元件编号，不接受模糊表述
- 遇到依赖缺失，报告缺什么、怎么补，不要盲目重试
```

---

## A.4 中途失败的对照排查表

流程中断时，先查这张表——**每一种都是本项目已实测到的真实失效模式**：

| 症状 | 真实成因 | 处置 |
|---|---|---|
| `'pandapowerNet' object has no attribute 'deepcopy'` | pandapower 3.5.4 已移除该方法；上游 `panda_mcp.py` 未适配 | 换用 surge 做 N-1（输出更完整）；或确认在 `fix/pandapower-deepcopy` 分支上 |
| 脚本打印「未收敛」，但求解器返回 `('ok','optimal')` | PyPSA 1.2.4 已移除 `Network.status`，`hasattr` 为假 → **误报失败** | 改从 `optimize()` 返回值取状态；**不要据此放弃可行路径** |
| 传了 `linearized=True` 但结果像 AC OPF | PyPSA 无此参数，实参落进 `**kwargs` 被**静默忽略** | 关键参数先核对函数签名，别信「参数被接受」 |
| 跨引擎对比出现 0.0x pu 的「差异」 | 两侧编号约定不同（0-based vs 1-based），字面键对比拿错元件 | 自动探测编号偏移，不要硬编码 |
| `No LP solver found — install HiGHS` | surge 需系统 C 库，`pip install highspy` **不提供**共享库 | 设 `HIGHS_LIB_DIR` 指向含 `highs.dll` 的目录 |
| `No AC-OPF NLP solver found` | surge 的 AC OPF 需 Ipopt 或 Gurobi 13 | AC OPF 改走 pandapower `runopp`（不受影响） |
| `Gurobi 13 not found` | 本机为 11.0.3，且许可已于 2026-03-31 过期 | 依赖 Gurobi 的路径全部不可用，改用内建求解器 |
| 工具调用报「找不到工具」 | 工具名不存在（OpenDSS 技能已有 6 个全部失效的先例） | 以 `list_tools` 实际返回为准 |
| 读文件被拒 | 路径不在 `POWERIO_MCP_ALLOWED_ROOTS` 围笼内 | 这是策略问题，需显式配置允许根 |
| 工具调用报缺 Julia / COM | HOPE/GenX 缺 Julia；PowerWorld Education 版不注册 SimAuto COM | 属环境限制，补运行时或换商业授权版 |
| 配电网算例被平衡求解器拒绝 | 多导体网络需先降维 | 调 `to_balanced_report` / `to_balanced` |

---

## A.5 本附录的诚实边界

| 项 | 说明 |
|---|---|
| 流程编排 | 按**已验证能力**编排，顺序遵循 PowerSkills 的渐进式披露原则 |
| 工具与判定方法 | 每一步用到的工具、阈值（1e-06 pu）、校验方式（守恒、对角线 = −1）**均有实测出处** |
| 提示词 | **未逐条实跑** —— 它们是操作模板，不是已验证的对话记录 |
| 实测数值 | 文中的 IEEE 39 数值全部转引自 `docs/logs/`，可逐项复核 |
| 未覆盖 | OpenDSS / ANDES / Egret / LTSpice / 商业 server 的分析流程**未纳入**（对应 server 本机不可用） |

---

*本文档为能力与场景总结，不替代 `docs/` 下的两份《实践指南》。若需 PDF 版本，请先确认生成方式（本项目禁止使用 pandoc 生成 PDF）。*
