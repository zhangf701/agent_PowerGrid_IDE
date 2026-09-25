# n1-ranking —— N-1 关键故障排序与可复现研究

**成熟度 L1**（数据式）· **零 UI 组件** · 装配 0 失败 0 警告。

> 来源：`docs/PowerMCP与PowerSkills_能力与场景总结.md` 科研场景 1（**已有实测素材**）。
> 实测产出：46 场景 / 23 越限 / 52 条越限；Top-1 `branch_26` = 161.84%（958.49 MW）；素材 `examples/01`（IEEE 39）。

## 内容

| 文件 | 作用 |
|---|---|
| `module.yaml` | 清单：8 个 surge 工具 · 3 个技能 · 1 实体 · 1 结果表 · 2 自检 · 1 报告模板 |
| `schema/contingency_set.json` | 领域实体：一次 N-1 扫描要跑哪些开断、按什么限值判定 |
| `schema/n1_columns.json` | 结果表列定义（`quantity` 列带 unit + criterion；`identifier` 列带 engine） |
| `prompts/n1_scan.md` | 扫描提示词（⚠️ **尚无引擎读取**） |
| `checks/*.py` | 2 条领域自检（⚠️ **尚无执行引擎**）；可单独跑：`python checks/xxx.py` |
| `templates/n1_report.md` | 报告模板（⚠️ **尚无渲染器**） |

## 开工顺序（13 步流程的 A–D 段）

1. **环境就绪** → `GET /environment`（确认 surge 可用、路径围笼含算例目录）
2. **登记算例** → `POST /cases`，再 `POST /cases/{id}/parse` 拿 PowerIO IR
3. **基态** → `surge.run_dc_power_flow`（**不通过就不要做 N-1**）
4. **扫描** → `surge.run_n1_branch_contingency`
5. **归因** → `surge.compute_ptdf` / `compute_lodf`（Top-3）

## 已知陷阱

| 陷阱 | 处理 |
|---|---|
| `Islanding` 类型**无支路定位信息** | 单独标为孤岛，容错而非崩溃（有 check 兜底） |
| 编号约定 | 一律标注 `(1-based)`（surge 约定） |
| 负载率判据 | 必须写 `161.84% (MVA 判据)` —— 判据不同会把 142% 看成 98% |

> ⚠️ 本模块是「验证扩展点」的样本之一，暴露的缺口见 [`../README.md`](../README.md)。
