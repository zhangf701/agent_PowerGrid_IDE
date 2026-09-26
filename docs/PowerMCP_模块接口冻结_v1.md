# PowerMCP 模块接口冻结 v1

> 2026-09-26 · 依据：方案 v4 §十（P1.5）· 模块化架构 §四 / §六 / §七 / §八-1
> 目的：**验证扩展点后冻结接口与槽位清单**，避免「只有 2–3 个模块时猜错抽象」。
> 本文档是 P1.5 的交付物 —— 它同时给出**冻结什么**与**明确不冻结什么（及原因）**。

---

## 一、判据：什么算「验证过」

| 级别 | 含义 |
|---|---|
| ✅ **已验证** | 有 **≥2 个真实模块**的实际使用 + 端到端可复现证据 |
| ⚠️ **部分验证** | 有 1 个模块使用，或有字段但无运行时行为 |
| ❌ **未验证** | **零使用** / 前端未实现 / 无运行时消费者 |

★ **冻结的前提是「已验证」**。未验证就冻结，等于把猜测固化成契约 —— 那正是 §八-1 要防的。

## 二、冻结结论一览

| # | 项 | 级别 | 冻结结论 | 依据 |
|---|---|---|---|---|
| 1 | 模块清单字段集 | ✅ 已验证 | **冻结 v1** | 2 个真实模块全覆盖 |
| 2 | `requires.core` 版本约束 | ✅ 已验证 | **冻结 v1** | 2 模块均用 `>=0.1`；`satisfies()` 已实装 |
| 3 | 装配与冲突规则 | ✅ 已验证 | **冻结 v1** | G-7/G-8/G-9/G-10 已修并测试 |
| 4 | `checks` 契约 | ✅ 已验证 | **冻结 v1** | G-5 已冻结；`/checks/run` 已交付 |
| 5 | 后端端点形状 | ✅ 已验证 | **冻结 v1** | `/modules` · `/checks/run` · `/chat` 提示词并入 |
| 6 | ★ **5 个槽位** | ❌ **未验证** | **不冻结（保持草案）** | **两模块 `slots: []`，零使用**；前端无注入位 |
| 7 | ★ **前端 `kernel.*` 6 个接口** | ❌ **未验证** | **不冻结** | 前端**完全未消费 `/modules`** |
| 8 | `exports` 渲染器 | ⚠️ 部分 | **不冻结** | 字段已声明，**渲染器未实现** |
| 9 | 结果表存储 / 渲染 | ⚠️ 部分 | **不冻结** | 列定义已可用，**无存储与渲染** |

---

## 三、已冻结 v1（详）

### 3.1 模块清单字段集

`modules/<id>/module.yaml`。**字段名与取值一经冻结，变更须走 §六 流程。**

| 字段 | 类型 | 必填 | 冻结的值域 / 约束 |
|---|---|:--:|---|
| `id` | str | ✅ | **须与目录名一致**；不得用 `on`/`off`/`yes`/`no`（YAML 会解析成布尔值） |
| `name` | str | ✅ | 显示名 |
| `version` | str | ✅ | 模块自身版本 |
| `kind` | str | ✅ | 现取值 `research` |
| `maturity` | str | ✅ | `L0` / `L1` / `L2`；**须与实际内容一致**（L0 不得含 `entities`/`result_tables`/`slots`；L2 必须有 `slots`）—— G-8 |
| `enabled` | bool | ✅ | 可单独禁用而内核仍可用（**自证条件**） |
| `requires.core` | str | — | 版本约束，见 §3.2 |
| `requires.servers` | list[str] | — | 未知 server **仅告警**（G-9）；**必须覆盖 `tools` 的全部前缀**（G-7，否则装配失败） |
| `requires.solvers` | list[str] | — | |
| `tools` | list[str] | — | **软收窄**（推荐工具集，非硬白名单）；工具名须取自 `list_tools` **真实返回** |
| `skills` | list[str] | — | 未知 skill **仅告警** |
| `sample_cases` | list[str] | — | **默认算例**（G-1）。运行时数据，**装配期不做存在性校验** |
| `entities[].id` / `.schema` | str | — | schema 文件必须存在，否则装配失败 |
| `result_tables[].id` / `.columns` / `.metrics` | — | — | 同上；`columns_source` 见 §3.3 |
| `prompts[].id` / `.file` | str | — | 文件必须存在 |
| `checks[].id` / `.file` / `.result_table` | str | — | 文件必须存在；`result_table` 绑定结果表；**绑定键不得叫 `on`** |
| `exports[].id` / `.template` | str | — | 文件必须存在（**渲染器未实现**，见 §4.3） |
| `slots` | list | — | **未冻结**，见 §4.1；未知槽位名**仅告警**（G-10） |

### 3.2 `requires.core` 版本约束

- **内核版本**：`CORE_VERSION = "0.1.0"`（`modules.py`，网关自身版本）
- **语法**：`>=` / `==` / `<=` / `>` / `<`，**缺省视为 `>=`**
- ★ **无法解析的 spec 一律视为「不满足」**（fail-loud，**不默认放行**）
- 两个真实模块均写 `>=0.1` ⇒ 语义为「不早于 0.1 的清单 schema」

> 刻意**不引入 `packaging`**：清单只需表达「不早于某版本」，为此加依赖不划算。

### 3.3 装配与冲突规则

| 项 | 规则 | 状态 |
|---|---|---|
| 扫描 | 内核启动扫描 `modules/*/module.yaml` | ✅ |
| 工具白名单 | 多模块**取并集** | ✅ |
| 技能子集 | 多模块**取并集** | ✅ |
| 实体 / 结果表**同名** | ❌ **禁止** —— 报错并**拒绝后者**（不静默覆盖） | ✅ |
| 槽位 | 多模块可注入同一槽位，按 `order` 排序 | ⚠️ 规则冻结，**但槽位本身未冻结** |
| 模块失败 | **fail-loud**：失败模块标记不可用并在环境视图显示，**不影响内核与其他模块** | ✅ |
| `columns_source` | 值 = 展开维度列名（如 `engine`）；**pivot 渲染归内核**（G-2） | 字段可用，渲染未做 |

**★ 自证条件（内核未被领域知识污染）**：模块根**不存在 / 为空 / 全部装配失败 / 全部禁用**
四种状态下，内核端点全部正常；且内核端点响应里**不得出现任何模块 id**。

### 3.4 `checks` 契约（引用冻结）

`check(ctx) -> list[str] | list[dict]`；`ctx` 含 `rows` / `result_table` / `module_id` / `case` / `case_id`；
模块级 `RULE_ID` / `SEVERITY`。**契约全文见 `gateway/src/powermcp_gateway/checks.py` 模块 docstring**（单一真源）。

### 3.5 后端端点（已冻结的形状）

| 端点 | 响应顶层键 |
|---|---|
| `GET /modules` | `root` · `root_exists` · `core_version` · `summary` · `effective` · `modules[]` · `failures` · `notes` |
| `GET /modules` 的 `modules[]` 单项 | `id` · `name` · `version` · `kind` · `maturity` · `enabled` · `path` · `servers` · `solvers` · `tools` · `skills` · `sample_cases` · `entities` · `result_tables` · `prompts` · `checks` · `exports` · `slots` |
| `POST /checks/run` | 请求 `{module_id, rows, case?, case_id?}`；响应含 `summary{checks_run, checks_skipped, check_errors, findings_total, by_severity}` · `results[]` · `skipped[]` |
| `POST /sessions/{sid}/chat` | 模块 `prompts` **每轮并入 system 消息**（G-4 最小闭环） |

---

## 四、★ 明确不冻结（及原因）

### 4.1 5 个槽位 —— **零使用，不冻结**

```yaml
# 两个真实模块的实际情况
n1-ranking:                slots: []
cross-engine-consistency:  slots: []
```

| 槽位 | 设计位置 | 真实使用 |
|---|---|---|
| `nav.extra` | 主导航 | **0** |
| `case.detail.tabs` | 算例详情页 | **0** |
| `chat.result.after` | 对话结果之后 | **0** |
| `experiment.result.columns` | 实验结果表 | **0** |
| `verification.extra` | 校验层 | **0** |

**追加事实**：前端**没有任何槽位注入位**（`grep slot frontend/src` → 0 命中），
且**完全未消费 `/modules`**（只在 `/environment` 里读 `modules.enabled/failed`，那是环境视图用的）。

⇒ **§八-1 的冻结前提对 L2 未满足**。两个模块都是 **L1**，证明的是
「**L0/L1 装得下真实选题**」（这本身是有价值的结论），
而**没有验证任何一个 L2 槽位**。此时冻结槽位 = 把猜测固化成契约。

**触发冻结的条件**（满足任一条即可启动槽位冻结）：
1. 出现**第一个真实的 L2 需求**（某选题确实需要写领域视图组件）；
2. 或前端先落地**至少一个槽位的注入位**（此时可冻结该槽位，其余仍为草案）。

**建议的验证方案**（届时执行，成本可控）：写一个**最小 L2 模块**——
只多一个 `slots: [{slot: chat.result.after, order: 10, component: ...}]`，
把「N-1 排序表」以领域卡片形式注入对话结果之后。验证点：
① 组件能否只经 props + `kernel.*` 拿数据（§八-2 的隐性耦合风险）；
② 多模块注入同一槽位的 `order` 排序是否如预期；
③ 内核在模块被禁用后是否仍可用（自证条件）。

### 4.2 前端 `kernel.*` 6 个接口 —— **未实现，不冻结**

架构 §六 列了 6 个接口（`kernel.tools.call` / `.cases.*` / `.events.subscribe` /
`.results.write` / `.export.render` / `.checks.register`）。**前端当前一个都没有** ——
前端还没有「内核层」，视图直接调 `apiParsed()`。

⇒ 冻结一个**尚不存在**的接口没有意义。**待前端落地内核层时再冻结**。

### 4.3 `exports` 渲染器 · 结果表存储与渲染

- `exports`：字段已声明且校验（模板文件必须存在），但**渲染器未实现**（G-4 明载「排后」）；
- `result_tables`：列定义可用，但**无结果表存储、无渲染**（`/checks/run` 的 `rows` 由调用方提供）。

⇒ 二者的**运行时契约**（数据形状、渲染入口）尚未成型，不冻结。

---

## 五、版本策略（冻结项的变更规则）

| 变更类型 | 处理 |
|---|---|
| **新增可选字段** | 次版本 +1；旧模块**无需改动**（向后兼容） |
| **新增必填字段** | 主版本 +1；须提供迁移说明与过渡期 |
| **改字段语义 / 值域收窄** | 主版本 +1；须给出受影响模块清单 |
| **删除字段** | 主版本 +1；须先标记 deprecated 一个次版本 |
| **槽位（未冻结）** | 冻结前可自由变更，**但须记录在 §四** |

`CORE_VERSION` 与清单 schema 版本**同号演进**（当前 `0.1.0`）。

---

## 六、冻结的**证据基础**（可复核）

| 证据 | 位置 |
|---|---|
| 2 个真实模块 | `modules/n1-ranking/module.yaml` · `modules/cross-engine-consistency/module.yaml` |
| 校验实现 | `gateway/src/powermcp_gateway/modules.py`（`CORE_VERSION` / `satisfies` / 装配与冲突） |
| checks 契约单一真源 | `gateway/src/powermcp_gateway/checks.py` 模块 docstring |
| 缺口清单与实测复现 | `modules/README.md` · `.superpowers/sdd/m15-module-gaps.py` |
| 10 条缺口的处置 | G-1/G-2/G-4/G-5 → `2026-09-25-g1-g5-wiring.md`；G-7~G-10 → `2026-09-25-module-g7-g10-hardening.md` |
| 内核自证条件 | `/modules` 在四种模块根状态下的行为（已测） |

---

## 七、结论

**P1.5 部分完成 —— 分两半说清楚：**

| 半 | 结论 |
|---|---|
| **L0/L1 接口** | ✅ **已冻结 v1**（字段集 / 版本约束 / 装配规则 / checks 契约 / 后端端点）—— 有 2 个真实模块与端到端证据 |
| **L2 槽位与前端内核接口** | ❌ **未达冻结条件**，**保持草案** —— 零使用、前端未实现；**冻结它就是把猜测固化成契约** |

★ **这不是失败，而是 P1.5 想得到的那个答案**：两个真实选题**都用 L1 装下了**，
说明 L1 的表达力足够覆盖它们；**L2 目前没有真实需求**。
按 §八-1 的原意，**没有需求就不该冻结**。

**建议**：接受「L0/L1 冻结、L2 草案」，把槽位冻结**推到第一个真实 L2 需求出现时**
（届时按 §4.1 的最小验证方案执行）。**不为了冻结而造一个假需求。**
