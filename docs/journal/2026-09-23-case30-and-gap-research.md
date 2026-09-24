# case30 全流程验证 + 文献空白调研 + 技能交付

- **日期**：2026-09-22 ~ 2026-09-23
- **前置**：[环境搭建](2026-09-21-env-setup.md) · [MCP 示例验证](2026-09-21-mcp-examples-verification.md) · [PowerSkills 审计](2026-09-21-powerskills-audit.md)
- **状态**：case30 与技能交付已完成；文献调研**结论未定**（见第四部分）

本文合并三块此前只存在于对话中的工作。分四部分，可独立阅读。

---

# 一、case30 全流程验证（09-22）

对象：`GridData/MatpowerData/case30.m`（MATPOWER，30 母线 / 41 支路 / 6 机组 / 20 负荷 / 2 并联补偿）

## 1.1 PowerIO IR 解析

```
schema  : pio-ir    version: 2    producer: powerio 0.11.3
value_type : powerio.BalancedNetwork     ← 非多导体
诊断   : []      diagnostics_summary: {"status":"ok","counts":全 0}
IR 文件: work/case30/case30.pio.json  (46,522 B, SHA256 28d21e7d8b354a4f…)
```

**本文所有后续步骤复用这同一份 IR，未重新解析。**

## 1.2 slack bus 推荐：**母线 1**

| 判据 | 依据 |
|---|---|
| 已是源算例声明的参考母线 | MATPOWER 中 `kind = REF`；PowerIO 报 `reference_buses: [0]` |
| **无功能力断层最强** | `qmax = 150`，是次高者（62.5）的 **2.4 倍** |
| 无本地负荷 | 全算例唯一无负荷的机组母线 |
| 有功备用 | `pmax = 80`（并列最大），当前 `pg = 23.54` |

**注意**：母线 1 的 `vmax = 1.05` 比其他 PV 母线的 `1.10` **更紧**，做 OPF 时会成为有效约束。

## 1.3 跨求解器基态潮流对比

同一份 IR 分别导入 pandapower 与 PyPSA：

| 对比项 | 探测到的偏移 | 配对 | 最大偏差 | 平均偏差 | 阈值 1e-06 |
|---|---|---:|---:|---:|---|
| 母线电压 `vm_pu` | pypsa = panda **+1** | 30/30 | **8.8369e-11 pu** | 3.2176e-11 | ✅ |
| 支路首端有功 | pypsa = panda **+1** | 41/41 | **8.9278e-08 MW** | 1.5393e-08 | ✅ |

**⚠️ 编号约定陷阱（必记）**：pandapower 用 **0-based 索引**，PyPSA 沿用 IR 的 **1-based 标识**。
- 按字面键直接比对 → 最大"偏差" **0.027806 pu**
- 自动探测偏移后 → 真实偏差 **8.84e-11 pu**
- **字面比对把偏差放大了 3.1 亿倍**，且会拿不同物理元件做对比

**偏差最大的 5 个母线恰好是电压最低的那几个，偏差最大的支路恰好是过载那条** ——
数值条件最差处两实现最易分岔。**偏差分布与物理应力分布吻合，本身即一种交叉验证。**

## 1.4 PTDF / LODF（surge）

| 矩阵 | 维度 | nnz | sparsity | max\|·\| | NaN | Inf/None |
|---|---|---|---:|---:|---:|---:|---:|
| PTDF | 41 × 30 | 1024 | 0.167480 | 1.0 | 0 | 0 |
| LODF | 41 × 41 | 1234 | 0.207959 | 1.0 | 0 | **123** |

**⚠️ 两侧 sparsity 分母不同**：PTDF 用全体元素（1−1024/1230），LODF 用**非 None 元素**（1−1234/1558）。**不可直接横向比较。**

### 物理自洽性核对（三条独立证据链重合）

| 核对项 | 结果 |
|---|---|
| LODF 对角线 | **38/38 精确 = −1.000000000000000**（最大偏离 0.000e+00） |
| 图论桥支路 | **3 条**：索引 12/15/33 = 端点 `9-11` / `12-13` / `25-26` |
| LODF 对角 None 列 | **恰为 12/15/33** |
| None 总数自洽 | **3 × 41 = 123** 精确 |
| LODF 对称性 | 不对称（1144/1444），**符合理论** |
| PTDF slack 列 | 全 0（max = 0.000e+00） |
| **并联支路互为相反数** | ⚠️ **case30 无并联支路，不可测** |

**对角线必为 −1 的证明**：`ΔP_k = LODF_kk × P_k`，开断后自身潮流归零故 `ΔP_k = −P_k` ⟹ `LODF_kk = −1`。
**与拓扑/阻抗/容量无关**，任何正确实现都必须精确成立。

**123 个 None 的物理含义**：桥支路开断 → 网络解列为孤岛 → 潮流再分配无定义 →
该 outage **整列 41 格全部为 None**（不只是桥自己）。

## 1.5 N-1 扫描

```
扫描场景 41 · 有越限 32 · 越限条目 56 · 无需筛选(n_screened_out=0) · 全部收敛
类型: ThermalOverload 36 · VoltageLow 17 · Islanding 3
```

**⚠️ 判据陷阱**：过载判据用 **MVA**（`flow_mva/limit_mva`），非 MW。

| 支路 | flow_mw | flow_mva | limit | 负载率 | 若误用 MW |
|---|---:|---:|---:|---:|---:|
| 8–28 | 31.41 | **45.59** | 32.0 | **142.47%** | 98.16% ← **误判为正常** |

**6–8 走廊是全网瓶颈**：28 个过载场景中 **23 个**与它相关；基态它已 111.83%。

**Islanding 的 3 个断号（branch_12/15/33）与前述图论桥精确重合** —— 拓扑/代数/AC 仿真三条独立路径同结论。

## 1.6 缓解手册应用

`6–8` 走廊承载的**母线 8 是全网最大负荷点（30 MW），却只有 2 条支路供电**，唯一备用通路 8–28 额定仅 32 MVA。

| 手册 | 步骤 | 本案结论 |
|---|---|---|
| `voltage-violation-mitigation` | 用现有无功资源 | ⚠️ **无变压器/无 SVC**，仅剩机组 vg 与 2 个并联补偿（且都不在越限母线附近） |
| `thermal-overload-mitigation` | 再调度 | ❌ 需 **72.7 MW**（占系统负荷 38.4%），G27 上调裕度仅 28.09 MW → 最多降到 126.06% |
| 同上 | 拓扑重构 | ❌ **无可选项**（母线 8 仅 2 条支路，故障即断其一） |
| 同上 | 移相器/HVDC | ❌ case30 无 |
| 同上 | **加固** | ✅ **唯一可行**：8–28 扩至 ≥48 MVA，或新建并联回路 |
| `contingency-mitigation` | 按走廊归组 | 热稳定集中在 **6–8**（23/28），电压集中在 **母线 18/19** —— **两个薄弱区电气上分离，需分别处理** |

---

# 二、CSEE-FS（BPA 格式）—— 解析失败记录

对象：`GridData/2、CSEE-FS/`（5 个文件：1 个指南 PDF + 2 对 `.DAT`/`.SWI`）

**指南要点**：中国电机工程学会发布的频率稳定算例；500 kV 交流 + ±500 kV 直流；**47 节点 / 31 交流线 / 3 直流线**；
两个场景：`HF、LF`（新能源占比 >50%）与 `ULF`（水电占比 89%）。运行需 **PSD-BPA** 商业软件。

## 两个正交的阻塞（**只解决一个都不够**）

| # | 阻塞 | 实测证据 |
|---|---|---|
| 1 | **PowerIO 不支持 BPA** | `format='bpa'` → `REQUEST.FORMAT.UNKNOWN`；支持列表 17 种，无 BPA/PSD |
| 2 | **文件非 UTF-8** | 四个数据文件实测**全部为 GBK/GB18030、无 BOM**；PowerIO 报 `not valid UTF-8` |

**⚠️ 文件名含中文顿号 `、`**（`HF、LF.DAT`），脚本调用需注意。

**后续路径**（未执行）：BPA → PSS/E RAW 或 MATPOWER 转换。PDSEdit 自身可能支持导出。

---

# 三、文献空白调研（七轮）

## 3.1 被推翻的候选（六条）

| 候选 | 被什么占据 |
|---|---|
| 不确定性量化 | 通用层 **8+ 篇**（ICML/ACL 2026）；电力层 IEEE 2026 直接重叠；PowerAgentBench-Dyn 已定义"概率可复现性" |
| 静默失效分类 | `AutoAgent`（2026-06）已量化："自评 100% 正确 vs 实际 0–70%" |
| 技能组合形式化 | 通用层 **7+ 篇**（arXiv 2605.23951 标题即此、SkillSpec、SIGIL、TPA、Behavioral Contracts…） |
| 大网架可扩展性 | `2609.02011` Seed-Anchored（直击 CGMES）等 |
| 人机协同/审批 | 《HITL AI in the energy sector: a systematic review》(**Advances in Applied Energy, 2026-03**) |
| 安全实证验证 | LLM-GridEval (ACM 2026) · TWINGRIDSHIELD · RIFT-Bench |

## 3.2 唯一存活：**MCP 接口**

依据（`2511.14478`，Frontiers in AI 2026 综述）：
> *"…the **lack of official standardized Model Context Protocols (MCPs) from engineering software vendors such as PSS®E, PowerWorld, CDEGS is a major barrier for standardized deployment**. Future research must focus on developing open, stable, and secure standards for agent-tool interaction…"*

**引用图验证**：该文被引 **0**；母论文 PowerAgent 路线图（IEEE P&E Magazine 2025）被引 **11**。
遍历母论文的 11 篇引用者 + 其他 4 个锚点共 **144 篇唯一引用者**：

| 主题 | 引用者中篇数 |
|---|---:|
| 基础模型/微调 | 50 |
| 调度/运行 | 25 |
| 规划/优化 | 22 |
| RAG/检索 | 21 |
| **技能/工具/编排** | 14 |
| **人机协同** | **2** |
| **可解释/审计** | **3** |

**摘要级复核**：母论文引用的 11 篇中，摘要提及 MCP 的**仅 1 篇**（Grid-Orch）、提及 skill 的**仅 1 篇**。

**⚠️ 但两个局限必须记住**：
1. **"0 引用"部分源于时间** —— 该空间 72 篇绝大多数是 2026 年论文，被引 0 属正常滞后
2. **MCP × 电力全空间仅约 10–12 个去重工作**，全部 2026 年
3. **建筑能源领域的 MCP 更成熟**（EnergyPlus-MCP 被引 **24** vs 电力最高 11）

## 3.3 方法演进（三轮迭代）

| 轮次 | 方法 | 结果 |
|---|---|---|
| 1 | 关键词检索 | ❌ **七轮错六轮** |
| 2 | 从论文引文链出发 + future work 系统提取 | ⚠️ 找到议程但**高频≠空白**（高频是"热门延伸"） |
| 3 | + OpenAlex 引用图遍历（锚点说的 vs 引用者做的差集） | ✅ **差异化最大** |

**关键方法论教训**：
- **单轮关键词检索 ≠ 新颖性证明**（前作用不同词，说 "energy sector" 而非 "power system"）
- **权威工具给的否定性证据也可能错**（曾据"no source focuses on…"误判 HITL 仍开放）
- **"自己社区已占" = 自证新颖性风险**（Power-Agent 生态的候选可能已被本社区占据）

---

# 四、技能交付：`finding-research-gaps`

**位置**：`C:\Users\Z\.claude\skills\finding-research-gaps\`（全局，**未提交到任何仓库**）

```
SKILL.md          699 词 · description 290 字符
scripts/
  openalex.py     引用图查询（search/find/cites/abstract）
  arxiv_gaps.py   全文抓取 → future work 提取 → 空白句聚合
```

**走了完整的 RED-GREEN-REFACTOR**：

**RED**（两个无技能基线）暴露了 4 个失败点，其中两个**是我自己没发现的**：
- 基线 A 指出我的 `futurework.json` **约 1/3 是结论段而非 future work 段** → 已修：提取时打 `prospective`/`retrospective` 标签
- 基线 B 指出**自证新颖性风险**

**GREEN**（带技能重跑）通过，agent 主动应用了技能里的具体规则（选无 "power system" 的锚点、识别高频陷阱、识别引用滞后）。

**REFACTOR** —— GREEN 的 agent 找到了技能**没覆盖**的失败模式：
> *"OpenAlex 匿名限流会返回『命中 0』，看起来像空白实则不是"*

实测确认后做了两层修复（文档 + 代码退避重试）。**修代码时我自己又犯了一次同类错误**（提前 return 跳过警告打印）。

---

# 五、产物索引

| 路径 | 内容 |
|---|---|
| `work/case30/` | IR、两侧潮流原始结果、surge 矩阵与 N-1 结果 |
| `work/fw/` | 112 篇语料库、97 篇全文、143 个章节、234 条空白句、可复现脚本 |
| `work/cite/` | 254 个锚点、5 锚点 × 144 引用者遍历结果 |
| `work/lit/` | 三篇 PowerAgentBench 论文全文与 52 条参考文献 |
| `C:\Users\Z\.claude\skills\finding-research-gaps\` | 交付的技能 |

---

# 六、未决 / 待办

- [ ] **MCP 接口方向的下一步未定** —— 是"把'标准应满足哪些性质'做成可研究问题"，还是继续找别的候选
- [ ] 技能的限流保护路径**未在未限流状态下端到端验证**（写入时正被限流）
- [ ] CSEE-FS 的 BPA → RAW/MATPLOWER 转换路径未调研
- [ ] case30 的 21–22 走廊（7 个场景）未做独立灵敏度分析
- [ ] `PowerMCP/fix/pandapower-deepcopy` 与 `PowerSkills/fix/pypsa-pandapower-api-drift` 两个分支仍在等待（后者 PR #8 OPEN）
