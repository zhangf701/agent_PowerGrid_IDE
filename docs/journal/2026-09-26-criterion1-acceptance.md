# 判据 #1 验收：一个新算例跑通全流程（A–C 阶段）

日期：2026-09-26 ｜ 依据：方案 v4 §十二 判据 #1 ｜ 流程定义：`PowerMCP与PowerSkills_能力与场景总结.md` 附录 A
前置：P1 的四个视图（① 环境就绪 · ② 算例库 · ③ 对话分析 · ⑤ 技能手册）已全部迁移完成。

> **判据原文**：一个新算例能跑通全流程 —— 从 `D:\GridData` 取一份**未处理过**的算例，
> 走完 **13 步的 A–C 阶段**，**无人工改脚本**。

## 一、算例与入口

| 项 | 值 |
|---|---|
| 算例 | `GridData/MatpowerData/case118.m`（33696 B，**从未登记、从未解析过**） |
| 登记 id | `ac7ae93e8478` |
| 入口 | 网关 HTTP（与 React 界面同一套端点）—— **无任何自定义脚本** |
| 阶段 A–C | 步骤 1–3 环境就绪 · 4–5 算例解析 · 6–7 基态与校验 |

## 二、逐步结果

### A 环境就绪（步骤 1–3）

| 步骤 | 做法 | 结果 |
|---|---|---|
| 1 环境预检 | `GET /environment` | 网关 `Python 3.12.6` ✓ · LLM `deepseek-chat` ✓ · 路径围笼 2 个根 ✓ · 选题模块 2 个 ✓ |
| 2 能读算例 | `GET /cases` 的 `within_allowed_roots` | `case118.m` → **true** ✓ |
| 3 工具面 | `GET /contracts/t0`（约 92 s） | 已挂载 server + 工具面计数；`summary.primary = incident`（**opendss 无法经 SDK 挂载**，已知阻塞）· `structural_unknown = 12` |

> 附录 A 的免责声明要求「每步执行前以 `list_tools` 实际返回为准」—— 本轮的**实际工具名**由对话流里的
> `tool_call` 帧给出（见步骤 4/6/7），与文档写法一致。

### B 算例解析（步骤 4–5）

| 步骤 | 做法 | 结果 |
|---|---|---|
| 4 解析为 IR | `POST /cases/{id}/parse` | `tool = powerio.parse` · `value_type = **powerio.BalancedNetwork**` · `ir_bytes = 224425` · `has_ir = true`（2.85 s） |
| 4 schema/version | `GET /cases/{id}/ir` | `schema = pio-ir` · `version = 2` · `producer = powerio 0.11.3` |
| 5 摘要 | 同上 | **118 母线 / 186 支路 / 54 机组 / 99 负荷**；3 绕组 0 · 开关 0 · 储能 0；`source_format = matpower` |
| 5 诊断 | `GET /cases/{id}/diagnostics` | `stale = false` · **`ok: no diagnostics`**（error/warning/remark/note 全 0） |

⇒ **无 error 级问题**，算例可用，可继续（符合附录 A 步骤 5 的判定要求）。

### C 基态与校验（步骤 6–7）

**步骤 6 —— 基态潮流（pandapower）**，经 `POST /sessions/{sid}/chat`（对话路径）：

```
tool_call  pandapower.load_network_from_any  {file_path: ...case118.m, source_format: "matpower"}
tool_call  pandapower.run_power_flow         {algorithm: "nr", calculate_voltage_angles: true}
```

| 项 | 结果 |
|---|---|
| 是否收敛 | **是** |
| 最低电压 | `0.943 p.u.` @ 母线 110（内部索引 109） |
| 最高电压 | `1.050 p.u.` @ 母线 96（内部索引 95） |
| 最重载线路 | **给不出负载率** —— `loading_percent` 全为 `Infinity`（见下「核对」） |

**步骤 7 —— 跨引擎交叉验证（PyPSA vs surge）**：

| 指标 | PyPSA | surge | Δ |
|---|---|---|---|
| 最低电压 | `0.943` @ 母线 76（Darrah V2） | `0.9430000` @ 母线 76 | `0.00e+00 pu` |
| 最高电压 | `1.050` @ 母线 10 等 4 处 | `1.0500000` @ 母线 10/25/66 | `0.00e+00 pu` |
| 全母线 **Δmax** | — | — | **`2.0e-06 pu`**（母线 9） |

★ 模型**主动按母线名称对齐、而非字面索引比对**，并逐引擎标注了编号约定
（PowerIO/MATPOWER/surge `1-based`；pandapower/PyPSA `0-based`）——
正是 §4.5 `Identifier` 要防的那个「字面比对把偏差放大 3.1 亿倍」。

## 三、★ 核对（不凭模型一句话就接受）

| 模型的声明 | 我的独立核对 | 结论 |
|---|---|---|
| 「case118 的 rating 为 0，无法给出负载率%」 | 直接查 IR：**186 条支路 `rate_a` 唯一值只有 `0.0`** | ✅ **属实** —— MATPOWER 官方 case118 **未给热极限**。模型**没有编数字**，如实说"无法给出" |
| 「PyPSA 丢弃 54 个机组无功限值」 | IR 里 54 个机组 `qmax/qmin` **齐备** ⇒ 丢弃发生在**引擎侧**（PyPSA 发电机无 q 上下界） | ✅ **属实**，且是**引擎能力差异**而非数据缺失 |

**⇒ 本算例（case118）不能用于「最重载线路 / 热极限」类分析** —— 这是一条**算例级事实**，
不是工具缺陷。任何基于它的负载率结论都是无依据的。

## 四、结论

**判据 #1：A–C 阶段（步骤 1–7）全部走通，无人工改脚本 ⇒ 达标。**

| 阶段 | 步骤 | 达标 |
|---|---|---|
| A 环境就绪 | 1–3 | ✅ |
| B 算例解析 | 4–5 | ✅ |
| C 基态与校验 | 6–7 | ✅ |

跨引擎一致性：**Δmax = 2.0e-06 pu**。
⚠️ **不得声称"机器精度"** —— 该量级与 case39 那次（`6.98e-11 pu`，同 IR 往返）**差 5 个数量级**，
且 PyPSA 导入时**显式报出两处保真度损失**（54 机组无功限值、2 条支路并联导纳折叠）。
差异**有可解释来源**，但**不足以宣称两引擎等价**。

## 五、过程中暴露的 4 条（如实记录）

| # | 现象 | 性质 | 建议 |
|---|---|---|---|
| 1 | 步骤 7 时模型**重新 parse 了算例**，未复用步骤 4 的 IR | 提示词/上下文问题（附录 A 步骤 4 明确要求"不要重新解析"） | 算例上下文注入里补一句「已解析的算例请复用产物，勿重新 parse」 |
| 2 | `pypsa.import_case_from_any` 往 `GridData/MatpowerData/` **写了 `case118_pypsa.nc`**（157 KB） | 工具副作用（在允许根内，**合法**），但用户需知情 | 界面在工具轨迹里显式标出「产生文件：…」（现只在 args 里可见） |
| 3 | 本轮**契约事件 0 条** | 好结果 —— 参数全对，校验层无告警 | — |
| 4 | 我的证据流捕获不完整（后台 curl `-m 200` 早于第二轮结束） | **测量工件**，非产品缺陷 | 下次捕获用更长超时或按需重连 |

## 六、留存的验收产物

| 产物 | 位置 | 处置 |
|---|---|---|
| 算例登记 | 算例库 id `ac7ae93e8478` | **保留**（判据 #1 的证据） |
| 解析产物 | `~/.powermcp_gateway/cases/ac7ae93e8478/parse.json` | 保留 |
| `case118_pypsa.nc` | `GridData/MatpowerData/`（工具副作用，`.gitignore` 覆盖） | 保留（可复现 PyPSA 侧） |

**提交**：本轮验收**未产生代码改动**（纯验收），故无新增提交；
`examples/` 仍未纳入版本控制（历史待决项，未动）。
