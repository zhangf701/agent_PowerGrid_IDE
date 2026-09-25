# 跨引擎一致性比对 —— 提示词

> 由 `cross-engine-consistency` 选题模块声明（`prompts[].file`）。
> ⚠️ **当前尚无引擎读取它**（同 `n1-ranking` 的说明）。

## 目的

同一份算例在多引擎下转换与求解后，**结果能保持一致到什么精度**？

## 提示词

```text
对算例 {case_id} 做跨引擎一致性比对，严格按下面顺序：

1. 用 powerio.parse 把它解析为 PowerIO IR（跨引擎统一表示）。
   记录 source_format；用 powerio.diagnostics 检查 IR 本身是否健康。
2. 用 powerio.summarize 取摘要（母线 / 支路 / 机组 / 负荷计数）。
3. 分别在 pandapower 与 pypsa 上载入并跑潮流：
   - pandapower.load_network → run_power_flow
   - pypsa.load_network      → run_power_flow
4. 对每个可比指标（最低电压 / 最大负载率 / 关键支路索引）：
   **并排给出各引擎的值与 Δ**，格式：`Δ = 6.98e-11 pu`。
5. 结果写入 delta_results 结果表；导出用 consistency-report 模板。

**必须遵守的三条**：
- 每个引擎行都要标注 `identifier_convention`（`0-based` / `1-based`）。
  实测：约定不一致会把偏差放大 3.1 亿倍。拿不到就报 unknown，**不得猜**。
- 一致性结论**必须给 Δ 值**，不能只说「一致 / 不一致」。
- 输入必须是**同一份算例**；若中途换了输入，对比结论作废。

## 不要做

- 不要把「引擎报错」当成「结果不一致」—— 前者是能力问题，后者是数值问题，混在一起会得出错误结论。
```

## 已知陷阱（来自实测）

| 陷阱 | 表现 | 处理 |
|---|---|---|
| 编号约定不同 | 0-based vs 1-based，字面键比对拿错元件 | 逐引擎标注约定；首次误报 0.068 pu 即此类 |
| IR → PyPSA 导入不携带无功限值 | `q_min_pu` / `q_max_pu` 缺失 | 在报告里显式声明该限制 |
| 只报「一致」不报 Δ | 无法判断精度 | 强制给 Δ（有 check 兜底） |
