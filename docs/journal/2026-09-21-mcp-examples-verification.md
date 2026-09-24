# PowerMCP 核心 Server 示例脚本验证报告

- **日期**：2026-09-21
- **前置任务**：[仓库扫描](2026-09-21-powerMcp-repo-scan.md) · [环境搭建](2026-09-21-env-setup.md)
- **状态**：✅ 三个脚本全部跑通（EXIT=0）
- **运行环境**：`PowerMCP/.venv`（Python 3.12.6，uv）· powermcp 0.4.0 · powerio 0.11.3 · mcp 2.2.0

---

## 一、交付物

| 文件 | 说明 |
|---|---|
| [examples/01_pandapower_surge_demo.py](../../examples/01_pandapower_surge_demo.py) | pandapower + surge 全流程（IEEE 39） |
| [examples/02_powerio_translation_demo.py](../../examples/02_powerio_translation_demo.py) | PowerIO 跨格式转换（内存传递） |
| [examples/03_commercial_runtime_check.py](../../examples/03_commercial_runtime_check.py) | 商业/高依赖 Server 预检与优雅探查 |
| [examples/04_pandapower_opf_demo.py](../../examples/04_pandapower_opf_demo.py) | **AC / DC OPF**（Skill 侧调用，非 MCP —— 见 §3.7） |
| [examples/data/case39.json](../../examples/data/case39.json) | IEEE 39 算例（pandapower JSON 表示） |
| [examples/data/case39.m](../../examples/data/case39.m) | IEEE 39 算例（MATPOWER 表示，经 powerio emit） |
| [docs/logs/](../../docs/logs/) | 三个脚本的完整运行日志 |

每个脚本**自包含**（各自内置极简 MCP stdio 客户端），可独立运行：

```bash
cd d:/coding/powerMcp_Pskills
./PowerMCP/.venv/Scripts/python.exe examples/01_pandapower_surge_demo.py
./PowerMCP/.venv/Scripts/python.exe examples/02_powerio_translation_demo.py
./PowerMCP/.venv/Scripts/python.exe examples/03_commercial_runtime_check.py
```

---

## 二、示例 01 结果：pandapower + surge（IEEE 39）

### 2.1 基态潮流（pandapower server）

算例：39 母线 / 35 线路 / 11 变压器 / 9 机组 / 21 负荷

| 指标 | 数值 |
|---|---|
| 收敛 | `converged = True` |
| 最低电压 | **母线 30，vm_pu = 0.9820** |
| 最高电压 | **母线 35，vm_pu = 1.0636** |
| 最重载线路 | **线路 21，loading_percent = 73.37%** |
| 低于 0.95 pu 的母线 | 0 个 |
| 高于 1.05 pu 的母线 | 7 个（35/24/25/27/21/28/18） |
| 过载（>100%）线路 | 0 个 |

> **注（避免误读）**：母线 35 的 1.0636 pu **恰等于该处发电机的电压设定值**（`gen[5].vm_pu = 1.0636`），它是 PV 母线，由机组维持在设定点。故那 7 个 >1.05 反映的是**算例数据的设定值偏高**，而非求解异常。脚本据此只断言真实成立的不变量（收敛、无低压、无过载）。

### 2.2 N-1 故障筛选

**⚠️ 发现上游缺陷：pandapower server 的 `run_contingency_analysis` 在本环境不可用。**

```
[BUG] Contingency analysis failed: 'pandapowerNet' instance has no attribute 'deepcopy'
```

- **根因**：`pandapower/panda_mcp.py:180` 与 `:191` 调用 `net.deepcopy()`；而 pandapower 3.5.4 中 `pandapowerNet` 的继承链为 `pandapowerNet → ADict → dict`，**已不再提供该方法**（实测 `hasattr(net, 'deepcopy') == False`）。
- **为何未被上游发现**：`pandapower/requirements.txt` 仅写 `pandapower`，**未钉版本**，该缺陷只在较新 pandapower 上暴露。
- **另一重局限**：即便可用，该工具也只返回**元件索引列表**，不含 `vm_pu` / `loading_percent` 数值；且分析后不保留故障态，无法事后回查。

**为何上游 CI 没发现**（已核实）：`tests/` 中**没有 `test_pandapower_server.py`**，全仓测试里也没有任何一处调用 `run_contingency_analysis`（`tests/test_sandbox.py:47` 仅把它列入 AST 路径检查清单，非功能测试）。CI 只跑 `tests/` + PowerFactory + HOPE + PSCAD + PLEXOSDB + surge，**pandapower server 的工具体从未被执行过**。

**修复路径的实测评估**（见 [tools/test_patch_propagation.py](../../tools/test_patch_propagation.py)）：

| 方案 | 实测结果 |
|---|---|
| A. 不打补丁（基线） | ❌ 失败 |
| B. 仅在客户端进程 monkey patch | ❌ **仍然失败** —— 补丁不跨进程 |
| C. 经 `PYTHONPATH` + `sitecustomize` 注入子进程 | ✅ 成功（46 场景 / 45 有越限） |

> 方案 B 失败的原因：`powermcp run <tool>` 经 `runpy.run_path` 在**独立子进程**中执行 server。在客户端脚本里给 `pandapowerNet` 打补丁，改的是客户端进程的类对象；server 子进程有独立的解释器与模块实例，看不到该补丁。
>
> 方案 C 成功的交叉印证：打上补丁后工具报告 45 个故障越限，而本地补算得"低电压 2 + 仅高电压 43 = 45"，**两路径吻合**——说明该工具判定逻辑本身正确，问题只在 `deepcopy` 那一行。

**处置决策**：**不改动上游源码**，N-1 分析统一走 surge。

理由：surge 的 `run_n1_branch_contingency` **自带** `max_loading_pct` / `min_vm_pu` / `loading_pct` / `flow_mw` 等数值，完全满足"报出具体数值"的要求，且无需任何补丁；而 pandapower server 的工具即便修复也只返回元件索引。示例 01 的 4a 分支保留为该缺陷的**诊断输出**，不是脚本失败。

**surge N-1 结果**（`run_n1_branch_contingency`，46 场景 / 23 有越限 / 52 条越限）

线路负载率 >100% 的故障 **19 个**，Top-3：

| 断号 | 支路 | 最大负载率 | 最低电压 |
|---|---|---:|---:|
| `branch_26` | Line 21→22 | **161.84%** | nan |
| `branch_17` | Line 13→14 | **133.50%** | nan |
| `branch_37` | Line 10→32 | **127.59%** | nan |

母线电压 <0.95 pu 的故障 **2 个**：`branch_42`（Line 20→34）min_vm_pu = **0.9361**；`branch_19`（Line 15→16）min_vm_pu = **0.9368**

**Top-3 关键故障逐条数值**（脚本实际输出）：

```
#1 断号 branch_26    Line 21->22(ckt 1)      最大负载率 161.84%   越限 3 条
     ThermalOverload  支路 23->24   loading_pct = 161.84%   flow = 958.49 MW
     ThermalOverload  支路 22->23   loading_pct = 112.14%   flow = 650.00 MW
     ThermalOverload  支路 16->24   loading_pct = 105.14%   flow = 630.12 MW
#2 断号 branch_17    Line 13->14(ckt 1)      最大负载率 133.50%   越限 2 条
     ThermalOverload  支路 6->11    loading_pct = 133.50%   flow = 639.85 MW
     ThermalOverload  支路 10->11   loading_pct = 103.88%   flow = 617.44 MW
#3 断号 branch_37    Line 10->32(ckt 1)      最大负载率 127.59%   越限 4 条
     ThermalOverload  支路 2->3     loading_pct = 127.59%   flow = 622.99 MW
     ThermalOverload  支路 15->16   loading_pct = 111.81%   flow = 646.07 MW
     ThermalOverload  支路 16->19   loading_pct = 105.74%   flow = 625.51 MW
     Islanding        支路 (未标注)  loading_pct =   2.00%   flow = -
```

> 越限类型除 `ThermalOverload` 外还有 `VoltageHigh`（如 母线 25、母线 9）与 `Islanding`；后者无支路定位信息，脚本已做容错标注而非崩溃。

### 2.3 灵敏度矩阵（surge）

**PTDF**（46 × 39，非零元 1090，稀疏度 0.3924）

```
 ↓row \ col          1           2           3           4           5
 1->2->1        0.54621    -0.21065    -0.13911    -0.05239    -0.00165
 1->39->1       0.45379     0.21065     0.13911     0.05239     0.00165
 2->3->1        0.43676     0.63149    -0.16673    -0.04997    -0.00256
 2->25->1       0.10945     0.15786     0.02762    -0.00242     0.00092
 3->4->1        0.37241     0.53975     0.62252    -0.07686    -0.00747
```

**LODF**（46 × 46，非零元 763，稀疏度 0.5261，Inf/None 506）

```
 ↓row \ col      1->2->1     1->39->1      2->3->1     2->25->1      3->4->1
 1->2->1        -1.00000      1.00000     -0.35456     -0.12016     -0.28848
 1->39->1        1.00000     -1.00000      0.35456      0.12016      0.28848
 2->3->1        -0.80088      0.80088     -1.00000      0.87984     -0.38841
 2->25->1       -0.19912      0.19912      0.64544     -1.00000      0.09992
 3->4->1        -0.68822      0.68822     -0.41021      0.14386     -1.00000
```

**物理自洽性核对**：对角线 = −1.0（开断自身即全失）；`1->2` 与 `1->39` 互为相反数 ±1.0（同母线间并联支路）；矩阵中的 `null` 对应开断后形成孤岛、LODF 无定义的场景（Inf/None 506）。

---

## 三、示例 02 结果：PowerIO 跨格式转换

### 3.1 parse → IR

```
源格式      : pandapower-json
value_type  : powerio.BalancedNetwork
IR 长度     : 65,188 字符
IR schema   : pio-ir v2  (producer=powerio 0.11.3)
摘要        : case39  母线 39 / 支路 46 / 机组 10 / 负荷 21
拓扑        : 连通分量 1  参考母线 [30]  辐射状=False
诊断        : 0 条（status: ok）
```

二次 `summarize` 元素数一致 —— 幂等性校验 PASS。

### 3.2 内存传递至两个求解器

同一份 IR 字符串**不经文件**分别传入：

| | pandapower `load_network_from_json` | pypsa `import_case_from_json` |
|---|---|---|
| status | success | success |
| value_type | `powerio.BalancedNetwork` | `powerio.BalancedNetwork` |
| 载入规模 | 39 母线 / 35 线路 / 11 变压器 | 39 母线 / 35 线路 |
| diagnostics | 1 条 / warnings 1 条 | 2 条 / warnings 3 条 |
| fidelity | — | `canonical` |
| 基态潮流 | 收敛，最低 0.9820 / 最高 1.0636 | 收敛，最低 0.9820 / 最高 1.0636 |

### 3.3 ★ 一个必须处理的坑：两侧元件编号约定不同

首次对比时脚本**误报 0.068 pu 的"差异"**。查明原因是**编号偏移**：

- pandapower 的 `res_bus` / `res_line` 用 **0-based 整数索引**（0..38）
- pypsa 沿用 **IR 里的 1-based 元件标识**（母线 `"1"`..`"39"`，线路 `"line_1"`..`"line_35"`）

**若按字面键join，等于拿不同物理元件对比。** 脚本改为**自动探测偏移**（搜索使最大残差最小的偏移量），而非硬编码：

```
[探测到的编号偏移] pypsa 键 = pandapower 键 + 1
```

### 3.4 对比结果 —— IR 往返保真

**母线电压 vm_pu**（39 个母线）

| 母线 | pandapower | pypsa | Δ(pu) |
|---:|---:|---:|---:|
| 19 | 0.991011 | 0.991011 | −6.98e−11 |
| 18 | 1.050107 | 1.050107 | −6.57e−11 |
| 14 | 1.016185 | 1.016185 | −5.07e−11 |
| 6 | 0.998397 | 0.998397 | −5.03e−11 |
| 7 | 0.997872 | 0.997872 | −5.00e−11 |

- **最大偏差 |Δ| = 6.980e−11 pu**，平均 2.916e−11 pu
- 判定阈值 1e−06 pu → **一致 PASS**

**支路首端有功**（35 条线路，pandapower `p_from_mw` vs pypsa `p0`）

- **最大偏差 |Δ| = 2.249e−07 MW**，判定 **一致 PASS**

> **结论**：同一 PowerIO IR 经两个独立求解器，基态潮流结果一致到**机器精度**。PowerIO IR 的往返语义保真度得到实测证实。

### 3.5 ⚠️ 待查项：PyPSA OPF 在 IR 导入算例上不可行

`optimize_network`（solver=highs）返回 `infeasible`。

**已逐项排除的假设**（均为实测）：

| # | 排查项 | 结果 |
|---|---|---|
| 1 | 求解器/环境 | 从零构建的极简 PyPSA 网络 OPF → **optimal (obj=500)** ⇒ 环境正常 |
| 2 | 电压上限 | `v_mag_pu_max` 放宽至 1.20，仍 infeasible |
| 3 | 电压退化配置 | `v_mag_pu_min = v_mag_pu_max = 1.0`（全网电压恒定），**仍 infeasible** |
| 4 | 容量缺失 | lines/transformers `s_nom` 无 0/NaN；generators `p_nom` 无 0/NaN |
| 5 | 必需列 | `p_nom`/`marginal_cost`/`p_min_pu`/`p_max_pu`、`s_nom`/`x`/`r` 均存在 |
| 6 | 无功限值 | `q_min_pu`/`q_max_pu` **列不存在**；补上 ±1.0 后仍 infeasible |
| 7 | **负荷水平** | `load = 0` **仍然 infeasible** ← 零负荷的平凡解本应可行 |
| 8 | 容量放大 | `s_nom ×100`、`p_nom ×3`、`load ×0.5` 均仍 infeasible |
| 9 | 基态过载 | pypsa 基态潮流线路 max 75.22%、变压器 72.22%，**无过载** |
| 10 | 控制类型 | `control` 全设 PV / Slack / PQ、删掉 Slack 机组，均仍 infeasible |
| 11 | 变压器分接头 | `tap_ratio` 全设 1.0、`phase_shift` 全设 0，均仍 infeasible |
| 12 | 成本退化 | 所有 `marginal_cost` 同为 0.3；改为互异后仍 infeasible |
| 13 | 孤立母线 | 39 个母线**全部被连接**，无孤立节点 |

**结论**：不可行性**特定于经 PowerIO IR 导入的算例**（同一 IR 的基态潮流两侧一致到 1e−10 pu）。**排除了数据层的一切解释**——包括「零负荷仍不可行」这一退化案例，说明问题出在 PyPSA 1.2.4 对该网络**优化模型的构造**，而非物理不可行。

> **本报告不猜测成因，也不将其作为 PowerIO 或 PyPSA 的缺陷断言**。如实记为**未解的阻塞项**。
>
> ⚠️ **本报告早期版本的更正**：曾记录「DC 线性化同样不可行」。**该结论是错的**——PyPSA 1.2.4 的 `Network.optimize()` **没有 `linearized` 参数**（实测签名见下），该实参落进 `**kwargs` 被**静默忽略**，实际跑的一直是 AC OPF。因此"DC OPF"这一路径**从未被真正测试过**。
>
> ```
> optimize() 实际参数: snapshots, multi_investment_periods, transmission_losses,
>   linearized_unit_commitment, model_kwargs, extra_functionality, assign_all_duals,
>   solver_name, solver_options, log_to_console, compute_infeasibilities,
>   include_objective_constant, committable_big_m, meshed_thresholds, kwargs
>   -> 'linearized' 不在其中
> ```
> 附带发现：IR→PyPSA 导入**不携带 `q_min_pu`/`q_max_pu`**（无功能力限值），这两列在导入网络中不存在。

### 3.6 能力不对称说明

pandapower server 的 8 个工具中**没有 OPF**（`create_empty_network` / `load_network` / `run_power_flow` / `run_contingency_analysis` / `get_network_info` / `load_network_from_any` / `load_network_from_json` / `export_network_to_format`），故"两者 OPF 对比"在本仓的 pandapower server 上**不可实现**。

### 3.7 ★ OPF 的替代交付路径（示例 04）

鉴于 §3.5 的 PyPSA OPF 阻塞与 §3.6 的 pandapower server 无 OPF 工具，采用了**第三条路**：

**pandapower 自带的 `runopp`（AC OPF）与 `rundcopp`（DC OPF）实测可用**，且与已验证的 `runpp` **同引擎、同网络对象、同索引约定** —— 没有新的数据契约，没有新的失败模式。

| 指标 | 基态潮流 | AC OPF | DC OPF |
|---|---:|---:|---:|
| 发电合计 (MW) | 6297.8711 | 6298.4106 | **6254.2300** |
| 网损 (MW) | 43.6411 | 44.1806 | **0.0000**（模型无网损） |
| 最低电压 (pu) | 0.9820 | 0.9820 | — |
| 最高电压 (pu) | 1.0636 | **1.0600**（触上限） | — |
| 线路最大负载率 (%) | 73.3709 | 87.6447 | 90.16 |
| 目标函数值 | （未优化） | **41,872.30** | **41,263.94** |

**AC vs DC 目标值差 = 608.36（+1.474%）** —— AC 计及 44.18 MW 网损，DC 不计，故 DC 目标值更低属预期。

**守恒律校验（三项全部通过）**：

```
基态:   发电 6297.8711 - (负荷 6254.23 + 网损 43.6411) = -0.0000 MW
AC OPF: 发电 6298.4106 - (负荷 6254.23 + 网损 44.1806) = -0.0000 MW
DC OPF: 发电 6254.2300 - 负荷 6254.23                  = -0.0000 MW  ← 无网损模型应精确相等
```

**AC OPF 机组最优出力**（限值并列，可逐行核验）：

| 机组 | p_mw | max_p_mw | q_mvar | vm_pu | 状态 |
|---|---:|---:|---:|---:|---|
| gen_0 | 671.4575 | 1040.0 | 140.0027 | 1.0443 | |
| gen_1 | 670.6040 | 725.0 | 299.9981 | 1.0191 | |
| gen_2 | 651.9934 | **652.0** | 133.7294 | 1.0098 | ← 达上限 |
| gen_3 | 508.0000 | **508.0** | 147.8162 | 1.0157 | ← 达上限 |
| gen_4 | 661.5451 | 687.0 | 236.2584 | 1.0600 | |
| gen_5 | 580.0000 | **580.0** | 68.1022 | 1.0600 | ← 达上限 |
| gen_6 | 564.0000 | **564.0** | 32.4907 | 1.0370 | ← 达上限 |
| gen_7 | 654.4892 | 865.0 | −19.1274 | 1.0294 | |
| gen_8 | 690.3215 | 1100.0 | 148.5428 | 1.0458 | |
| ext_grid | 645.9999 | — | 167.7178 | — | ← 平衡机 |

**节点边际电价 `lam_p` 前 5 高**（`res_bus.lam_p`，可用于容量规划论述）：
母线 38 `14.1064` · 母线 8 `14.0631` · 母线 0 `14.0433` · 母线 7 `13.9580` · 母线 6 `13.9255`

#### ⚠️ 破例声明（必须随能力一起交付）

**本示例的 OPF 部分不是 MCP 调用**，而是 Skill 侧直接调用 pandapower 的 `runopp` / `rundcopp`。这与示例 01–03 的纯 MCP 路径不同，是与 §7 决策一并接受的取舍。

为使其结论对 MCP 侧成立，脚本设置了 **🔒 一致性闸门**（步骤 4.2）：从**与 MCP 相同的 JSON 文件**本地重建网络，比对基态潮流母线电压。

```
[闸门] 与 MCP 结果对比（39 个母线）
       最大偏差 |Δ| = 0.000e+00 pu
       ✅ 一致（阈值 1e-06 pu）—— 本地网络与 MCP 网络是同一个
```

闸门未过则脚本 `assert` 中止，**不允许在来历不明的网络上继续做优化**。

#### 一个有价值的行为对照

pandapower 在求解时打印：

```
gen vm_pu > bus max_vm_pu for gens [5]. Setting bus limit for these gens.
```

即机组 5（母线 35）的电压设定值 `1.0636` 高于该母线 `max_vm_pu = 1.06` —— 这是**算例数据自身的不自洽**。pandapower **自动放宽该母线限值**后继续求解并成功；而 **PyPSA 在同一份数据上直接判 `infeasible`**。

> 这是一处有诊断价值的对照，但它**不足以解释** §3.5 的 PyPSA 阻塞——实测把 `v_mag_pu_max` 放宽到 1.20 后 PyPSA 仍不可行，故该异常**不是充分原因**。此处如实记录，不作为结论。

---

## 四、示例 03 结果：商业 / 高依赖 Server 探查

### 4.1 PowerWorld 三级探查

| 层级 | 检查项 | 结果 |
|---|---|---|
| 一级 | PowerWorld Simulator 软件 | ✅ **已安装** `C:\Program Files\PowerWorld\Simulator GOS Education 23\pwrworld.exe`（**Education 版**） |
| 二级 | SimAuto COM 注册 | ❌ **`PowerWorld.SimulatorAuto` 未注册**；注册表仅有文件关联 ProgID `PowerWorld.pwbfile` / `PowerWorld.pwpfile` |
| 三级 | `esa` 桥接包 | ❌ 未安装（`pip install powermcp[powerworld]`） |
| 案例 | 仓库内 PWB | ✅ `IEEE 39 bus.pwb`（44,974 bytes） |

**输出**：
```
[SKIP] PowerWorld COM/License unavailable
       缺失项: SimAuto COM 注册, esa 包
```

> **根因**：`esa` 通过 COM 驱动 SimAuto 自动化接口。**Education/GOS 版不注册 SimAuto COM 类**，故即便装上 `esa` 也无法工作——软件存在 ≠ 可自动化。

### 4.2 HOPE / GenX —— Julia 缺失

```
[SKIP] Julia runtime missing for HOPE
[SKIP] GenX.jl checkout 未配置
```

| 检查项 | HOPE | GenX |
|---|---|---|
| Python 包 | PyYAML 6.0.3 ✅ | matplotlib 3.11.2 / pandas 2.3.3 ✅（核心传递带入） |
| Julia 运行时 | ❌ 不在 PATH | ❌ 不在 PATH |
| 配置项 | `hope.repo_root` / `hope.julia_bin` 均未设置 | `genx.repo_root` 未设置 |

> **装得上 ≠ 跑得动**：HOPE/GenX 的 Python 包已随 `[hope]`/核心依赖装好，工具也能注册，但真正求解需调用 Julia 侧引擎。这是 PowerMCP 外部引擎 server 的普遍模式（延迟导入 + 可操作报错，**无 mock 降级**）。

### 4.3 其余商业 Server 汇总

| tool | pip 包 | 本机软件 | 状态与原因 |
|---|---|---|---|
| psse | 未装 | — | 厂商引擎，未配置 `psse.python_lib` / `psse.bin` |
| pslf | 未装 | — | 厂商引擎，未配置 `pslf.python_lib` |
| powerfactory | 未装 | — | 厂商引擎，未配置 `powerfactory.python_path` |
| pscad | 未装 | — | 缺包 `mhi`；`pip install powermcp[pscad-windows]` |
| ltspice | 未装 | — | 缺包 `PyLTSpice`；`pip install powermcp[ltspice]` |
| plexosdb | 未装 | — | 缺包 `plexosdb_mcp`（该包**未上 PyPI**，需手动 git 安装） |
| powerworld | 未装 | **有** | 缺包 `esa` + SimAuto COM 未注册 |

---

## 五、发现汇总

| # | 发现 | 类型 | 严重度 | 处置 |
|---|---|---|---|---|
| 1 | `run_contingency_analysis` 在 pandapower 3.5.4 下必然失败（`net.deepcopy()` 已移除） | **上游缺陷** | 高（功能不可用） | **已决策：不改源码，改走 surge** |
| 2 | 该工具即便可用也只返回索引、不返回数值；且不保留故障态 | 设计局限 | 中 | 同上，surge 输出更完整 |
| 3 | PowerIO IR 往返保真度达机器精度（电压 7e−11 pu / 有功 2e−07 MW） | **正向验证** | — |
| 4 | 两求解器元件编号约定不同（0-based vs 1-based），字面键对比会张冠李戴 | 使用陷阱 | 中 |
| 5 | PyPSA OPF 在 IR 导入算例上不可行，成因未定位（已排除 13 项假设） | 待查项 | 中 | **已用 C1 绕过**：改用 `runopp`/`rundcopp` 交付 OPF（§3.7） |
| 6 | PowerWorld 仅装了 Education 版，**不含 SimAuto COM**，故不可自动化 | 环境限制 | 高（使用侧） |
| 7 | pandapower server **无 OPF 工具**，与 PyPSA 能力不对称 | 设计局限 | 低 |
| 8 | HOPE/GenX 包已装但缺 Julia 运行时，属"装得上 ≠ 跑得动" | 环境限制 | 中 |

---

## 六、尚未验证的部分（诚实声明）

| 项目 | 为何未验证 |
|---|---|
| OpenDSS 的 55 个工具 | 未装 `[opendss]` extra |
| ANDES(6) / Egret(5) / LTSpice(7) | 未装对应 extra |
| PSSE / PSLF / PowerFactory / PSCAD / PLEXOSDB | 需商业软件 + 配置路径 |
| PowerWorld 的 14 个工具 | SimAuto COM 未注册 |
| HOPE 的 20 个工具 / GenX 的 7 个工具 | 缺 Julia |
| 各 server 的非潮流功能（建模、编辑、导出等） | 本次仅覆盖潮流 / N-1 / 灵敏度 / 转换路径 |

**已实测覆盖**：pandapower(8 中 3 个)、PyPSA(17 中 3 个)、surge(44 中 4 个)、powerio(10 中 3 个)，合计约 13 个 MCP 工具的真实调用；另加示例 04 的 2 项 **Skill 侧** pandapower 调用（`runopp` / `rundcopp`）。

### 三大支柱的能力现状

| 支柱 | 状态 | 路径 |
|---|---|---|
| 基态潮流 | ✅ | MCP |
| 跨格式解析与矩阵 | ✅ | MCP（PowerIO IR，保真 1e-10） |
| PTDF/LODF 与 N-1 | ✅ | MCP（surge） |
| **AC / DC OPF 与容量规划** | ✅ | ⚠️ **Skill 侧 Python**（`runopp`/`rundcopp`），非 MCP —— 见 §3.7 |

---

## 七、决策记录：N-1 路径的选择

> ⚠️ **本节记录已被后续修订（2026-09-21 晚，见 §7.2）**。当日本节决策为「不改动上游源码」，后经用户确认改为**修复 PowerMCP 的 `panda_mcp.py`**。下文保留当时的推演过程，以便回溯；**当前状态以 §7.2 为准**。

**决策（当时）**：N-1 分析统一走 surge，**不改动 PowerMCP 源码**。

**背景**：发现 #1 的 `net.deepcopy()` 缺陷有 4 条候选修复路径，逐一实测后：

| 路径 | 实测结论 |
|---|---|
| 降级 pandapower 到 2.x | ❌ 排除。`pyproject.toml` 对 pandapower **无版本约束**，降级需自行钉版本并同时满足 Python 3.12 / PyPSA 1.2.4 / PowerIO 0.11.3，把一个问题换成三个 |
| 客户端进程 monkey patch | ❌ **实测无效**。`powermcp run <tool>` 经 `runpy.run_path` 在独立子进程执行 server，客户端补丁不跨进程 |
| `PYTHONPATH` + `sitecustomize` 注入 | ✅ 实测有效（46 场景 / 45 越限），但需给**每个** MCP 客户端配置条目挂 `env.PYTHONPATH`，比改源码更易失配 |
| 直接改 `panda_mcp.py` | ✅ 有效且最简单，但 `PowerMCP/` 是外部 git checkout，改动会造成与上游分叉 |
| **改用 surge（采纳）** | ✅ **零改动**，且输出**更完整**（自带 `loading_pct` / `flow_mw` / `min_vm_pu`，而 pandapower 工具即便修复也只给索引） |

**最终选择 surge 的决定性理由**：它是唯一**同时**满足"零改动"与"输出满足数值要求"的路径。

**遗留影响**：失去 pandapower 引擎自身的 N-1 结果。若将来需要该引擎的结果，改源码是最短路径（一行 ×2 处）。

### 7.1 OPF 路径的选择（决策 C1）

OPF 面临与 N-1 类似但更严重的处境：**两条 MCP 路径都不可用**（pandapower server 无 OPF 工具；PyPSA 的 `optimize_network` 对 IR 导入算例 infeasible，成因未定位）。

评估过三条路：

| 路径 | 成本 | 结果 | 取舍 |
|---|---|---|---|
| **A** 定位 PyPSA OPF 阻塞（原生重建对照） | 2–4 h | PyPSA server 的 OPF 可用 | 不保证能解决；且需构建原生网络，有"建错得假结论"的风险 |
| **C1** 用 `pandapower.runopp` / `rundcopp` ✅ **采纳** | ~30 min | **AC + DC OPF 立刻可用**（已验证） | 是 Skill 侧 Python 调用，**非 MCP 工具调用** |
| C2 给 pandapower server 加 OPF 工具 | ~1 h | MCP 原生 OPF 工具 | 需改上游源码（已否决） |

**采纳 C1 的理由**：`runopp` 与已验证的 `runpp` **同引擎、同网络对象、同索引约定**，不引入新的数据契约与失败模式；而路线 A 要解的是一个跨引擎转换问题，成本高一个数量级且结论不确定。

**为弥补 C1 的"非 MCP"弱点**，示例 04 设置了 🔒 一致性闸门：本地网络必须与 MCP 载入的网络逐母线一致（实测 Δ = 0.000e+00 pu），否则 `assert` 中止。这样 OPF 的结论对 MCP 侧成立。

**遗留影响**：OPF 能力在 Skill 实现上是一条**独立的 Python 路径**，与其余三大支柱的 MCP 路径不同。若日后要统一到 MCP，最短路径仍是给 pandapower server 加一个 OPF 工具。

---

### 7.2 修订：改为修复 PowerMCP 源码（2026-09-21 晚）

**变更**：用户确认改为修复 `PowerMCP/pandapower/panda_mcp.py` 的 `net.deepcopy()`，而非绕开它。

**改动**（最小修复，1 文件 +3 −2）：

```diff
 from typing import Dict, List, Optional, Tuple, Any, Union
+import copy
 import sys
 from pathlib import Path
@@ run_contingency_analysis
-        orig_net = net.deepcopy()
+        orig_net = copy.deepcopy(net)
-                contingency_net = orig_net.deepcopy()
+                contingency_net = copy.deepcopy(orig_net)
```

**验证**（两条独立路径互证）：

| 路径 | 结果 |
|---|---|
| MCP 直调 `run_contingency_analysis` | `status: success`，**46 故障 / 45 越限** |
| 早前经 `PYTHONPATH` + `sitecustomize` 注入补丁 | **46 场景 / 45 越限**（完全一致） |
| 示例 01 端到端重跑 | **EXIT=0**，`[4a]` 分支走成功路径 |

**✅ 已提交（本地分支，不提 PR）**：

| 项 | 值 |
|---|---|
| 分支 | `fix/pandapower-deepcopy`（从 `main` @ `a21ea6b` 分出） |
| 提交 | `563297a` |
| 范围 | 1 文件 +4 −2 |
| `main` | **未受影响**，仍与 `origin/main` 一致 |

> 此前本节初稿称"未触碰上游"，**与现状不符**：`main` 确实未被触碰，但仓库并不干净 ——
> 修复位于独立分支上。选择分支而非直接改 `main`，是为了让 `main` 仍可与上游同步。

**未做**（超出本次"最小修复"范围）：
- 补 `tests/test_pandapower_server.py`（PowerMCP 的 `tests/` 中**没有** pandapower server 的功能测试，是本案缺陷长期存活的直接原因）
- 向 `Power-Agent/PowerMCP` 提 PR（用户明确只要本地修复）
- 增强 `run_contingency_analysis` 的输出（当前仍只返回元件索引，不含数值）

**连带更新**：示例 01 的 docstring 与诊断分支已同步改写 —— 不再声称"不改动上游源码"，
改为说明「4a 用 pandapower 筛选（上游缺陷已在本分支修复）+ 4b 用 surge 取数值」，
并让 else 分支成为"当前不在修复分支上"的诊断提示。

---

## 八、待办

- [ ] 排查 PyPSA OPF 在 IR 导入算例上不可行的成因（发现 #5）——**已降级为可选**，OPF 已由 C1 路径交付
- [ ] 若需 OPF 统一走 MCP：给 pandapower server 加一个 OPF 工具（需改上游源码，当前否决）
- [ ] 决定 AC OPF 的 `q_min_pu`/`q_max_pu` 是否需要显式配置（IR→PyPSA 导入不携带该字段，已实测确认）
- [ ] 决定是否补装 `[andes]` / `[opendss]` extra 以扩大验证覆盖
- [ ] 若需验证 HOPE/GenX，先安装 Julia 运行时
- [ ] **明确 Skill 目标**（自仓库扫描起持续挂起）
