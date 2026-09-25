# 跨引擎一致性报告 —— {{case_label}}

> 由 `cross-engine-consistency` 模块的 `consistency-report` 模板渲染。
> ⚠️ **当前尚无渲染器**（见 modules/README.md 的 findings）。

## 一、算例与转换链

| 项 | 值 |
|---|---|
| 算例 | {{case_label}} |
| 源格式 | {{source_format}} |
| 内容哈希 | `{{case_sha256}}` |
| IR 版本 | {{ir_version}} |

## 二、IR 往返保真度

| 项 | 值 |
|---|---|
| 最大绝对偏差 | {{roundtrip_max_abs_delta_pu}} pu |
| 诊断项 | {{diagnostics_summary}} |

> 实测参考量级：**Δ = 6.98e−11 pu**（机器精度）。若本次显著大于该量级，需先排查转换链。

## 三、逐指标对比

{{result_table:delta_results}}

> ⚠️ **本表为长格式**（每行 = 一个指标 × 一个引擎）。原因见
> `schema/delta_columns.json` 的 `$known_limitation`：`result_tables[].columns`
> 是静态列，无法表达「每引擎一列」的动态列。

## 四、编号约定声明

| 引擎 | 约定 |
|---|---|
| {{engine_conventions}} | |

> 实测：编号约定不一致会把偏差**放大 3.1 亿倍**。本报告的标识符一律按上表解释。

## 五、已知限制（必须随结论一起交付）

- IR → PyPSA 导入**不携带** `q_min_pu` / `q_max_pu`（无功能力限值）。
- 未参与本次对比的引擎：{{not_covered_engines}}。
- 「引擎报错」与「结果不一致」**分开记录** —— 前者是能力问题，后者是数值问题。
