# 2026-09-27 — case39 跨引擎 7e-3 pu 差异根因结题：surge 是 distributed slack

> 状态：✅ **根因定位并实锤**（复现误差 6.8e-09 pu，机器精度级）
> 脚本：`.superpowers/sdd/m35-cross-engine-param-diff.py`（四臂参数 diff）·
> `m36-injection-diff.py`（逐母线注入差）· `m37-mismatch-check.py`（统一 Ybus 失配检验）
> 证据：`work/xengine-diff/`（四臂原始数据 + ppc）

## 结论一句话

**surge 的 AC 潮流是 distributed slack（分布平衡）**：它把全网功率失配均匀分摊给
**全部 10 台机组**（每台 +69.5995 MW），而不是按 MATPOWER/pandapower 标准语义让
slack 母线（bus31）独自承担（677.87 MW）。两引擎解的不是同一个功率分配问题——
7e-3 pu 的 PQ 电压差异是**真实且语义级**的。

## 决定性验证

把本地 pandapower（from_ppc 直读原文）的 10 台机组 **Pg 各 += 69.5995 MW** 后跑潮流：

| 对比 | Δmax |
|---|---|
| pp 直读解 vs surge 解 | 7.1786e-03 pu @ bus 15 |
| **pp（每台 Pg+69.5995）vs surge 解** | **6.787e-09 pu（逐位吻合）** |

即：surge 的解 == 「原网络 + 每台机组 69.6 MW」在 pandapower 下的解。

## 排除链（每步都有实测证据）

1. **IR 无辜**：原文 .m ↔ powerio IR 四臂参数逐项一致（m35，0 差异）——IR 转换无损。
2. **pp 无辜（双路径）**：pp-server（经 IR）与本地 from_ppc 直读原文的解**逐位相同**
   （1.016185@15 等）——IR→pandapower 转换无损，pp 求解标准（nr/1e-8）。
3. **编号口径无辜**：pp 键 +1 对齐在极值与 PV 设定值上全部逐位命中。
4. **f_hz 无辜**：from_ppc 的 b→c 换算自洽，50/60 Hz 解相同。
5. **surge 的解不满足其声明的网络方程**（m37）：统一 Ybus 下，pp 解的 P 失配 = 1e-8
   （脚本口径正确性顺带得证），surge 解在**每台发电机母线**都有 +69.599 MW 的 P 失配
   ——均匀分摊的签名模式。
6. **实锤**：distributed-slack 假设下的 pp 复现误差 6.8e-09。

## 途中更正的两处错误认知

- **模型自述的「surge 参考角在 bus39」是错的**：surge 实际 va 参考 = bus31（va=0.0），
  与 .m 声明一致——结构化通道必要性再次得到证明（转述连参考母线都能报错）。
- **模型自述的「PV 母线 Δ=0」这次是对的**（Δ=0~4.4e-16，全部精确停在 Vg）；
  「收敛容差差异」解释再次被否（1e-8 容差给不出 7e-3）。

## 含义（对选题与工程）

1. **cross-engine-consistency 选题的核心案例**：同一数据、同一 slack 声明，引擎的
   **平衡机语义**可以不同（single slack vs distributed slack）→ 解差异真实、可解释、
   可量化、可复现。这正是「一致性视图必须给 Δ 且必须有意义」的最佳例证。
2. **接口语义契约缺口**：`run_ac_power_flow` 工具没有暴露「平衡机语义」参数/声明——
   两引擎对同名工具的**语义**不同（参数契约验不出，schema 完全一致）。
   属于比「参数可验」更深一层的**求解语义契约**，建议记入接口冻结文档的候选缺口。
3. **实践警示**：跨引擎比对前必须确认平衡机语义；surge 的分布式分摊对
   N-1 / ATC / 损耗研究的影响是系统性的（每台机 Pg 都被改了）。
4. **界面**：CrossEnginePanel 的 Δmax 行判「✖ 不一致」是正确结论，无需改动。

## 遗留

- surge 的 `AcPfOptions`（flat_start/enforce_q_limits/max_iterations/tolerance）
  **没有**关闭 distributed slack 的开关 —— 引擎隐含默认，属上游问题（PowerSkills PR 线）。
- pp 侧 rate_a 经 IR 丢失（不影响潮流解，但影响 N-1/负载率分析）——独立小缺口，
  建议随上游转换问题一并反馈。
