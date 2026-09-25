# 选题模块 —— 两个真实模块 + 扩展点验证结论

> **本目录是「先做 2 个真实模块验证扩展点，再冻结接口」那一步的产物**
> （[模块化架构 §八-1](../docs/PowerMCP_前端模块化架构.md) 的风险缓解措施）。
> 两个模块不是为了"能跑"，而是为了**逼出清单表达不出来的东西**。

## 一、两个模块

| 模块 | 选题 | 成熟度 | 实测素材 |
|---|---|---|---|
| `n1-ranking` | N-1 关键故障排序与可复现研究 | **L1** | 科研场景 1：46 场景 / 23 越限 / Top-1 `branch_26` = 161.84%（958.49 MW），`examples/01` |
| `cross-engine-consistency` | 跨引擎一致性与算例转换保真度 | **L1** | 科研场景 4：Δ = 6.98e−11 pu，`examples/02` |

```bash
# 查看装配结果（含校验缺口）
python - <<'PY'
from powermcp_gateway.config import GatewayConfig
from powermcp_gateway.modules import build_report
from powermcp_gateway.skills import build_report as sk
print(build_report(GatewayConfig.discover(),
                   known_skills=tuple(s["id"] for s in sk(GatewayConfig.discover())["skills"])))
PY

# 或起网关后 GET /modules
```

**当前装配结果**：2 个模块 · **0 失败** · **0 警告** · 全部 L1。

## 二、★ 首要结论：L0/L1 **装得下**真实选题

两个模块都**停在 L1**，**没有写一行 UI 组件**（`slots: []`）。

- N-1 排序：工具白名单 + 3 个技能 + 1 个实体 + 1 张结果表 + 2 条自检 + 1 个报告模板
- 跨引擎一致性：14 个工具 + 3 个技能 + 1 个实体 + 1 张结果表 + 2 条自检 + 1 个报告模板

→ **「多数选题零 UI 代码即可开工」这一判断，在两个差异较大的选题上成立。**
（一个单引擎、一个四引擎；一个结果表是窄表、一个是需要 pivot 的长表。）

## 三、扩展点逐项状态（**这是最需要看清的一张表**）

> ⚠️ **「清单支持」≠「能用」**。下表第三列才是"模块今天能不能干活"。

| 扩展点 | 清单支持 | 校验 | **已接线（有行为）** |
|---|:--:|---|:--:|
| `id` / `name` / `version` / `kind` / `maturity` / `enabled` | ✅ | ✅ id 须与目录名一致；kind/maturity 取值合法；**maturity 与实际内容一致（G-8）** | ✅ `/modules` 展示 |
| `requires.core` | ✅ | ✅ 版本判定（无法解析的 spec 一律不满足） | ❌ |
| `requires.servers` | ✅ | ⚠️ 已知清单告警 + **与 `tools` 前缀的一致性（G-7）** | ❌ |
| `requires.solvers` | ✅ | ❌ 无校验 | ❌ |
| `tools` | ✅ | ✅ **前缀须被 `requires.servers` 覆盖（G-7）**；未知 server 告警（G-9） | ❌ 软收窄**未实装** |
| `skills` | ✅ | ⚠️ 仅「是否存在」 | ❌ 技能手册未按模块过滤 |
| `sample_cases` | ✅ | ⚠️ 仅类型（运行时数据，不做存在性校验） | ✅ `/modules` 展示（G-1） |
| `entities` | ✅ | ✅ 文件必须存在 + 跨模块同名禁止 | ❌ 无实体存储 |
| `result_tables` | ✅ | ✅ 同上 + **`columns_source` 类型（G-2）** | ❌ 无结果表存储 / 渲染 |
| `prompts` | ✅ | ✅ 文件必须存在 | ✅ **`/chat` 每轮并入 system 消息（G-4 最小闭环）** |
| `checks` | ✅ | ✅ 文件必须存在 + **`result_table` 绑定（G-5）** | ✅ **`POST /checks/run` 执行引擎（G-4 最小闭环）** |
| `exports` | ✅ | ✅ 文件必须存在 | ❌ **无渲染器** |
| `slots` | ✅ | ⚠️ 未知槽位名告警（G-10；清单未冻结故不拒绝） | ❌ 前端未起步 |

**一句话**：**清单层完备，校验层基本齐备，行为层最小闭环**（prompts / checks 已接线；
工具软收窄、技能过滤、结果表存储、exports 渲染、slots 注入仍未做）。
`/modules` 的 `summary` 会显示 `enabled: 2` —— **那不等于"这两个模块已经能干活了"**，
但 `/chat` 会读模块提示词、`POST /checks/run` 能跑模块自检了（2026-09-25 起）。

## 四、发现的扩展点缺口（10 条，含 4 条实测复现）

> 复现脚本：`.superpowers/sdd/m15-module-gaps.py`（4 条校验缺口逐条实测）

### ✅ 已裁决并落地（2026-09-25，张老师四项裁决）

| # | 缺口 | 裁决与落地 |
|---|---|---|
| **G-1** | 没有「默认算例」字段 | ✅ 加 `sample_cases` 字段（指向算例库 id 或路径；运行时数据，装配期不做存在性校验）；两个真实模块已声明 `examples/data/case39.m` |
| **G-2** | 静态列表达不了「每引擎一列」 | ✅ 加 `result_tables[].columns_source` 字段（值 = 展开维度列名，如 `engine`；pivot 渲染归内核）；字段已可用，内核渲染实现归 P1 |
| **G-4** | prompts / checks / exports 声明了却无行为 | ✅ **最小闭环**：`/chat` 并入模块提示词 + `POST /checks/run` 执行引擎。exports 渲染器排后 |
| **G-5** | checks 契约未定义 | ✅ 契约冻结第一版：`check(ctx) -> list[str] \| list[dict]`（ctx 含 rows/result_table/module_id/case/case_id）+ 模块级 `RULE_ID` / `SEVERITY`；`checks[].result_table` 绑定结果表（**绑定键不叫 `on`** —— YAML 1.1 把裸 `on` 解析成布尔值，绑定会静默失效）。契约全文见 `gateway/src/powermcp_gateway/checks.py` 模块 docstring |

### ✅ 校验缺口（4 条曾实测确认"拦不住"，**已于 2026-09-25 修复**）

> 实测复现保留（`.superpowers/sdd/m15-module-gaps.py`），作为"修复前确实拦不住"的证据链。

| # | 缺口（修复前实测） | 修复后行为 |
|---|---|---|
| **G-7** | `servers: [surge]` + `tools: [pypsa.optimize_network]` → **装配成功，无提示** | 清单**自相矛盾 → 装配失败**；有 `tools` 却未声明 `requires.servers` → 警告提示补声明 |
| **G-8** | `maturity: L0` 却填了 `entities` → **装配成功** | `L0` 含 `entities`/`result_tables`/`slots` → **装配失败**；`L2` 无 `slots` → **装配失败** |
| **G-9** | `tools: [不存在的server.某工具]` → **无警告** | `tools` 前缀引用未知 server → **警告** |
| **G-10** | 写任意槽位名都通过（前端注入时会静默失效） | 未知槽位名 → **警告**（槽位清单尚未冻结，暂不拒绝；已知槽位 = `SLOT_NAMES` 五个） |

**修复**：提交 `95c849d`（+14 条测试）；变异探针 `.superpowers/sdd/m19-g710-mutation.py` **5/5 全红**；
护栏测试 `test_real_modules_pass_the_new_rules` 保证两个真实模块不被新规则判死。

### 🔵 记录即可（不阻塞）

| # | 缺口 | 建议 |
|---|---|---|
| **G-3** | 「软收窄」目前只是 `/modules` 的 `notes` 文案，**清单层无字段** | 若将来要做硬白名单，需加 `enforcement: soft \| hard`；当前保持软收窄 |
| **G-6** | `entities` 与 `result_tables` 是**平行列表**，看不出"输入 → 输出"关系 | 可选：给 `result_tables[]` 加 `produced_from: <entity_id>`，让界面能"从实体跳到结果表" |

## 五、这次验证**没有**发现的

- ❌ 没有出现"清单表达不了某个选题"的情形 —— 两个选题都能完整声明。
- ❌ 没有出现"必须写 UI 组件"的情形 —— 两个模块都停在 L1。
- ❌ 没有出现跨模块声明冲突（两个模块的实体/结果表 id 天然不重名）。

→ **对「L0/L1 够用」这一判断，本次是两个正面证据。** 但样本只有 2 个，
且都来自同一个文档的既有场景；**更多样化的选题仍可能逼出新缺口**。

## 六、给下一步的建议

1. ~~先裁决 G-1 / G-2 / G-4 / G-5~~ → **✅ 已裁决并落地**（2026-09-25，见 §四）。
   剩余：exports 渲染器、工具软收窄实装、技能按模块过滤、结果表存储与渲染（含 G-2 的 pivot）。
2. **不要现在冻结清单 schema** —— G-4/G-5 一旦动手，`checks` / `prompts` / `exports`
   的形状很可能要改，届时已写的 4 个 check 需要同步。
3. ~~G-7/G-8/G-9/G-10 是低成本的校验补强~~ → **✅ 已完成**（2026-09-25，提交 `95c849d`）。
