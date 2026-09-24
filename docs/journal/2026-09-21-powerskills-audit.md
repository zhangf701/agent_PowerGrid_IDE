# PowerSkills 审计报告（层次 1 动态 + 层次 3 交叉一致性）

- **日期**：2026-09-21
- **审计对象**：https://github.com/Power-Agent/PowerSkills （提交时 `main`，`pushedAt 2026-08-22`）
- **本地路径**：`d:/coding/powerMcp_Pskills/PowerSkills`（shallow clone，depth 30）
- **审计范围**（按用户指定）：
  - **层次 1**：4 个在役 tool skill（pandapower / pypsa / surge / potpourri）的 **20 个 Python 脚本**动态运行 + SKILL.md 声称与实测核对
  - **层次 3**：交叉一致性（escalation 引用、工具名真实性、触发条件对齐）
  - **未做**：层次 2（其余 17 个 skill 的静态文档审计）
- **环境**：`PowerMCP/.venv`，pandapower 3.5.4 · pypsa 1.2.4 · surge-py 0.1.9

---

## 〇、结论摘要

**21 个 skill 中，4 个在役 skill 里有 3 个的脚本或文档存在阻断级问题**；surge 是唯一质量完好的。

| 严重度 | 数量 | 类别 |
|---|---:|---|
| 🔴 阻断 | **3** | 脚本无法运行（语法错误 / 已移除的 API） |
| 🟠 事实不符 | **4** | SKILL.md 声称的数字或行为与实测不符 |
| 🟡 引用错误 | **1** | 6 个工具名全部不存在 |
| 🔵 规范/结构 | **5** | 缺 escalation 表、版本未钉、无 CI 等 |
| ✅ 通过 | **3** | 3a / 3b / 3c 三项交叉检查 |

**根因共性**：所有 🔴 与部分 🟠 都源于同一个模式——**代码写于旧版 API，依赖无版本上界，仓库无 CI**。

---

## 一、层次 1b：20 个脚本的动态运行结果

| skill | 脚本 | 结果 | 症状 |
|---|---|---|---|
| **pandapower** | `network_analysis.py` | ✅ EXIT=0 | 网损 43.64 MW（**与我方独立实测 43.6411 MW 吻合**） |
| | `contingency_analysis.py` | 🔴 | `AttributeError: 'pandapowerNet' instance has no attribute 'deepcopy'` |
| | `test_scripts.py` | 🔴 | 同一异常（自检**确实能抓到**，但无人运行） |
| **pypsa** | `build_case39.py` | ⚠️ EXIT=0 | 能跑，但产出的算例潮流失效（见 §2.3） |
| | `optimization_analysis.py` | 🔴 | **`IndentationError`（语法错误），文件无法导入** |
| | `contingency_analysis.py` | 🔴 | 求解成功却报"未收敛"（见 §2.2） |
| | `network_analysis.py` | 🔴 | `KeyError: 'load_0_0'` —— 脚本与自带算例的命名约定不兼容 |
| | `expansion_analysis.py` | ✅ EXIT=0 | 输出为 0 值投资结果 |
| **surge** | `network_analysis.py` | ✅ EXIT=0 | |
| | `sensitivity_analysis.py` | ✅ EXIT=0 | |
| | `contingency_analysis.py` | ✅ EXIT=0 | |
| | `contingency_ranking.py` | ✅ EXIT=0 | 输出**直接带 escalation skill 名** |
| | `test_scripts.py` | ✅ 6/8 | 2 项因缺 C 库失败（见下） |
| | `dispatch_analysis.py` | ⚠️ | 缺 HiGHS C 库（环境，非 skill 缺陷） |
| | `opf_analysis.py` | ⚠️ | 缺 HiGHS C 库（环境） |
| | `transfer_capability.py` | ⚠️ | case118 只有 1 个 area（数据限制，自检已正确 SKIP） |
| **potpourri** | 全部 3 个 | ⚠️ | 缺 `pyomo` / `simbench` / `opf-potpourri`（**我方未安装其 requirements**，非 skill 缺陷） |

> **区分原则**：⚠️ 标记的是**环境/数据**限制（我们用例环境没装对应依赖），🔴 是**skill 自身**的缺陷。二者不能混为一谈。
>
> surge 的报错信息质量突出：明确说明 `pip install highspy` **不提供**共享库，并给出系统级安装指引。这是全仓最好的错误设计。

---

## 二、🔴 阻断级问题（3 项）

### 2.1 `pandapower/scripts/contingency_analysis.py:56` —— 已移除的 API

```python
net_copy = net.deepcopy()          # ← pandapower 3.5.4 中 pandapowerNet 已无此方法
```

**与 PowerMCP 的 `panda_mcp.py:180,191` 是同一处失效调用**（见 [MCP 验证报告](2026-09-21-mcp-examples-verification.md)）。

`requirements.txt` 声明 `pandapower>=3.0.0`，**无上界** → 装出 3.5.4 → 脚本必崩。

**实证**：`python scripts/test_scripts.py` 抛
```
AttributeError: 'pandapowerNet' instance has no attribute 'deepcopy'
```

### 2.2 `pypsa/scripts/contingency_analysis.py:117` —— 已移除的 API（第二处同类）

```python
converged = hasattr(net_copy, 'status') and net_copy.status.get('status') == 'ok'
```

**实测**：PyPSA 1.2.4 中 `Network.status` **不存在**，新 API 从 `optimize()` 返回值取状态：

```
AttributeError: 'Network' object has no attribute 'status'. Did you mean: 'stats'?
optimize() 返回值: ('ok', 'optimal')
```

`hasattr(...)` 返回 `False` → `not hasattr(...)` 为真 → 脚本打印
```
ERROR: Baseline optimization did not converge!
```
**尽管求解器明确返回了 `('ok','optimal')`、目标值 168,246.9**。这是**误报失败**——比崩溃更隐蔽，因为 Agent 会据此放弃一条其实可行的路径。

### 2.3 `pypsa/scripts/optimization_analysis.py` —— 语法错误，文件无法导入

第 2 行 `"""` 开启模块 docstring，第 18 行**本该是 `"""` 收尾，却写成了 markdown 围栏 ` ``` `**：

```python
1  #!/usr/bin/env python3
2  """
3  Optimization results analysis for PyPSA networks.
...
17        print(f"Total cost: {results['objective']}")
18  ```                       ← 应为 """，实际是 markdown 围栏
19
20  import pypsa              ← 被吞进 docstring
...
26      """                   ← 这个 """ 才是真正的收尾
27      Check if optimization has been run...   ← 游离缩进 → IndentationError
```

`python -m py_compile` 确认失败。**全仓仅此 1 个文件语法失败**（已扫描全部 `.py`），是孤立缺陷而非模式化问题。

---

## 三、🟠 事实不符（4 项）

### 3.1 `pandapower/SKILL.md:19` —— 线路与变压器数量写反

文档声称示例序列产出 `39 buses, 34 lines, 12 transformers, 10 generators`。

**实测其自带的 `case39.json`**：

| 项目 | SKILL.md | 实测 | |
|---|---:|---:|---|
| buses | 39 | 39 | ✓ |
| lines | 34 | **35** | ✗ |
| transformers | 12 | **11** | ✗ |
| generators | 10 | 9 gen + 1 ext_grid = 10 | ✓ |

34+12 = 35+11 = 46，**总数对、拆分错**。对 Agent 而言这是"文档与事实不符"——它会按 34 条线路预期。

### 3.2 `pypsa/SKILL.md:22` —— loads 数量不符

声称 `get_network_info -> 10 generators, 46 branches, 19 loads`。

**实测 `case39.nc`**：10 generators ✓、46 branches ✓、**21 loads ✗**。

### 3.3 `pypsa/SKILL.md:23` —— 声称的潮流收敛无法复现 ⚠️

声称 `run_power_flow("case39", linear=False) -> converged, max branch loading 87%`。

**实测：潮流发散。**

```
p0 范围: -1.23e+38 ~ 6.47e+37 MW
负载率 max = 1.37e+37 %
电压范围 = -2.57e+17 ~ 5.36e+16
```

**已做的排除**（均为实测）：

| 排查 | 结果 |
|---|---|
| `pf()` 本身是否可用 | ✅ 极简 2 节点网络的 `pf()` 正常（电压 0.9950~1.0000） ⇒ **`pf()` 无问题** |
| 网络是否连通 | ✅ 1 个连通分量，39 母线全连通 |
| 零阻抗支路 | ✅ 无（`x` 范围 10.2~27.6 Ohm） |
| 容量缺失 | ✅ `s_nom` 无 0/NaN |
| `optimize()` 是否可用 | ✅ 返回 `('ok','optimal')`，目标值 168,246.9（量级合理）⇒ **LOPF 可解，PF 不可解** |
| 手动设 `control='Slack'` | ❌ **仍未收敛** |

**已定位到的缺陷**（但不充分）：`build_case39.py:93`

```python
n.add("Generator", "slack", bus=bus, p_nom=p_max, marginal_cost=0, carrier="slack")
```

命名为 `slack`、注释写"Slack"，但**从未设置 `control="Slack"`** → 网络无参考母线。实测该网络全部 10 台机组 `control` 均为 `PQ`。

> ⚠️ **但手动把该机组设为 `Slack` 后潮流仍发散**，故**它不是充分原因**。**根因未完全定位**，本报告不猜测。

### 3.4 `pypsa/scripts/network_analysis.py` —— 脚本与自带算例不兼容

```
KeyError: 'load_0_0'
```

脚本期望的负荷命名与 `case39.nc` 的实际命名不匹配（自带算例的负荷名为 `load_0_0`、`load_2_1` 等，脚本按另一套约定索引）。**自带算例无法喂给自带的脚本**。

---

## 四、🟡 引用错误（1 项，影响 6 个工具名）

### `opendss/SKILL.md` 与 `README.md` 引用的 6 个 OpenDSS 工具名**全部不存在**

| 被引用（README + SKILL.md） | 是否存在于 OpenDSS server（55 个工具） | 真实对应 |
|---|---|---|
| `compile_and_solve` | ❌ 不存在 | `compile_opendss_file` + `solve_snapshot` |
| `get_bus_voltages` | ❌ 不存在 | `get_voltage_mag_ln_nodes_records`（另有 ll / smart 变体） |
| `get_total_power` | ❌ 不存在 | `get_powers_p_records` / `get_powers_q_records` |
| `set_load_multiplier` | ❌ 不存在 | （未找到对应项） |
| `run_daily_energy_meter` | ❌ 不存在 | （未找到对应项） |
| `get_harmonic_results` | ❌ 不存在 | （**55 个工具中无任何谐波类工具**） |

**含义**：OpenDSS skill 描述的是一套**旧版或不同的 API**。照此执行的 Agent 会调用不存在的工具。

> 注：OpenDSS 不在用户锁定的 4-server 范围内，且本次未安装其依赖，故**未做动态验证**；工具名比对基于 PowerMCP 源码提取（55 个，与仓库扫描报告一致）。

---

## 五、🔵 规范/结构问题（5 项）

### 5.1 `ltspice/SKILL.md` 缺 Escalation triggers 表

README 声称 *"Every `powerskills-tool` skill ends with an **Escalation triggers** table"*。

**实测**：11 个 tool skill 中 **10 个有，`ltspice` 没有**（其 SKILL.md 以 "## Deliver" 直接结尾）。

### 5.2 `voltage-violation-mitigation` 的 description 来源枚举不全

其 description 列举 escalations 来源为「PowerWorld, PSS/E, PSLF, OpenDSS, pandapower, PyPSA, or surge」= **7 个**。

**实测**：有 **10 个** tool skill 会 escalate 到它（漏列 **ANDES、Egret、potpourri**）。

由于 skill 靠 description 做语义匹配，枚举不全会**降低这些来源的匹配准确率**。

### 5.3 仓库**完全没有 CI**

```
★ 仓库无 .github/ —— 没有任何 CI
```

自检脚本（`test_scripts.py`）存在且**确实能抓到** deepcopy 缺陷，但**没有任何东西自动运行它**。这是上述 🔴🔴🟠 长期存活的直接原因。

### 5.4 版本约束前后不一致

| skill | 声明的 pandapower 约束 |
|---|---|
| `pandapower/requirements.txt` | `pandapower>=3.0.0` ← **无上界** |
| `potpourri/requirements.txt` | `pandapower>=2.13,<3.5` ← **有上界** |

同一仓库内一处钉了、一处没钉 → 说明维护者**在局部遇到过**版本不兼容，但未回头统一。

### 5.5 `potpourri` 的约束与在役环境冲突

`potpourri` 要求 `pandapower<3.5`，而我们的环境装的是 **3.5.4**（由 pypsa / surge 的依赖共同决定）。
若在**同一环境**内同时满足 potpourri 与 pypsa/surge，需降级 pandapower —— 与用户在 [MCP 决策记录](2026-09-21-mcp-examples-verification.md) 中「不降级」的决定直接冲突。

---

## 六、✅ 层次 3：交叉一致性检查结果

### 6a. Escalation 引用完整性 —— **PASS**

- 引用的 mitigation skill：**10 个**（去重后）
- 实际存在的 mitigation skill：**10 个**
- **无悬空引用，无孤儿 skill** ✓

### 6b. 工具名真实性 —— **对 3 个可查询 server PASS；OpenDSS 见 §4**

| skill | 调用形式引用的工具数 | 不存在于该 server 的 |
|---|---:|---|
| pandapower | 5 | 无 ✓ |
| pypsa | 9 | 无 ✓ |
| surge | 13 | 无 ✓ |
| andes | 4 | 无 ✓ |
| egret | 3 | 无 ✓ |
| ltspice | 7 | 无 ✓ |
| powerworld | 14 | 无 ✓ |
| psse | 5 | 无 ✓ |
| pslf | 12 | 无 ✓ |
| **opendss** | 6 | **6 个全部不存在** ✗ |

> 初版提取曾把字段名（`loading_percent`、`s_nom`、`v_mag_pu`）、参数名（`lp_solver`、`rate_a_mva`）与算例名（`case118`）误判为工具名；收窄为**调用形式** `name(` 并逐项复核后，上述结论成立。

### 6c. 触发条件与 playbook 入口对齐 —— **PASS**

| tool skill 触发行 | playbook 入口条件 | 对齐 |
|---|---|---|
| `res_bus.vm_pu < 0.95 or > 1.05` | description: "bus voltage falls below 0.95 pu or rises above 1.05 pu" | ✓ |
| `loading_percent > 100` | description: "branch loading exceeds 100% of its rating" | ✓ |
| `run_n1_*` 有 binding contingency | `contingency-mitigation` | ✓ |
| 潮流不收敛 | `convergence-failure-mitigation` | ✓ |

**跨层契约成立**——这是本仓库设计中最扎实的部分。

---

## 七、发现汇总

| # | 发现 | 位置 | 严重度 | 已实测 |
|---|---|---|---|---|
| 1 | `net.deepcopy()` 已移除 | `pandapower/scripts/contingency_analysis.py:56` | 🔴 | ✅ 崩溃 |
| 2 | `Network.status` 已移除 → **误报失败** | `pypsa/scripts/contingency_analysis.py:117` | 🔴 | ✅ 求解成功却报未收敛 |
| 3 | 语法错误（markdown 围栏） | `pypsa/scripts/optimization_analysis.py:18` | 🔴 | ✅ py_compile 失败 |
| 4 | 自带算例潮流发散，无法复现声称的 87% | `pypsa/case39.nc` + SKILL.md:23 | 🟠 | ✅ p0~1e38 |
| 5 | slack 机组未设 `control="Slack"`（非充分原因） | `pypsa/scripts/build_case39.py:93` | 🟠 | ✅ |
| 6 | 脚本与自带算例命名不兼容 | `pypsa/scripts/network_analysis.py` | 🟠 | ✅ KeyError |
| 7 | 线路/变压器数量写反（34/12 → 实为 35/11） | `pandapower/SKILL.md:19` | 🟠 | ✅ |
| 8 | loads 数量不符（19 → 实为 21） | `pypsa/SKILL.md:22` | 🟠 | ✅ |
| 9 | **6 个工具名全部不存在** | `opendss/SKILL.md` + `README.md:32` | 🟡 | ✅ 源码比对 |
| 10 | 缺 Escalation triggers 表 | `ltspice/SKILL.md` | 🔵 | ✅ |
| 11 | description 来源枚举不全（7 → 实为 10） | `voltage-violation-mitigation/SKILL.md` | 🔵 | ✅ |
| 12 | 仓库无 CI | 全仓 | 🔵 | ✅ |
| 13 | 版本约束前后不一致 | `pandapower/` vs `potpourri/requirements.txt` | 🔵 | ✅ |
| 14 | potpourri 的 `pandapower<3.5` 与在役环境冲突 | `potpourri/requirements.txt` | 🔵 | ✅ |

---

## 八、审计方法的局限（诚实声明）

| 项 | 局限 |
|---|---|
| potpourri 的 3 个脚本 | 未动态验证——需 `pyomo`/`simbench`/`opf-potpourri`，且其 `pandapower<3.5` 约束与本环境冲突。**不宜据此判定其有缺陷** |
| surge 的 2 个 OPF 脚本 | 未动态验证——缺 HiGHS/Ipopt **系统 C 库**（非 pip 可装）。属环境限制 |
| OpenDSS 及其余 6 个 server | 未动态验证——依赖缺失或为商业软件。工具名比对基于**源码提取** |
| 层次 2（17 个 skill 的静态文档审计） | **按用户指定未做**。因此**本报告不能声称覆盖全部 21 个 skill 的文档正确性** |
| pypsa case39 潮流发散的根因 | **未完全定位**。已排除 6 项假设，定位到一处缺陷但不充分。不猜测 |

---

## 八·五、已提交的修复（PR #8）

**🔗 https://github.com/Power-Agent/PowerSkills/pull/8** · 状态 OPEN · 3 文件 +39/−12

| 项 | 内容 |
|---|---|
| 分支 | `fix/pypsa-pandapower-api-drift`（从 `main` @ `05bda3a` 分出） |
| 提交 | `920b35a` |
| Fork | `zhangf701/PowerSkills`（本方无 `push` 权限，故经 fork 提交） |
| 作者 | `zhangf701`（提交带 `Co-Authored-By: Claude`） |

> 🔒 **本地状态已冻结（用户指令）**：`PowerSkills/` 停留在 `fix/pypsa-pandapower-api-drift`（HEAD `920b35a`，工作区干净，与 fork 同步）。
> **不要切回 `main`**，等确认合并或决定下一步动作。`main` 保留在本地 `05bda3a`，未受影响。

**实际修复 4 处**（原定 3 处，验证时发现第 4 处）：

| # | 文件:行 | 修复 |
|---|---|---|
| 1 | `pypsa/optimization_analysis.py:18` | ` ``` ` → `"""`（docstring 终止符） |
| 2 | `pandapower/contingency_analysis.py:58` | `net.deepcopy()` → `copy.deepcopy(net)` |
| 3 | `pypsa/contingency_analysis.py` | 新增 `optimization_succeeded()`，改 2 处调用点（`status` API） |
| 4 | `pypsa/contingency_analysis.py:93,104` | `mremove()` → `remove()` |

> **第 4 处是"验证驱动"发现的**：修复 #3 后重跑脚本，错误从
> `ERROR: Baseline optimization did not converge!` 推进到
> `AttributeError: 'Network' object has no attribute 'deepcopy'`，再推进到 `mremove`。
> **只看代码不跑，PR 会是不完整的。**

**逐项验证证据**：

| 检查 | 结果 |
|---|---|
| `python pandapower/scripts/test_scripts.py` | 3/3 通过（修复前崩溃） |
| `python pypsa/scripts/contingency_analysis.py case39.nc` | EXIT=0 跑完（修复前崩溃 → 静默误报失败 → 再崩溃） |
| 三个文件 `py_compile` | 全部通过 |
| `quick_validate.py` ×2 | "Skill is valid!" |

**刻意排除的三项**（已在 PR 描述中说明，建议另开 Issue）：

1. `pypsa/case39.nc` 潮流发散（根因未完全定位）
2. `optimization_analysis.py` 的 `check_optimization_status()` 同样读已移除的 `Network.status`——但其 `else` 兜底使其**不崩溃**，修它会引入行为变化
3. `skill-creator/scripts/quick_validate.py` **在非 UTF-8 默认区域设置下无法运行**（`read_text()` 未指定 `encoding=`，中文 Windows 上抛 `UnicodeDecodeError`）——本次用 `PYTHONUTF8=1` 绕过

---

## 九、待决

- [ ] 是否将本报告提交为 upstream issue / PR（发现 1、3 是明确的代码缺陷，2 是明确的误报逻辑缺陷）
- [ ] 是否补做层次 2（其余 17 个 skill 的静态审计）
- [ ] OpenDSS 的 6 个错误工具名（发现 9）是否需要修正后提 PR
- [ ] `pypsa/case39.nc` 潮流发散（发现 4）—— 是否值得继续定位根因（可能需要与 `build_case39.py` 的原作者确认意图）
