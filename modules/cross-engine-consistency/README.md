# cross-engine-consistency —— 跨引擎一致性与算例转换保真度

**成熟度 L1**（数据式）· **零 UI 组件** · 装配 0 失败 0 警告。

> 来源：`docs/PowerMCP与PowerSkills_能力与场景总结.md` 科研场景 4（**已有实测素材**）。
> 实测：母线电压 Δ = 6.98e−11 pu、支路有功 Δ = 2.25e−07 MW（机器精度）；素材 `examples/02`。

## 内容

| 文件 | 作用 |
|---|---|
| `module.yaml` | 清单：14 个工具（powerio + pandapower/pypsa/surge）· 3 技能 · 1 实体 · 1 结果表 · 2 自检 · 1 报告模板 |
| `schema/consistency_run.json` | 领域实体：一次多引擎对比（含 **`identifier_convention` 必填**） |
| `schema/delta_columns.json` | 结果表列定义（**长格式** —— 见下方已知限制） |
| `prompts/cross_engine_compare.md` | 比对提示词（✅ G-4 已接线，注入 `/chat` system 消息） |
| `checks/*.py` | 2 条领域自检（⚠️ **尚无执行引擎**）；可单独跑：`python checks/xxx.py` |
| `templates/consistency_report.md` | 报告模板（⚠️ **尚无渲染器**） |

> ⚠️ 刻意**不声明 `powerio` 技能** —— PowerSkills 的 11 个 tool skill 里没有它
> （它是跨引擎交换基座，不是某个引擎的工作流技能）。声明了会得到「skill 不存在」警告，
> 那条警告本身是有效设计。

## 已知限制（必须随结论一起交付）

| 限制 | 说明 |
|---|---|
| **结果表是长格式** | `result_tables[].columns` 是**静态列**，表达不了「每引擎一列」的动态列，故用「每行 = 指标 × 引擎」。界面需自己 pivot，并排比对可读性差。**记为缺口 G-2** |
| IR → PyPSA 不携带无功限值 | `q_min_pu` / `q_max_pu` 缺失 |
| 「引擎报错」≠「结果不一致」 | 前者是能力问题，后者是数值问题，**必须分开记录** |

## 编号约定（本模块的核心风险）

实测：字面键比对拿错物理元件，**首次误报 0.068 pu**；跨引擎编号约定不一致会把偏差**放大 3.1 亿倍**。
故 `schema/consistency_run.json` 把 `identifier_convention` 列为**必填**，且有 check 兜底。

> ⚠️ 本模块是「验证扩展点」的样本之一，暴露的缺口见 [`../README.md`](../README.md)。
