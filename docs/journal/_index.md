# Journal 索引

本目录收敛本项目的技术文档：研究日志、扫描报告、设计 spec、handoff。

**新对话开始时请先读本文件回溯历史。**

---

## 文档列表（倒序）

### 🚩 2026-09-27 — HANDOFF（**P2 实验矩阵功能闭环：定义 → 执行 → 结果表 → 导出**）★ 最新
📄 [handoff_2026-09-27_p2-experiments-complete.md](handoff_2026-09-27_p2-experiments-complete.md)

**接手先读这篇**。状态：实验矩阵**网关侧已全部交付**（①a 定义层 · ①b 步骤序列契约与串行执行器 ·
①c 结果表与导出），网关 **613 passed**、探针 **m38 11/11 · m39 11/11 全红**、真实网关 e2e 全过。
★ **①b 硬前置核实核出了与上篇 handoff 不符的事实**：`surge.run_n1_branch_contingency` **只接
`monitored_branches`、没有 `file_path`** —— 它跑的是进程内已加载的网络 ⇒ 一次 N-1 =
`load_network` → `run_n1_branch_contingency` **两步**，且须同一 server 会话（旧 handoff §六 的
e2e 模板 `{file_path,branch}` **是错的**，别再照抄）。⇒ 契约扩展为显式 `steps[]`（**不保留旧 `step`**、
**全部步骤同 server**）。★ 执行期三条硬 fail-closed：**一格一会话** / **`remounted` 判失败** /
**多步无会话池显式 503**（各有探针）。★ 结果按 `cache_key` 落盘，算例一改即 `never_run` + `orphaned`
（实测）。★ 环境坑：**`create_app()` 会把全局 `_POOL` 重置为 `None`**（测试夹具走 HTTP 会抹掉会话池）；
探针又踩一次「选择器指错」（已内建识别）。**未做：前端 `ExperimentsView` · §11.2 并发隔离 · P3 的
`result_tables` 透视。**

---

### 🚩 2026-09-27 — JOURNAL（**P2-①b/①c 实验矩阵：执行器 · 结果表 · 导出**）
📄 [2026-09-27-p2-experiments-execution.md](2026-09-27-p2-experiments-execution.md)

**判据 #2/#3 的网关侧由此具备**。①b-1 契约扩展（`Step` / `Experiment.steps` / `Cell.steps` /
`cache_key = H(算例 sha256 + steps 序列 + core_version)`，**步骤顺序参与身份**）· ①b-2 串行执行器
`POST /experiments/{eid}/run` · ①b-3 真实 e2e（case39：**46 场景 / 23 越限 / 52 条**，3.1s；
无池网关多步 **503**、单步 **200** 正对照）· ①c `/results` + `/export?format=csv|md`。
★ **e2e 抓到真实缺陷**：引擎内层 JSON 的 `status` 与保留列 `status` **撞名**（列里出现两个 status）
→ 指标键统一加 `metric.` 前缀 + C5 探针。★ 陈旧结果实测：改算例前 `{'ok':1} orphaned=0`
→ 改后 `{'never_run':1} orphaned=1`。★ 未引用因子会告警（否则两格 `cache_key` 相同却看着正常）。
⚠️ 越限明细级 `result_tables` 透视属 **P3**，本步未做（不给假表）。

---

### 🚩 2026-09-27 — HANDOFF（**P2 盘点 + 实验矩阵定义层 P2-①a**）
📄 [handoff_2026-09-27_p2-experiments-definition.md](handoff_2026-09-27_p2-experiments-definition.md)

状态：P2 三缺二已定位（**实验矩阵 / 并发隔离**未做，均已用 grep 核实而非照抄文档）；
实验矩阵的**定义与登记层已交付**并提交 `ad6b50b`，工作区干净。★ 三个必须延续的设计决定：
一格 = 显式声明的工具调用（**因子只是标签维度**，不做"负荷水平"这类语义因子）·
`cache_key` **不含引擎/IR 版本**（无可靠来源，不假装有）· **格子现算不存快照**。
⚠️ **①b 执行器的硬前置**：开工前必须先核实目标工具真实 `input_schema`，
不核实就写执行器 = 对着想象的接口定型。★ 探针教训：**探针不红时先怀疑选择器指错，再怀疑实现**。
含环境踩坑（后台网关会被回收 / curl 需 `--noproxy '*'` / 测试需设围笼否则 409）与全套自检命令。
⚠️ **本文的 §七-1「①b 硬前置」已由下一篇 handoff 完成核实**，并核出与本文 §六 e2e 模板不符的事实
—— 以最新 handoff 为准。

---

### 🚩 2026-09-27 — JOURNAL（**P2-①a 实验矩阵：定义与登记**）
📄 [2026-09-27-p2-experiments-definition.md](2026-09-27-p2-experiments-definition.md)

**判据 #2/#3 落地的第一块**：`experiments.py` + `POST/GET /experiments` · `GET /experiments/{eid}`，
**只定义与登记、不执行**（执行是 ①b）。★ **一格 = 一次显式声明的工具调用**（server/tool/args 模板），
**因子只是标签维度** —— 刻意不做「负荷水平」这类语义因子，那等于替引擎声称未核实的能力。
★ `cache_key` 只含可确证的量（**不含引擎版本/IR 版本**，写明理由：无可靠来源，不假装有）。
★ 格子**现算不存快照**（算例一改，同格算出新 key ⇒ 旧结果即陈旧）。
两条渲染硬约束：整串占位符**保类型** · 未知占位符**必须报错**（否则"跑成功但没生效"）。
错误映射 400/409/404/500/503，409 专给"算例存在但状态不允许"。网关 **525 → 567 passed**；
变异探针 **8/8 全红**（第一版 M2 未变红 → 拆 M2a/M2b，正是探针的价值）；真实网关 e2e 6 条路径全对。
⚠️ 未核实：目标工具的真实 `input_schema` —— 是 ①b 开工前必须先核的一项。

---

### 🚩 2026-09-27 — JOURNAL（**case39 跨引擎 7e-3 pu 根因结题：surge 是 distributed slack**）
📄 [2026-09-27-xengine-7e3-rootcause.md](2026-09-27-xengine-7e3-rootcause.md)

**根因实锤（复现误差 6.8e-09 pu）**：surge 的 AC 潮流把功率失配**均摊到全部 10 台机组**
（每台 +69.5995 MW），而非标准 single-slack 语义（bus31 独自承担 677.87 MW）。
排除链：IR 无辜（参数逐项一致）· pp 双路径逐位一致 · 编号/f_hz 排除 ·
统一 Ybus 下 surge 解每台 gen 母线 +69.599 MW 失配 → distributed-slack 假设下 pp 逐位复现。
**含义**：cross-engine-consistency 选题的核心案例（平衡机语义差异）；
`run_ac_power_flow` 缺「求解语义」契约（schema 一致但语义不同）；界面 Δmax「不一致」判定正确。
脚本 m35/m36/m37 + 证据 work/xengine-diff/。遗留：surge 无关闭开关（上游）；pp 经 IR 丢 rate_a。

---

### 🚩 2026-09-27 — JOURNAL（**⑥ 校验层收尾：跨引擎一致性 · 能力矩阵 · IR 检查器 + N-1 violations 结构化**）
📄 [2026-09-27-verify-three-blocks.md](2026-09-27-verify-three-blocks.md)

**React 迁移计划内视图全部落地**。校验层展开区改四标签；`ViolationTable`（排序数据层做死 + 截断可见 +
flow/limit 并排）；跨引擎配对在数据层（**算例不同永不配对**、无标识 → Δ 照显但「无法判定」、阈值 1e-4
显式声明）；能力矩阵**动态列/静态列来源分离写明**（t0 findings vs v4 §5.3 文档知识）；IR 检查器覆盖
诊断/陈旧标记，selection/edits 注明未实现。★ F-5 延伸：`from_bus`/`to_bus` 实测 1-based 入 `byOutput`
（case39 夹具：to_bus=39 > 38）。夹具 3 份抓自真实网关。vitest **126 passed/7 文件**；build/guard ✅。
⚠️ chat.test 一次超时假失败与沙箱 EPERM 同现，隔离与干净全量跑均稳过。

---

### 🚩 2026-09-26 — JOURNAL（**F-4 接线：结果经适配层进 Quantity/Identifier**）
📄 [2026-09-26-f4-wiring.md](2026-09-26-f4-wiring.md)

**结构化通道建成**：`tool_call` 事件新增 `result_excerpt`（网关侧 NaN 消毒 + MCP 内层解析，523 passed）→ 前端 `results.ts` 适配层（`measure()` 唯一调用点）→ `ResultSummary` 组件（「非模型转述」）→ 对话视图接线，95 passed。
**★ 端到端决定性对比**：同一轮对话，模型自述 `bus 78`（又把数组位置当母线号），结构化通道 `bus 76`（对）—— 数值呈现不再依赖模型自述。
**★ 顺带钉死 F-5**：`bus_number` 实测 **1-based**（case118 N-1 出现 118）⇒ 约定**按「输出」标注而非按「引擎」**，tokens 的 `byEngine.surge=0-based` 对母线号是错的（未修，适配层已显式绕开）。

---

### 🚩 2026-09-26 — JOURNAL（**判据 #1 两条修复 + ★ 新发现 F-4：模型编号对齐会出错**）
📄 [2026-09-26-criterion1-followups.md](2026-09-26-criterion1-followups.md)

**修复 #1（上下文禁止重复 parse）**：判据 #1 步骤 7 时模型重新调了 `powerio.parse`（附录 A 明确要求复用 IR）。**不能只说"禁止"** —— 引擎载入本来就该用各自的 `*_from_any(file_path=…)`（那是引擎自身导入，不算重新解析），故指令点名工具 + 给出替代。**端到端验证**：工具调用 5 → **2 步**、帧数 **1951 → 193**；网关 515 → **516 passed**。
**修复 #2（输出文件知情）**：`pypsa.import_case_from_any` 会往用户数据目录写 `.nc`。`ToolCallRow` 新增「输出文件（按参数声明）」；白名单**核实自真实 server 代码**（`output_path` 14 · `output_dir` 10 · `out_path` 5），**有意排除 `dest`**（电力语境可能是目标母线）；措辞守住「**参数声明 ≠ 确实写入**」边界。前端 73 → **79 passed**。
**★ F-4（新，未修）**：模型报「最低电压 `0.943 pu` @ **母线 78**」，而**直接调 surge 读 `vm`/`bus_numbers` 实测是 `bus_numbers[75] = 76`** ⇒ 它**把数组位置当成了母线编号**，且**语气确定**（典型「语气确定的假声明」）。更关键的是**准确性依赖提示词压力**：步骤 7 我提示了编号约定它就对，本轮没提示它就错 ⇒ **不可靠且提示词治不了**。⇒ ★★ **结果呈现不能靠模型自由写 prose** —— §4.3 要求的 `Quantity`/`Identifier` 接线**尚未落到对话视图**，这是 ③ 的真实缺口，且现在**有实测证据**，不再只是设计推断。

---

### 🚩 2026-09-26 — JOURNAL（**判据 #1 验收通过：新算例跑通 A–C 全流程**）
📄 [2026-09-26-criterion1-acceptance.md](2026-09-26-criterion1-acceptance.md)

**判据 #1 达标**：取**从未登记/解析过**的 `GridData/MatpowerData/case118.m`，走完 13 步的 **A–C 阶段（步骤 1–7）**，**无人工改脚本**（全部经网关 HTTP，与 React 界面同一套端点）。
**A** 环境就绪（`/environment` + `/contracts/t0`）· **B** 解析 → `pio-ir` v2 / `powerio.BalancedNetwork` / 224 KB / **118 母线 · 186 支路 · 54 机组 · 99 负荷** / 诊断 `ok: no diagnostics` · **C** 基态潮流（对话路径：`pandapower.load_network_from_any` → `run_power_flow`，收敛，最低 `0.943`@110 · 最高 `1.050`@96）+ **跨引擎校验**（PyPSA vs surge，**Δmax = 2.0e-06 pu**，模型**主动按母线名称对齐**并逐引擎标注编号约定）。
★ **核对（不凭模型一句话就接受）**：模型称「case118 rating 为 0」→ 查 IR 证实 **186 条支路 `rate_a` 唯一值只有 `0.0`** ⇒ **属实**（MATPOWER 官方 case118 未给热极限）⇒ **该算例不能做热极限/负载率分析**，模型**没有编数字**。「PyPSA 丢弃 54 个机组无功限值」也属实（引擎能力差异，非数据缺失）。
⚠️ **不得声称"机器精度"**：`2.0e-06 pu` 比 case39 那次（`6.98e-11`，同 IR 往返）**差 5 个数量级**，且 PyPSA 导入**显式报出两处保真度损失**（54 机组无功限值 / 2 条支路并联导纳折叠）——差异有可解释来源，但不足以宣称两引擎等价。
**过程中 4 条如实记录**：① 模型**重新 parse** 而未复用已解析 IR（附录 A 步骤 4 明确要求复用）② `pypsa` 往 GridData **写了 `case118_pypsa.nc`**（允许根内合法，但界面应显式标出"产生文件"）③ 契约事件 0 条（参数全对，好结果）④ 我的证据流捕获不完整（测量工件）。

---

### 🚩 2026-09-26 — JOURNAL（**S2 视图迁移：③ 对话分析（含 ⑥ 校验层状态条）**）
📄 [2026-09-26-view3-chat-migration.md](2026-09-26-view3-chat-migration.md)

**范围**：③ 的全部 + ⑥ 的「契约面板/状态条」部分（§4.3 的轨迹块头带契约告警计数、§4.7.1 要求状态条**所有视图共有**，故切不干净）。⑥ 其余三块（跨视图一致性 §5.2 / 能力矩阵 §5.3 / IR 检查器 §5.4）留下一步。
**交付**：`sse.ts`（帧解析纯函数，两条流共用）· `api.ts` 的 `parseChatFrame`/`parseEvidence`（按 kind 分派）· `session.ts`（`useSession` 提到 App 层 + **按 `seq` 去重**）· `ToolCallRow` §4.3 · `ContractBadge` §4.1 · `ContractCard` §4.2 · `VerificationLayer` §4.7.1（含 `summarizeFindings` 双轨汇总）· `ChatView` · App 主区**标签页**（对话默认 / 技能手册，`#skills` 深链）· 真实 `chat.sse` / `evidence.sse` 夹具。
★ **§8.4 三条同时落地**：safeParse · **不 throw**（坏帧降级、流继续）· **不静默**（`malformed` → 渲染成 `incident` 横幅）。★ **`seq` 去重是必须的**：服务端不解析 `Last-Event-ID`，重连全量重放。
★ **顺带修掉 MVP 一个假绿灯**：MVP 初始状态条是 `✔ 0 通过`（**0 条检查却显示通过**，§4.7.1 反例点名的最危险形态）；React 按规范实现 **空集 = `? 未知`**。
**验证**：build ✅ · guard ✅ · vitest **48 → 73 passed/5 文件** · 原始色 0 命中。测试含**真实 SSE 字节**的端到端与去重验证。
⚠️ **三处诚实边界**：① 无头 Chrome 本会话不可用（11 个残留进程、一律超时；**未全量 kill**，不排除含用户浏览器），A/B 改由 vitest 渲染真实夹具产出（非同一时刻同构对照）；② `EventSource` 接线用**伪造实现**测通，真实浏览器断线重连未真机验证；③ 真实 LLM 端到端未跑（夹具是网关侧真实抓取，但喂进的是 jsdom）。
**下一步：⑥ 剩余三块**。

---

### 🚩 2026-09-26 — JOURNAL（**S1 视图迁移：② 算例库 + F-2 字体令牌修复**）
📄 [2026-09-26-view2-cases-migration.md](2026-09-26-view2-cases-migration.md)

**F-2 已修**：`build_design_tokens.py` 的 `fontFamily` 生成**过度匹配**（`--p-font-` 吃掉 `--p-font-size-*`）+ **二次 `var()` 包裹** → `font-sans`/`font-mono` 产出无效 CSS 被浏览器丢弃，而**两道护栏都拦不住**。修法：`by_prefix(..., exclude=...)` + 不再二次包裹，**新增第三道护栏** `validate_artifacts()` 校验**产物内容合法性**（与「是否漂移」是两类问题 —— 生成器稳定吐垃圾时漂移检查照样绿）。变异探针 **3/3 全红**；组件内联绕过全部换回 `font-mono`。
**② 算例库已迁完**：`api.ts` 新增 5 个 cases schema · `components/CaseCard.tsx`（§4.7.2）· `views/CasesView.tsx` · `App.tsx` 左栏挂载（与 MVP 同布局）。★ **§4.7.2 三条硬规则全部落到界面**：`available`/`drift` 现算不缓存 · `drift` 说明**基准来自登记时** · 围笼外给**可执行指引**（把哪个目录加进哪个变量后重启）。
用 `POST /parse` **一次调用**替代 MVP 的 parse+ir 两次（少拉 52KB IR 全文，文案不变）。
**验证**：build ✅ · guard ✅ · vitest **31 → 48 passed/4 文件** · 原始色 0 命中 · **A/B 与 MVP 一致**（算例卡 2/2 · 徽标 1/1 · 三按钮各 2/2 · 提示行 1/1）。**两处有意差异**（规范强制）：追加可见的可执行指引（MVP 只有徽标，§4.7.2 反例点名）；操作反馈就地显示在面板内（MVP 写进对话流，待 S2 改 Toast）。
★ **围笼 409 分支第一次有了真实界面落点**（网关 curl 实测 409 + 视图用真实文案单测断言）；⚠️ 诚实边界：无头 dump-dom 不能点击，该交互由两段证据拼合。
**下一步：S2 ③ 对话分析**（Zod 边界已就位）。

---

### 🚩 2026-09-26 — JOURNAL（**React 地基步：组件层 · 视图拆分 · Zod 入站边界**）
📄 [2026-09-26-react-foundation-step.md](2026-09-26-react-foundation-step.md)

**为什么先做地基**：三个待迁视图（② 算例库 · ③ 对话分析 · ⑥ 校验层）**不能并行** —— 共享写入点（`api.ts` + 当时不存在的 `components/`，组件全内联在 321 行 `App.tsx` 里）+ ③→⑥ 有真依赖（校验层事件源就是对话的 SSE 流）。⇒ **串行**，地基步让「一视图一文件 + 组件统一出口」成立。
**交付**：`components/`（8 文件：`Signature` §3.8.1 · `Button` §4.6.1 · `Input` §4.6.2 · `states` §4.6.5 · **`Quantity` §4.4**（`measure()` 唯一入口 + `unique symbol` 品牌防伪造）· **`Identifier` §4.5**（约定表从生成物 import，未命中→`约定未知`，冲突抛错）· `SkillCard` §4.7.3）· `views/`（`EnvView` + `SkillsView`，`App.tsx` 收为纯壳）· **`api.ts` 补 Zod 入站边界**（§8.4 强制：`apiParsed` 是唯一入口，漂移→`SchemaDriftError`→渲染成 `incident`；只校验**进入状态树的字段**）+ `zod@4.6.5` + `tsconfig allowJs`。
**★ 顺手挖出两个真缺陷**：**F-2**（**待裁决**）`tools/build_design_tokens.py:258` 的 `fontFamily` **过度匹配 + 二次 `var()` 包裹** → `font-mono` 产出无效 CSS 被浏览器丢弃，**两道护栏都拦不住**；**F-3**（**已修**）真实 `/environment` **没有 `llm.required_env`**，而前端声明为必填并 `.join()` → **LLM 未配置时白屏**（只因当时恰好已配置才未暴露）。
**验证**：`npm run build` ✅ · `npm run guard` ✅（88 令牌）· `npx vitest run` **31 passed/3 文件** · 原始色 **0 命中** · **A/B 与 MVP 无差异**（22 卡 / 10 触发表 / 计数行逐字符一致）；唯一有意差异是按 DoD #6 给徽标加了**图标+文字**并把误用的 `⚠` 改回规范值 `▲`。
⚠️ **环境坑（新增 4 条）**：`npm install` 会毁依赖树（平台二进制 **+ `@babel/generator`** → **dev 下 500、build 正常**），补救用 **tarball 直下 + tar 解包**（scoped 包 URL 必须 `%2f` 编码）；**MSYS 会把以 `/` 开头的参数改写成 Windows 路径**；`vite dev` 绑 `localhost`（IPv6）；Chrome 旧 `--headless` **不执行 ES module**，必须 `--headless=new`。
**下一步：S1 ② 算例库迁移**（阻塞已解除）。

---

### 🚩 2026-09-26 — JOURNAL（**#6 结案 + #8 通过 + F-1 已修：围笼路径形态 · 输入规范化**）
📄 [2026-09-26-case6-closeout-and-fence-defect.md](2026-09-26-case6-closeout-and-fence-defect.md)

**#6 结案 = 输入侧**（干净 curl 直构同一路径 **201**，`available=true` 证明网关读到了文件；探针 `.superpowers/sdd/m34-case-register-input.py` 穷举污染形态 —— **⑦ 单引号包裹的回显与记录原文逐字符一致**，另 ② 双引号 / ③ 零宽 / ④ 全角反斜杠也复现 400）。**#8 通过 3/3**（`missing_required`/`wrong_type`/`unknown_arg`，`remounted:false` 证明调用未转发到 server）。**★ 首次真实触发 409 围笼分支**（此前只有 monkeypatch 单测）。
**★ F-1 已修**：`run_gateway.sh:15` 的 `pwd` 在 Git Bash 下给 POSIX 形态 → 允许根被写成 `D:\d\coding\...` → **项目内算例也判 `within_allowed_roots=false`，任何算例解析都 409**（`run_gateway.cmd` 的 `%~dp0..` 正常）。改为 `pwd -W 2>/dev/null || pwd`；闭环验证：`fence` 形态正确 · case39.m 解析 **200** · case5.m 仍 **409**。
**★ #6 已修**：新增 `normalize_case_path` / `suspicious_case_path` —— 剥离成对引号（含嵌套）· 剔除零宽字符 · 全角标点归一；**改动如实回报**（`path_normalized`，**不静默修正**）；400 文案给出可疑字符类别 + 可操作建议；MVP 前端显示归一化提示。
测试 **501 → 515 passed, 2 deselected**（+14，**顺带确证 ≈501 基线**，上期遗留的「待复跑确证」可关闭）；变异探针 **2/2 全红**。
★ 环境备忘：本机 HTTP 探测**必须加 `--noproxy '*'`**（沙箱代理会把 localhost 劫持成 502）；**MSYS 会改写 Bash 参数里的 Windows 路径**（`'C:\Users\Z'` → `C:/Users/Z`）—— 含反斜杠的代码用编辑工具写，别走 shell。

---

### 🚩 2026-09-26 — HANDOFF（**React 迁移第 1 步完成 + MVP 人工测试闭环**）
📄 [handoff_2026-09-26_react-skeleton-and-mvp-test.md](handoff_2026-09-26_react-skeleton-and-mvp-test.md)

接手入口。状态：MVP 测试 8✓/#6 坐实 bug/#8 待 curl 补测；React 骨架 DoD 7/7 全过、视图 1 技能手册 A/B 无差异；下一步算例库迁移。含：母线编号口径（surge 1-based vs 基线 0-based 恒差+1）、契约违规对话路径不可靠（以 HTTP 直构为准绳）、#6 诊断命令、npm/沙箱踩坑档案、仓库未提交清单。

---

### 🚩 2026-09-26 — JOURNAL（**React 骨架 DoD 7/7 全过，迁移第 1 步闭环**）
📄 [2026-09-26-react-skeleton-dod-passed.md](2026-09-26-react-skeleton-dod-passed.md)

张老师确认骨架验收全过：构建零错、tokens 双护栏绿、原始色 0 命中、真实数据贯通（无头验证）、主题双态、状态签名 unknown 如实、guard 篡改探针报红/恢复、vitest 2/2；`/ui/mvp.html` 未动。踩坑三连（测试库版本不存在 / esbuild EBUSY / 平台二进制缺）+ npm 直调 npm-cli.js 绕 WSL shim，均已记当日日志。下一步：第 2 步逐视图迁移（技能手册 → 算例库 → 对话+校验层），A/B 对照 MVP。

---

### 🚩 2026-09-26 — JOURNAL（**MVP 人工测试结果：8✓ · #6 坐实网关侧 bug · #8 待 curl 补测**）
📄 [2026-09-26-mvp-manual-test-results.md](2026-09-26-mvp-manual-test-results.md)

张老师执行 10 条清单：`1✓ 2✓ 3✓ 4✓ 5✓ 6✗ 7✓ 8未完成 9✓ 10✓`。
**#6**：登记存在的项目外文件误报 400「文件不存在」（文件存在 + venv `exists()=True` + 前后端 strip 链路均已核实）——到达网关的字符串存疑或运行时差异，待 curl 二分复现；围笼 409 分支至今未被验证。**#8**：对话路径触发契约违规不可靠（模型拒绝/改道，其"客户端 SDK 先校验"理由已被源码证伪），确定性路径 = HTTP 直构 `/tools/call`（见 `docs/MVP测试_契约拦截示例.md`）。**#10** 通过；★ 长期口径：surge 报 Matpower 1-based 母线号，基线（pandapower）为 0-based，恒差 +1。结论：MVP 验证使命基本完成，支撑 React 骨架启动（见 `docs/MVP崩溃后技术栈评估与建议.md`）。

---

### 🚩 2026-09-26 — JOURNAL（**补记：`8064da6` 之后 7 个未记提交 + 工作区脏**）
📄 [2026-09-26-gateway-startup-hardening.md](2026-09-26-gateway-startup-hardening.md) · [2026-09-26-skills-manual-view.md](2026-09-26-skills-manual-view.md) · [2026-09-26-cases-context-injection.md](2026-09-26-cases-context-injection.md) · [2026-09-26-ands-access-toolface.md](2026-09-26-ands-access-toolface.md)

`handoff_2026-09-25_workbench-p0-and-mvp.md` 与索引均曾滞后于实际仓库。当前 HEAD=`6f5d454`，补记 `8064da6` 之上的 7 个提交（启动脚本加固 · 技能手册视图 · 算例库上下文注入 · **ANDES 接入工具面**）+ 工作区脏（`run_gateway` 路径围笼补丁未提交、`examples/` 从未入版）。测试基线 **≈501 passed**（433→g7-g10 447→g1-g5 487→serverpool 498→cases 500→ANDES 501，按提交链累加，**待复跑确证**）；端点 **16 个**。

---

### 🚩 2026-09-25 — JOURNAL（**子项目 4：持久 server 连接池，T6-M5 根治**）
📄 [2026-09-25-serverpool-t6m5.md](2026-09-25-serverpool-t6m5.md)

张老师真实测试把 T6-M5 从「慢」坐实为「**功能阻断**」→ 会话级持久连接池
（`serverpool.py`，门控 `POWERMCP_SESSION_POOL=1`）。断裂自愈 + LRU + 如实上报状态丢失。
测试 **487 → 498**；变异 3/3 全红；**真进程实测**：载入 case14 → 下次调用状态仍在。

---

### 🚩 2026-09-25 — JOURNAL（**opendss 根因定位，修复待完成**）
📄 [2026-09-25-opendss-rootcause-pending.md](2026-09-25-opendss-rootcause-pending.md)

**"唯一真阻塞"有了可复现的根因**：SDK 白名单环境 × `ctypes.LoadLibrary`（py_dss_interface）
= 子进程静默挂死；完整环境 3s 全通 55 工具。修复方向两条例证待裁决，**未实施**（张老师指示先完成 MVP）。
证据链：`.superpowers/sdd/m23~m31-*`。

---

### 🚩 2026-09-25 — JOURNAL（**G-1/G-2/G-4/G-5 落地**）
📄 [2026-09-25-g1-g5-wiring.md](2026-09-25-g1-g5-wiring.md)

四项裁决落地：`sample_cases` / `columns_source` 清单字段 · checks 契约冻结（G-5）+ 执行引擎
`POST /checks/run` · `/chat` 注入模块提示词（G-4 最小闭环）。测试 **447 → 487**；变异 3/3 全红；
真实模块 E2E 通过。★ 绑定键不能叫 `on`（YAML 布尔陷阱）。

---

### 🚩 2026-09-25 — JOURNAL（**模块校验补强 G-7~G-10**）
📄 [2026-09-25-module-g7-g10-hardening.md](2026-09-25-module-g7-g10-hardening.md)

四条校验缺口修复：`tools` 前缀一致性（装配失败）· `maturity` 与内容一致（装配失败）·
未知 server/槽位告警。+14 测试，**447 passed**；变异探针 **5/5 全红**；两个真实模块仍 0 失败 0 告警。
`modules/README.md` 缺口表已同步为"已修复"。

---

### 🚩 2026-09-25 — HANDOFF（**前端重定位 + P0 完成 + MVP 跑通**）
📄 [handoff_2026-09-25_workbench-p0-and-mvp.md](handoff_2026-09-25_workbench-p0-and-mvp.md)

**新对话接手请先读这份**（比下一份更新）。16 个提交，把前端从「服务论文选题的契约审计界面」
**重定位为通用研究工作台**。

- **P0 全部完成**：LLM 对话链路 · 环境/技能端点 · 算例库与解析 · 模块装配机制 · 设计系统落地
- **UI 规范同步至 v2**（P1 改写为「研究流程是第一公民」· 组件三组 · 校验层默认折叠）
- **两个真实模块**（L1、零 UI）证明 **L0/L1 装得下真实选题**；但暴露 **10 条扩展点缺口**
  → **接口冻结暂缓**
- **单文件 MVP**（`frontend/mvp.html`）跑通：环境就绪 + 算例 + 对话 + 校验层状态条
- ★★ **修了一个阻塞级缺陷**：MCP SDK 只继承白名单环境变量 → 路径围笼此前形同虚设
- 测试 **181 → 433 passed**；变异探针累计 **69+ 条全红**；上游 0 行改动
- ⚠️ **未完成**：设路径围笼（张老师）· 裁决 4 条缺口 · 决定 MVP 去向 · React 工程
- 提交序列见 handoff §二

---

### 🚩 2026-09-25 — JOURNAL（**前端定位级重定位 + P0-1 对话链路交付**）
📄 [2026-09-25-frontend-rebaseline-and-p0-llm-adapter.md](2026-09-25-frontend-rebaseline-and-p0-llm-adapter.md)

**新对话接手请先读这份。** 两件事：

- **前端方案定位级重定位**：目标从「服务『接口标准化』论文选题」改为
  「**直观、方便地用 PowerMCP + PowerSkills 做电力系统相关的任何研究**」。
  契约从「第一公民」降为**可开关的校验层**（能力一个不丢）；**与论文选题解绑**。
  - 最硬证据（词频）：张老师点名要用 powerskills，但 `skill` 在《UI 设计规范》**0 次**、
    在《前端设计方案》**1 次**（且只作契约比对对象）—— 21 个技能在 v3 中**零覆盖**。
  - 产出：重定位提案 · 模块化架构（内核 + 可插拔选题模块，**三层成熟度 L0/L1/L2**）·
    **方案 v4**（968 行，5 主视图 + 1 可开关校验层）。
  - ⚠️ 归档修正：`work/frontend-design/` 下的 `_v3.md` 是**过期**版本，docs 版才是权威（已另存 `_v3.1.md`）。
- ★ **发现并修复：网关当时没有 LLM 层**（`llm`/`provider`/`openai` 在 `gateway/src/` **0 命中**）
  → 「对话分析」（主界面）没有后端。已交付 **P0-1**：`llm.py` + `agent.py` +
  `POST /sessions/{sid}/chat`。
- ✅ **P0-2a 已交付**：`GET /environment`（廉价检查，不拉起 server）+ `GET /skills`
  （22 技能 + **Escalation triggers** —— v3 零覆盖的「研究方法」载体；健康度只报可计算信号，
  整体如实标 `unknown`）。**独立复现了审计报告的三条结论**（ltspice 缺 escalation 表 / 无悬空引用 / 无孤儿手册）。
- ✅ **P0-2b 已交付**：`case` 一级实体（v4 引入；v3 只有 session 粒度）+ `GET/POST /cases` ·
  `GET/DELETE /cases/{id}`。**按路径引用不复制**（登记 sha256 + 读取现算 drift）·
  **DELETE 只注销登记、绝不删除源文件** · 索引为可读 JSON + 原子替换。
- ✅ **P0-2b-2 已交付**（**首个真实拉起 server 的单元**）：`POST /cases/{id}/parse` ·
  `GET /cases/{id}/ir` · `GET /cases/{id}/diagnostics`。实测 **parse → IR → diagnostics 往返成功**；
  **反事实对照**证明上一轮的 env 修复**必要**（不透传时 `is_error=True`）。
  ⚠️ PowerIO 返回是**双层编码**（`powerio_ir` 字段本身是 JSON 字符串）—— 必须原样保存。
- ★★ **修复一个阻塞级真缺陷**：**MCP SDK 只继承白名单环境变量** ——
  `POWERIO_MCP_ALLOWED_ROOTS` 与 `HIGHS_LIB_DIR` **都不在其中**，不显式传就等于"设了也不生效"。
  后果：**路径围笼形同虚设**（server 只认默认根，读不到算例目录）、surge 的 DC OPF 永远拿不到求解器。
  已改为显式透传，并新增 `server_env` 观测面。
- ✅ **P0-3 已交付**（**P0 收口**）：`modules.py`（清单解析 + 校验 + 装配 + 脚手架）·
  `GET /modules` · `scripts/create_module.py`。**★★ 内核自证条件已可检验**：
  模块根**不存在 / 为空 / 全部装配失败 / 全部禁用**四种状态下内核端点全部正常；
  另有一条**反向**断言 —— 内核端点响应里不得出现任何模块 id。
- ✅ **《UI 设计规范》已同步至 v2**（2033 行 / 112 KB）：P1 改写为「**研究流程是第一公民**」·
  组件三组划分（A 常驻 / B 校验层默认折叠 / C 研究视图新增 6 个）· §5.1 骨架改为
  「5 主视图 + 1 可开关校验层 + 模块注入位」· §7.4 契约摘要改为可选 · §8.4 入站边界扩至 6 个新端点。
  **令牌体系完全不变**（88 个令牌，校验脚本通过）。
- 测试：**181 → 433 passed, 2 deselected**；变异探针累计 **69/69 全红**；
  `PowerMCP/` 与 `PowerSkills/` 均 0 行改动。
- ⚠️ **四轮变异探针共逼出 5 条「假护栏」**（1 条真 bug：escalation 子标题致假警报；
  4 条测试缺陷：文件名巧合 / 时间分辨率 / 快路径无断言 / 两条守卫混为一谈）。
- ⚠️ **P0 剩余一项**：**设计系统落地** —— 前置已具备（UI 规范 v2 完成）。
- 下一步：**设计系统落地**（tokens → CSS 变量 / Tailwind / 通用基础件）→
  或 **2 个真实模块**（N-1 排序 · 跨引擎一致性）验证扩展点后冻结接口。
- 提交：`84cbb66`（文档重定位）· `8786495`（P0-1）· `1b87182`（P0-2a）· `6b0fc45`（journal）·
  `3dbb37d`（env 修复 + P0-2b）· `369d6b3`（journal）· `578b3f4`（P0-2b-2）·
  `9b1763f`（journal）· `638c269`（P0-3）· `2227326`（journal）· `0d05616`（UI 规范 v2）。

---

### 🚩 2026-09-24 — HANDOFF（**子项目 3 收尾审查完成，可关闭**）
📄 [handoff_2026-09-24_subproject3-closed.md](handoff_2026-09-24_subproject3-closed.md)

**新对话接手请先读这份**（比下一份更新）。记录 Task 0–7 交付**之后的**两轮审查与全部修复。

- **补做了两项欠下的审查**：Task 7 独立补审（上轮因 429 缺失）· 最终全分支审查（base `5111d47`，40 commits，4 Important + 台账 35 条 Minor 分诊）
- **4 条 Important（均经用户裁决）**：契约 3 事件改为 `ContractFinding` 同形 · **`EventBus` 解耦「记录」与「投递」**（慢客户端不再让证据丢失）· `validate_args` 异常不再逃出成 HTTP 500 · 契约 4 判据大小写修正（重测基线仍 6 条）
- **独立验证另找出 3 条残留并收口**：审计写失败是**静默降级**（→ 计数 + `GET /health` 暴露）· 同类畸形"一个报告一个沉默"（→ 统一上报 `structural` unknown）· `api.py` 陈旧注释
- **测试 138 → 181 passed, 1 deselected**；**变异探针累计 5/5 全部变红**（无假护栏）；`PowerMCP/` 仍 **0 行改动**
- ⚠️ **最重要的方法教训**：本周期的**高价值修复集中在错误路径，而恰恰错误路径的测试最差** ——
  探针 A/C 证实：把 `_dispatch` 的 `is_error` 回传、`gen()` 的 seq 去重与 `finally: unsubscribe`
  改回 bug 态，测试**仍全绿**。
  → **约定：修复错误路径必须与「钉住该错误路径的测试」成对交付，并以变异探针自证（改回旧行为必须变红）。**
- 提交序列：`68fbe22` → `4732694` → `ef23f64` → `c981f9f`
- ❌ 仍未解决：opendss 无法经 mcp SDK 挂载 · 选题新颖性专查**至今未做**

---

### 🚩 2026-09-24 — HANDOFF（**子项目 3 全部交付完成**）
📄 [handoff_2026-09-24_gateway-t2-complete.md](handoff_2026-09-24_gateway-t2-complete.md)

**新对话接手请先读这份**（比下一份更新）。子项目 3（T2 + 审计 + SSE）**7/7 Task 全部交付**，
**138 passed**，端到端验收通过（完成标准 4/4）。

- **5 处经用户裁决的判据级改动**：契约 4 同时识别**函数式注册**（OpenDSS 55 工具全靠它）·
  `checked==0` 改报 `unknown` · `_dispatch` 回传 `is_error` · `EventBus.subscribe_queue()` 同步注册 ·
  app 加 **lifespan flush 审计**（否则进程退出即丢证据）
- ⚠️ **Task 7 未经独立子代理审查**（账户频率限制 429）—— 下次会话优先补做
- ⚠️ **最终全分支审查尚未执行** —— 台账累积 30+ 条 Minor 待裁决
- 📌 **新建技能 `plan-code-preflight`**：派发前把计划代码提取到真实位置跑一遍 ——
  本轮 7 个任务**每一个**都因此抓出「照抄必然失败」的问题（合计 20+ 处）

---

### 🚩 2026-09-24 — HANDOFF（UI 规范定稿 + 子项目 3 计划与首两个任务）
📄 [handoff_2026-09-24_gateway-t2-sdd.md](handoff_2026-09-24_gateway-t2-sdd.md)

**新对话接手请先读这份。** 记录本会话增量：UI 设计规范 v1.0→v1.2（经 3 份独立审查）·
子项目 3（T2/审计/SSE）计划 · **Task 0/1 已交付**（99 tests）· 根目录 `git init`。

- ⚠️ **含一条重要的方法教训**：本会话 9 条 Important 缺陷**全部出在计划代码里**（实现者逐字照抄），
  分四类：**错误路径处理 / 静默数据丢失 / 边界输入 / 断言无力的测试** —— 接手时按这四类去审剩余计划代码可省大量返工
- ⚠️ **含子项目 3 的两处判据重新界定**（契约 3 被实测证伪、契约 4 改为可判定等价命题，产出 7 条）
- **SDD 进度台账**：`.superpowers/sdd/progress.md`（接手必读，续跑依据）

---

### 🏗️ 2026-09-24 — 网关交付（**子项目 2：契约引擎 T0**）
📄 [计划与执行记录](../superpowers/plans/2026-09-24-gateway-contract-engine-t0.md) · 代码 [`gateway/`](../../gateway/) · 缺陷立项 [opendss 挂载](../superpowers/plans/2026-09-24-opendss-sdk-mount-defect.md)

**首个可运行的工程交付物**：本地网关 —— 拉起 MCP server、求值 T0 静态契约、经 HTTP 暴露契约状态。

- **位置**：`gateway/`（新建）。**本轮同时给项目根 `git init`** —— 此前根目录**无任何版本控制**
  （2026-09-24 已发生过一次交付物被覆盖且无法恢复的事故，这是那道兜底）
- **交付**：10/10 Task · 64/64 Step · **76 单元测试 + 1 集成测试通过** · 20 个提交
- **端点**：`GET /health` · `GET /servers` · `GET /contracts/t0`
- ✅ **`PowerMCP/` 保持 0 行改动**（*zero source mutation*）
- **实测快照**：已挂载 **8/9** · 工具 **117** · `summary = incident`
  契约 2 → 5 satisfied + 2 degraded + 2 structural；契约 5 → 11 条重名（**全部 schema 不同**）
- ⚠️ **计划 Goal 有一条未达成**：Goal 写"拉起 9 个"，实际 **8 个** ——
  **opendss 无法经 mcp SDK 挂载**（裸 stdio 探针 1.86s 正常响应，经 SDK 握手 90s/180s 超时）。
  已单独立项，**根因未定**，影响契约 2 / 契约 8 / 能力矩阵 OpenDSS 行
- ⚠️ **与计划预设的偏差（环境相关，非实现缺陷）**：原预测 `hope`/`genx` 因缺 Julia 拉不起来 ——
  **实测相反，9 个全部可拉起**。**错因**：把「引擎**求解**需要 Julia」与「server **进程**无法启动」
  混为一谈；`list_tools` 只要求模块可导入，而 T0 契约**一次求解都不跑**。
  真实的可启动风险是**缺 pip extra**（`pip install powermcp[andes]` 那类）
- **计划已回填为"已交付实现"**：Task 1/5 的代码块已同步为交付版，
  ⚠️ 因此该计划现在描述的是**"已经这么建了"**，不再是前置规格

---

### 2026-09-24 — UI 设计规范（**前端设计方案的实现级展开**）
📄 [../PowerMCP_UI设计规范.md](../PowerMCP_UI设计规范.md) · 令牌真源 [design/tokens.json](../../design/tokens.json) · 校验 [tools/check_design_tokens.py](../../tools/check_design_tokens.py)

**把《前端设计方案》§五 的提案级视觉规范，展开为可直接开发的规格。** 范围＝方案 §八 的 **P1**。

- **技术栈**：Vite + React + TS · shadcn/ui + Radix · Tailwind · ECharts（**非 Next.js** —— 方案 §六 形态 A 是本地单机，SSR 收益为零）
- **主题**：**双主题全做**（浅色默认 + 深色），颜色全部成对定义
- **技术栈**：Vite + React + TS · shadcn/ui + Radix · Tailwind · ECharts（**非 Next.js** —— 方案 §六 形态 A 是本地单机，SSR 收益为零）
- **主题**：**双主题全做**（浅色默认 + 深色），颜色全部成对定义
- **6 个组件**：契约徽章 · 契约卡片 · Tool Call 审计行 · Quantity · Identifier · 基础件（含 P1 必做的引擎状态指示器）
- ⚠️ **发现方案一处内部不一致并显式处理**：§2.2 称「状态**三态**」，但 §11.1/§11.3 均要求 `unknown` 对外可见
  → 本规范采用**四态**，并建议方案 §2.2 同步修订（附录 B.3）
- **交付**：`docs/PowerMCP_UI设计规范.md` + `design/tokens.json`（单一真源）+ 校验脚本；备份于 `work/frontend-design/`
- 🚫 **不含 WCAG 无障碍章节**（用户指定删除）；但**保留**方案 §五.1 的「颜色不得单独承载信息」

#### ★ v1.1 修订（经三份独立审查）

**审查方法**：派三个独立子代理（实现可行性 / 一致性 / **对抗性**），各带全新上下文。对抗审查**实际编译 TSX** 验证。

**🔴 最严重发现 —— 规范在实现层重现了它自己要防的缺陷**
- `tokens.json` 的 `identifierConvention` 用 server id（`pypsa`），而规范表格用显示名（`PyPSA`）
  → 运行时**查表未命中 → 兜底 `0-based`** → PyPSA 的 `13` 渲染成 `13 (0-based)`，**一条语气确定的假声明**
- 且绑定表**只覆盖 3/9 引擎**，其余 6 个静默兜底
- 缓解措施（悬浮提示）在截图/导出里不可见 —— **规范用"截图会丢信息"论证过颜色不能单独承载信息，却用 tooltip 承载唯一的免责声明**

**🔴 第二严重 —— 判别联合挡得住"忘写判据"，挡不住"判据写错"**
- `<Quantity value={98.16} unit="%" criterion="MW" />` **编译通过**，渲染 `98.16% (MW 判据)` —— **比裸值更可信**
- 写下这行的人正是当初用 MW 算负载率的那个人；把正确值与错误值并列成同一枚举 = 给错误值发合法性证书

**「类型约束」卖点的实测兑现率 ≈ 30%**（非首版宣称的"不可表达"）
- 真的挡住 13 类写法（实测报错）· 挡不住：`JSON.parse` 的 `any`（**项目唯一真实数据入口**）、
  ECharts/SVG/**LLM 流式 Markdown 正文**、`var(--c-contract-*)` 两行 JSX

**已完成的 4 条高杠杆修订**
1. **§4.5 引擎键统一** —— 改 server id；9 引擎全覆盖；**未命中 → `unknown` 不再兜底**；`engine` 收为字面量联合（编译期挡 `engine="PyPSA"`）
2. **§4.4 `criterion` 不再由 JSX 手写** —— `Measured` + `measure()` 唯一构造入口，判据从 N 个渲染点收敛到 1 个数据适配点
3. **§4.3 删除 `state` 属性** —— 改由 `worstState(contracts)` 内部派生；**空集汇总定义为 `unknown`**（自然实现 `reduce(...,'satisfied')` 会把"没检查"渲染成"检查过且正常"）
4. **§4.4 补 P4 的 `source`** —— §2 P4 曾声称"数值的 `source` 为必填"但组件里并无此属性

**诚实性修订**：P3 原则**改名**为「让违规写法在关键调用点上不易顺手写出」并标注实际兑现程度 ·
§3.1 三层架构规则**限定为颜色**（原文写成通用语，字面上禁止组件使用全部 `--p-*`） · §7.4 补 `?0`（原示例三态，契约引擎崩溃会渲染成 `✔0 ▲0 ✖0` = 静默 fail-open）

**7 处引文修正**：含一条**冒引** —— §4.2 曾写「确认必须写入审计（方案 §11.4）」，而方案 §11.4 只规定存储介质，该要求实为**本规范新增**
**结构补充**：附录 A.4 补录 **16 个缺失令牌**（原「令牌**全表**」名不副实）· 新建附录 B.4「本规范新增」登记表

**校验**：85 令牌逐值比对通过；**三组反向测试**（篡改颜色 / 尺寸 / 新补录的 z-index → 均报错 → 还原 → 通过）

#### ★ v1.2 修订（两条工程改进，用户提出）

**① §8.4（新增）SSE 数据边界运行时校验 —— 强制**
- **问题**：`JSON.parse` 返回 `any`，**编译期守卫在运行时全部穿透**。SSE 是长连接流式推送，
  网关字段漂移（`server_id` vs `server`、`contracts` 为 `null`）直达 React 状态树 → **白屏**，且整个会话反复触发
- **规则**：入站事件必须经适配层 `safeParse`（Zod / Valibot）后才允许进入状态树与 `measure()`；
  `measure()` 入参类型改为 `z.infer` 的输出 —— **把运行时契约与编译期类型绑到同一处**
- **失败一律降级为 `incident` 并入审计**（通道 A 不可丢）；禁止 `throw`（炸掉整个流）与静默丢弃（等于 fail-open）
- ✅ 效果：P3 逃逸表中「`JSON.parse` 的 `any`」一条**标记为已闭合**

**② 未知态两分 + 双轨汇总 —— 解决"Alert Fatigue by Design"**
- **问题**：方案 §11.1 已接受契约 4 长期 `unknown`。原**单一标量**汇总使几乎所有审计行常年挂问号
  → 工程师免疫、不再下钻 → **真正偶发的契约 3 参数降级被"钝刀子"淹没**
- **根因**：单标量试图同时表达**"多严重"与"多可信"两个正交维度**，硬塞进一个全序必然牺牲一边
- **解法**：`unknown` 按成因分 `structural`（引擎级、常态、**不升级**）/ `incident`（本可判定却拿不到、**必须升级**）；
  汇总改为**双轨** —— 主徽章（已知告警最差值）+ 次级标记 `+?N`（结构性未知计数）
- **新增第 5 个签名** `incident` / `!` / 事故 + 双主题色（violet 族，与 violated 的红区分）

**连带修正**
- **§4.6.6** `crashed` / `circuit-open` 原均映射 `violated` → 渲染成同一个「✖ 违反」，区分消失。
  现改 `incident` + **引擎专用标签**（引擎态是独立枚举，只借签名取色）；**并补上该组件缺失的属性表**
  （原为唯一带 ★ 却无属性表的组件）
- §4.2 `ContractCard` 增 `reason`（`state==='unknown'` 时必填）
- §1.5 术语表新增结构性/事故性未知、主徽章/次级标记；§7.4 摘要新增 `!n` 计数

**校验**：88 令牌（+3 incident 色）通过；**新增两组反向测试**（篡改 incident 色 / 删除 signature 标签 → 均报错 → 还原 → 通过）

---

### ⚠️ 2026-09-24 — 引用图遍历复核（**更正既有结论**）
📄 [2026-09-24-citation-graph-recheck.md](2026-09-24-citation-graph-recheck.md)

**通读 journal 时发现 `traversal.json` 的 `n` 与 `citing` 长度不一致 → 定位到技能脚本的静默截断。**

- **根因**：`finding-research-gaps/scripts/openalex.py` 的 `cites` 单次请求 + `--top` 默认 50、**无翻页**
  → 被引 79 / 58 的两个锚点只取到 50 条，**共漏 37 篇**，且无任何缺失标记
- ✅ **已修复**：改 cursor 分页（`per_page=200`）、`--top` 缺省改为**取全量**、
  新增 `traverse` 子命令（此前这一步**没有脚本**，故结果无法重跑）、`_get` 增加代理回落；原文件已备份
- ✅ **重跑**：144 → **181 篇唯一引用者**（193 抓全，重叠 12，**旧有新无 0 篇** ⇒ 旧版是新版真子集）
- ⚠️ **截断是系统性的**：排序 `publication_date:desc` → 丢掉的是**最老的那段**；
  新增 37 篇中 **34 篇是 2024/2025**；旧集合高估新近度（2026 占比 73.6% vs 真实 60.2%）
- ❌ **「人机协同仅 2 篇」证伪** —— 181 集中至少 4 篇命中，含 *Integration of LLM and Human-AI
  Coordination for Power Dispatching*（IEEE TVT 2024）；找回的还有 RePower（工具/平台层）等
- ❌ **「工具/技能 14 · 可解释 3 · 人机协同 2」不可复现** —— 原分类产物从未归档；
  同规则下机械计数为 12/3/4，人工甄别后 genuine 仅 **4/1/2**
- ✅ **方向性结论稳健**：前四类 108→134 篇（+26），尾部三类仅 15→19 篇（+4），**差距反而拉大**；
  与 `work/fw/aggregate.json`（97 篇 future work）构成两套独立数据的一致指向
- **新增产物**：`work/cite/rerun-20260924/`（`traversal_full.json` · `themes_full.json` ·
  `themes_curated_tail.json` · `classify_themes.py`）
- **技能已同步**：`SKILL.md` 新增两条「Common mistakes」（短列表不可信为完整 · 计数必须连标注一起归档）

---

### 🚩 2026-09-23 — HANDOFF（基线交接文档）
📄 [handoff_2026-09-23_powermcp-baseline.md](handoff_2026-09-23_powermcp-baseline.md)

**新对话接手请先读这份**，再按需深入下面的具体文档。

- 它是**首次交接**（`previous_handoff: null`），记录全量历史
- 含：项目定位、七块已完成工作、关键决策、文件变更表、当前状态（✅⏳❌📋）、
  **可直接运行的快速上手指令**、下一步优先级、给接手 agent 的提醒
- 关键悬置：**MCP 接口方向的下一步未定**（七轮筛选后唯一存活的候选）

---

### 2026-09-23 — 科研选题方向总结报告（选题决策文档）
📄 [2026-09-23-research-direction-summary.md](2026-09-23-research-direction-summary.md)

**把七轮文献空白调研收敛成一份可直接用于决策的文档。** ⚠️ 是**汇总**而非新调研，不引入新检索结果。

- **§1 选题的约束条件**：本项目能给什么（IR 往返保真、case30 全流程、250 工具）/ 不能给什么（8 项实测缺陷）
- **§2 方法三轮演进**：关键词检索（**七轮错六轮**）→ 引文链 + future work → **引用图差集**（差异化最大）；含三条方法红线
- **§3 六条被推翻候选** + 唯一存活（**MCP 接口标准化**）
- ⚠️ **本条的引用图数字已被 2026-09-24 复核推翻，勿再引用**：144 → **181 篇**（脚本静默截断）；
  「工具/技能 14 · 可解释 3 · 人机协同 2」**不可复现**（同规则机械计数 12/3/4，人工甄别 genuine 仅 4/1/2），
  **「人机协同仅 2 篇」证伪**。详见上一条 [引用图遍历复核](2026-09-24-citation-graph-recheck.md)。
  ✅ 仅**方向性结论稳健**（尾部三类占比仍显著低于前四类）
- ~~**§4 引用图验证**：5 种子锚点 → 144 篇唯一引用者；矩阵/调度类已 118/144，**工具/技能层仅 14、可解释/审计 3、人机协同 2**~~
- ⚠️ **§4.3 三条局限原样保留**：0 引用部分是**时间滞后**非空白 · 空间仅 10–12 篇 · **建筑能源 MCP 更成熟**（EnergyPlus-MCP 被引 24 > 电力最高 11）
- **§5.2 最可操作的产出**：把「MCP 标准化」拆成 **8 条有实测支撑、可逐条形式化的契约类型**
- **一句话结论**：下一步**不是动手做**，而是先用 `finding-research-gaps` 做**新颖性专查**

---

### 2026-09-23 — case30 全流程验证 + 文献空白调研 + 技能交付
📄 [2026-09-23-case30-and-gap-research.md](2026-09-23-case30-and-gap-research.md)

**合并三块此前只存在于对话中的工作**（09-22 ~ 09-23）。

**① case30 全流程**：IR 解析（`pio-ir` v2 / `BalancedNetwork` / 零诊断）→ slack 推荐（母线 1，qmax 150 是次高者 2.4 倍）→ 跨引擎潮对比（**Δ 8.84e-11 pu**）→ PTDF/LODF → N-1（41 场景 / 32 越限 / 56 条）→ 缓解手册应用
- ⚠️ **编号陷阱**：pandapower 0-based vs PyPSA 1-based，**字面比对把偏差放大 3.1 亿倍**
- ⚠️ **判据陷阱**：过载用 **MVA**，用 MW 会把 142% 看成 98%
- ✅ **三条独立证据链重合**：图论桥 ≡ LODF 对角 None 列 ≡ N-1 Islanding 断号（均为 12/15/33）
- ❌ **N-1 缓解**：再调度需 72.7 MW（占负荷 38.4%）不可行；母线 8 仅 2 条支路**无可切方案**；**只有加固 8–28 有效**

**② CSEE-FS 解析失败**：PowerIO 不支持 BPA **且** 文件是 GBK —— **两个正交阻塞，只解决一个都不够**

**③ 文献空白调研（七轮）**：六条候选全被推翻（不确定性量化 / 静默失效 / 技能形式化 / 可扩展性 / 人机协同 / 安全实证），**唯一存活：MCP 接口标准化**（有 Frontiers 2026 综述明确背书 + 引用图验证）

**④ 技能交付**：`finding-research-gaps`（全局，**未提交仓库**），走完 RED-GREEN-REFACTOR

---

### 2026-09-21 — 两份实践指南更新为第二版（并入实测结果）
📄 [2026-09-21-guides-v2.md](2026-09-21-guides-v2.md) · 状态：✅ 已完成

把本轮全部实测结论并入 `docs/` 的两份实践指南，并新增「哪些 server / 技能可用 + 科研使用步骤 + 科研场景」。

- **交付**：`PowerMCP实践指南_v2.pdf`（23 页）· `PowerSkills实践指南_v2.pdf`（24 页）+ 对应 `.md` 源；**第一版 PDF 原样保留**
- **新增四章**：PowerMCP 第四章「当前可用性全景」（五级状态 + 服务器级总表 + 运行时核验）· PowerSkills 第六章「技能健康度审计」（3 阻断 / 4 事实不符 / 1 引用错误 / 5 规范 / 3 通过）· 两份各一章「科研使用步骤」与「科研场景」
- ⚠️ **更正第一版数字**：服务器 15→16；case39 由「34 线路 / 12 变压器」更正为 **35 / 11**；示例 1 的 L17/母线 7 数字改为实测值；OpenDSS 工具名更正；**「PyPSA DC OPF 亦 infeasible」结论作废**（`linearized` 参数不存在，被静默忽略）
- 🚫 **pandoc 已禁用**：本轮 PDF 系用 pandoc + xelatex 产出，用户随后明确禁止用 pandoc 生成 PDF；命令与 `pandoc-header.tex` 均已作废。今后需 PDF 时先向用户确认方式（详见「实践指南 PDF 的生成方式」一节）

---

### 2026-09-21 — surge 求解器配置记录（HiGHS / Ipopt）
📄 [2026-09-21-surge-solver-setup.md](2026-09-21-surge-solver-setup.md)

新建 conda 专用环境 `powersolvers`（未动 `base`），解锁 surge 的 OPF 能力。

- ✅ **HiGHS 完全可用** —— 设 `HIGHS_LIB_DIR` 后 `solve_dc_opf` **3/3 稳定通过**（cost=125948.01），`solve_scopf` 亦然
- ❌ **Ipopt 未能可靠解决** —— 试遍别名 / `IPOPT_LIB_DIR` / `PATH` / 预加载共 7 种组合均失败；有**一次不可复现的成功**，且另一次尝试中**进程静默崩溃**。**不声称已解决**
- ⚠️ **更正一处我先前的错误结论**：曾判断 API_REFERENCE 缺 5 个工具 —— **该结论是错的**，文档把同类工具合并写在同一标题下，我的正则只取了第一个。实测 **44/44 完整覆盖，无需修复**（该错误未进入任何文档）
- ⚠️ 配置**未持久化**（仅在 shell 会话内），符合"禁止未经确认修改系统环境变量"约束

---

### 2026-09-21 — PowerSkills 审计报告（层次 1 动态 + 层次 3 交叉一致性）
📄 [2026-09-21-powerskills-audit.md](2026-09-21-powerskills-audit.md)

对上游 https://github.com/Power-Agent/PowerSkills 的审计。**结论：21 个 skill 中，4 个在役 skill 里有 3 个存在阻断级问题；surge 是唯一质量完好的。**

| 严重度 | 数 | 代表问题 |
|---|---:|---|
| 🔴 阻断 | 3 | `optimization_analysis.py` **语法错误**；pandapower 的 `net.deepcopy()`；pypsa 的 `Network.status`（**求解成功却误报"未收敛"**） |
| 🟠 事实不符 | 4 | pypsa 自带算例**潮流失效**（无法复现 SKILL.md 声称的 87%）；线路/变压器数量写反；loads 数不符 |
| 🟡 引用错误 | 1 | `opendss/SKILL.md` + README 引用的 **6 个工具名全部不存在** |
| 🔵 规范 | 5 | ltspice 缺 escalation 表；**仓库无 CI**；版本约束前后不一致 |
| ✅ 通过 | 3 | 3a escalation 引用完整（10/10）· 3b 工具名有效 · 3c 触发条件对齐 |

**根因共性**：代码写于旧版 API + 依赖无版本上界 + **仓库无 CI** → 缺陷长期存活。

**未做**：层次 2（其余 17 个 skill 的静态审计，按用户指定跳过）；potpourri/surge-OPF/OpenDSS 因环境依赖缺失未做动态验证（报告中已区分"skill 缺陷"与"环境限制"）。

**✅ 已提 PR #8**：https://github.com/Power-Agent/PowerSkills/pull/8 —— 修复 4 处同源的 API 漂移缺陷（3 文件 +39/−12），经 fork `zhangf701/PowerSkills` 提交。详见报告 §8.5。

---

### 2026-09-21 — PowerMCP 核心 Server 示例脚本验证报告
📄 [2026-09-21-mcp-examples-verification.md](2026-09-21-mcp-examples-verification.md) · 状态：✅ 三脚本全部跑通（EXIT=0）

在 IEEE 39 算例上验证了 pandapower / PyPSA / surge / powerio 四个开源 server + 商业组件探查。

- **交付**：`examples/` 下 **4** 个自包含脚本 + `docs/logs/` 完整日志
- **正向验证**：PowerIO IR 往返保真达机器精度 —— 同 IR 经 pandapower 与 PyPSA，母线电压 **Δ=6.98e−11 pu**、支路有功 **Δ=2.25e−07 MW**
- ⚠️ **上游缺陷**：`run_contingency_analysis` 在 pandapower 3.5.4 下必然失败（`panda_mcp.py:180,191` 的 `net.deepcopy()` 已被移除）；`requirements.txt` 未钉版本故只在较新版暴露；上游 `tests/` **无该工具的功能测试**故 CI 未拦截
- ✅ **已决策**：**不改上游源码，N-1 统一走 surge**。4 条候选路径实测对比见报告第七节——「客户端 monkey patch」经实测**无效**（`powermcp run` 是独立子进程，补丁不跨进程）
- ⚠️ **使用陷阱**：两侧元件编号约定不同（pandapower 0-based 索引 vs pypsa 1-based `"1"`/`"line_1"`），**字面键对比会拿错物理元件**（首次误报 0.068 pu）
- ⚠️ **待查**：PyPSA OPF 在 IR 导入算例上 infeasible，已排除求解器/电压上限/DC/容量/必需列等假设，**成因未定位**（不编造解释）
- ⚠️ **环境**：PowerWorld 仅装了 Education 版，**不含 SimAuto COM**，故不可自动化；HOPE/GenX 缺 Julia

**关键数值**：基态最低 母线30 `0.9820` / 最高 母线35 `1.0636` / 最重载 线路21 `73.37%`；N-1 Top-1 断号 `branch_26`（Line 21→22）负载率 `161.84%`、`flow = 958.49 MW`；低电压故障 2 个，最低 `min_vm_pu = 0.9361`；AC OPF 目标 `41,872.30`（网损 44.18 MW）、DC OPF 目标 `41,263.94`。

### 2026-09-21 — OPF 能力交付（示例 04）
📄 见上条报告 §3.7 与 §7.1 · 状态：✅ 已跑通

**决策 C1**：两条 MCP 路径均不可用（pandapower server 无 OPF 工具；PyPSA `optimize_network` 对 IR 导入算例 infeasible），遂改用 **pandapower 自带 `runopp`（AC）/ `rundcopp`（DC）**——与已验证的 `runpp` 同引擎，无新数据契约。

⚠️ **破例**：这是 **Skill 侧 Python 调用，不是 MCP 工具调用**。为弥补此弱点，脚本设 🔒 一致性闸门：从同一 JSON 本地重建网络并与 MCP 基态潮流逐母线比对，实测 **Δ = 0.000e+00 pu**，不过闸门则 `assert` 中止。

**实测数值**：AC OPF 目标 `41,872.30`、网损 `44.18 MW`、电压 `0.9820~1.0600`、线路最大负载率 `87.64%`；DC OPF 目标 `41,263.94`、发电精确等于负荷 `6254.23 MW`。三项守恒校验残差均为 `0.0000 MW`。

**附带对照**：pandapower 对算例中「机组 5 电压设定值 1.0636 > 母线上限 1.06」自动放宽并求解成功，而 PyPSA 在同一数据上直接判 infeasible。（该异常经实测**不是** PyPSA 阻塞的充分原因）

---

### 2026-09-21 — PowerMCP 运行环境搭建记录
📄 [2026-09-21-env-setup.md](2026-09-21-env-setup.md) · 状态：✅ 已完成并验证

在 `PowerMCP/.venv`（Python 3.12.6，uv 建）装好 **核心 + `[hope,surge]`**，未触碰任何 conda 环境或系统配置。

- **已决策**：安装范围＝核心（pandapower / PyPSA / PowerIO / mcp）+ `surge` + `hope`；不装 `andes`/`egret`/`opendss`/`ltspice` 及全部闭源 extra
- **已发现**：`genx` extra 不增加任何新包（`matplotlib`/`pandas` 由核心传递带入）——已实测证实
- **已验证**：`powermcp doctor` 通过；**运行时 `list_tools` 核验 5 个 server 全部 MATCH**（pandapower 8 / pypsa 17 / surge 44 / hope 20 / powerio 10）
- ⚠️ `MCP paths` 报黄：路径围笼仍是隐式默认值，未设 `POWERIO_MCP_ALLOWED_ROOTS`
- ⚠️ HOPE / GenX 包已装但**跑不动**（缺 Julia 运行时与仓库本体）

---

### 2026-09-21 — PowerMCP 仓库扫描报告
📄 [2026-09-21-powerMcp-repo-scan.md](2026-09-21-powerMcp-repo-scan.md)

对 https://github.com/Power-Agent/PowerMCP 的完整结构扫描（提交 `a21ea6b`，v0.4.0）。

**核心结论**：
- Monorepo 结构：`powermcp/` 核心胶水包 + 15 个厂商 server 目录；经 hatchling `force-include` 零源码改动打包
- 16 个 server / **约 250 个 MCP 工具**；**两种注册风格并存**（装饰器 vs 函数式），只扫 `@mcp.tool` 会漏掉 OpenDSS(55) 与 PSCAD(26)
- 跨 server 交换格式为 **PowerIO IR gen 2**（`pio-ir` v2），由外部 `powerio` 包提供
- 安全控制面成熟：路径围笼 + **AST 静态强制检查** + PSSE 22 条命令黑名单（防 prompt-injection → RCE）+ HOPE 只读模式
- ⚠️ **工具名跨 server 冲突严重**（`load_network`/`add_bus`/`run_contingency_analysis` 等多处重名，语义可能不同）—— **对后续 Skill 设计影响最大**
- ⚠️ CI 矩阵漏 Python 3.11（classifier 声明了但未验证）

**地位**：后续所有任务的前置依据。任何"基于 PowerMCP 建 Skill"的工作都应先读本文档第三、七节。

---

## 项目工具

| 路径 | 用途 |
|---|---|
| [docs/PowerMCP_模块接口冻结_v1.md](../PowerMCP_模块接口冻结_v1.md) | **P1.5 交付物**（2026-09-26）：模块清单字段集 / 版本约束 / 装配规则 / checks 契约 / 后端端点 **冻结 v1**；★ **5 个槽位与前端 `kernel.*` 明确不冻结**（零使用 / 未实现），含触发条件与最小验证方案 |
| [docs/React版测试命令.md](../React版测试命令.md) | **手测清单**（2026-09-26）：服务地址 · 界面逐项预期 · 9 组 curl（**均已实跑**）· 3 条环境坑 · 一键复跑脚本 |
| [docs/PowerMCP实践指南_v2.pdf](PowerMCP实践指南_v2.pdf) · [.md](PowerMCP实践指南_v2.md) | 对外交付文档（第二版，A4 23 页）。含可用性全景、科研步骤与场景 |
| [docs/PowerSkills实践指南_v2.pdf](PowerSkills实践指南_v2.pdf) · [.md](PowerSkills实践指南_v2.md) | 对外交付文档（第二版，A4 24 页）。含技能健康度审计 |
| [docs/PowerMCP实践指南.pdf](PowerMCP实践指南.pdf) · [PowerSkills实践指南.pdf](PowerSkills实践指南.pdf) | 第一版（2026-09-19），**保留存档，未改动** |
| [PowerMCP/](PowerMCP/) | 仓库克隆。**当前在 `fix/pandapower-deepcopy` 分支**（含本地修复 `563297a`，未提 PR）；`main` 未被触碰 |
| [PowerSkills/](PowerSkills/) | PowerSkills 仓库克隆（21 个 skill）。**当前在 `fix/pypsa-pandapower-api-drift` 分支**（PR #8，🔒 冻结勿切回 main） |
| [PowerMCP/.venv/](PowerMCP/.venv/) | 隔离运行环境（Python 3.12.6，已 gitignore） |
| [examples/](examples/) | 3 个可独立运行的验证示例脚本 + `data/` 算例 |
| [docs/logs/](docs/logs/) | 示例脚本的完整运行日志 |
| [tools/runtime_tool_census.py](tools/runtime_tool_census.py) | 运行时工具清单核验：拉起 server 调 `list_tools`，与静态统计对照 |
| [tools/dump_tool_schemas.py](tools/dump_tool_schemas.py) | 导出 server 的真实工具 schema（参数名/类型/必填/默认值/返回结构） |
| [tools/test_patch_propagation.py](tools/test_patch_propagation.py) | N-1 修复路径的对照实验：证明客户端 monkey patch 不跨进程（决策依据） |
| [work/cite/rerun-20260924/](work/cite/rerun-20260924/) | **引用图遍历重跑产物**（181 篇引用者 + 主题分类 + 人工甄别）；含可重跑脚本 `classify_themes.py` |
| `C:\Users\Z\.claude\skills\finding-research-gaps\scripts\openalex.py` | OpenAlex 引用图客户端（**2026-09-24 修复分页截断**，备份 `openalex.py.bak-20260924`） |

### 运行示例

```bash
cd d:/coding/powerMcp_Pskills
./PowerMCP/.venv/Scripts/python.exe examples/01_pandapower_surge_demo.py
./PowerMCP/.venv/Scripts/python.exe examples/02_powerio_translation_demo.py
./PowerMCP/.venv/Scripts/python.exe examples/03_commercial_runtime_check.py
./PowerMCP/.venv/Scripts/python.exe examples/04_pandapower_opf_demo.py
```

### 实践指南 PDF 的生成方式（已禁用 pandoc）

> 🚫 **本项目禁止使用 pandoc 生成 PDF**（2026-09-21 用户明确指令）。
> `PowerMCP实践指南_v2.pdf` / `PowerSkills实践指南_v2.pdf` 系禁令下达前用 pandoc + xelatex 产出；
> **对应命令保留在此仅作历史记录，不得再执行**。`pandoc-header.tex` 随之作废。
>
> 后续若需重新排版或生成 PDF：**先向用户确认使用哪种方式**，不要自行选择引擎。

若只是要**阅读/核对**已有 PDF（只读操作，不受禁令约束）：

```bash
cd d:/coding/powerMcp_Pskills/docs
pdfinfo "D:/coding/powerMcp_Pskills/docs/PowerMCP实践指南_v2.pdf"          # 页数 / 纸张
pdftotext -enc UTF-8 "D:/coding/powerMcp_Pskills/docs/PowerMCP实践指南_v2.pdf" out.txt   # 回读校对
pdftoppm -png -r 300 -f 7 -l 7 "D:/coding/powerMcp_Pskills/docs/PowerMCP实践指南_v2.pdf" pg   # 转图目视
```

> ⚠️ 原生 Windows 工具（pdftotext / pdftoppm / pdfinfo）**不认 Git Bash 的 `/d/...` 路径**，必须传 `D:/...`；
> 输出路径带中文会报 I/O Error，中间产物请用 ASCII 名。

---

## 待办（未启动）

- [ ] **明确 Skill 目标**（自仓库扫描起持续挂起，当前首要待决）：目标 server 子集、Skill 粒度（每工具一技能 / 每业务流程一技能）、是否以 PowerIO IR 作数据契约
- [ ] **【选题线·最高】MCP 接口方向的新颖性专查** —— 动手前必做（见 [方向总结报告](2026-09-23-research-direction-summary.md) §5.3）
- [ ] **【工程线·网关】子项目 4（进程监管）/ 1（设计系统落地）/ 5（前端视图）** —— 子项目 3 已于 2026-09-24 收尾关闭，见 [最新 handoff](handoff_2026-09-24_subproject3-closed.md)
  - ⚠️ 子项目 5 开工前须知：契约 3 事件流有**两个 kind**（`contract_violation` / `contract_unknown`），payload 同为 `ContractFinding` 同形
  - 子项目 4 同时承接 `T6-M5`（每次 `/tools/call` 都重新拉起 MCP server）与 `T6-M6`（`_STORE` 无淘汰）
- [ ] **【2026-09-24 复核遗留】** 用 **abstract 级**复核尾部三类论文（标题匹配会漏措辞不同的前作）
- [ ] **【2026-09-24 复核遗留】** 统一 `anchors.json` 与 `traversal.json` 的采集时间戳（两文件对 2 个锚点的被引数不一致：59 vs 58、38 vs 40）
- [ ] **【2026-09-24 复核遗留】** 「72 篇」与「10–12 个去重工作」两个计数仍无原始数据支撑，需单独处理
- [ ] 排查 PyPSA OPF 在 IR 导入算例上不可行的成因（详见验证报告发现 #5）
- [ ] 决定是否补装 `[andes]` / `[opendss]` / `[ltspice]` extra 以扩大验证覆盖
- [ ] 若需验证 HOPE / GenX，先安装 Julia 运行时
- [ ] 若日后需要 pandapower 引擎自身的 N-1 结果，需重新评估是否改源码（当前决策是不改）
