# N-1 关键故障排序报告 —— {{case_label}}

> 由 `n1-ranking` 模块的 `n1-report` 模板渲染。
> ⚠️ **当前尚无渲染器** —— `exports` 只校验模板文件存在（见 findings 报告）。
> 占位符约定：`{{变量}}` 取标量，`{{result_table:<id>}}` 取结果表。

## 一、算例

| 项 | 值 |
|---|---|
| 算例 | {{case_label}} |
| 来源 | `{{case_source_path}}` |
| 内容哈希 | `{{case_sha256}}` |
| 解析时间 | {{parsed_at}} |
| 引擎 | surge |

## 二、基态

| 指标 | 值 |
|---|---|
| 收敛 | {{base_case_converged}} |
| 最低电压 | {{base_min_vm_pu}} |
| 最高负载率 | {{base_max_loading}} |

> ⚠️ **基态不通过则 N-1 结论无意义** —— 本报告只在基态收敛时出具。

## 三、N-1 扫描结果

{{result_table:n1_results}}

## 四、越限归因（Top-3）

{{top3_attribution}}

## 五、复现说明

- 工具调用与参数：审计流水 `~/.powermcp/audit/audit-{{session_id}}.ndjson`
- 契约快照：{{contract_snapshot}}
- **标识符编号约定**：本报告一律标注 `(1-based)`（surge 约定）。
  跨引擎比对时该约定不一致会把偏差放大 3.1 亿倍。
