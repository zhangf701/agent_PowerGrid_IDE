# React 版测试命令（可直接复制）

> 2026-09-27 更新 · 下列命令**均已实跑验证**（当日记自运行中的网关），预期结果取自实测。
> 覆盖：环境 · 算例库（含围笼 409 与输入规范化）· 契约拦截 · 对话 · 技能 · 契约 T0 · 模块 · checks
> · **⑥ 校验层四标签（跨引擎一致性 / 能力矩阵 / IR 检查器）· N-1 违规表（本次新增）**。
>
> ⚠️ **算例 id 以 `GET /cases` 现查为准** —— id 由路径派生，但索引内容随登记/注销变化。
> 本次实测时索引为 5 张：`cd4cf1328477`=case39（examples/data）·
> `ac7ae93e8478`=case118（GridData/MatpowerData）· `d4fe3cd86962`=case5（**已移到
> GridData/MatpowerData，项目内**——2026-09-26 版的围笼用例随之失效）·
> `e6abcfc1f695`=围笼测试专用文件（`C:/Users/Z/Downloads/case_fencetest.m`，本次新建）·
> `e6a7e04090fc`=case14（项目内、**未解析**——IR 检查器的 409 分支用）。

## 一、服务地址

| 服务 | 地址 | 说明 |
|---|---|---|
| 网关 | `http://127.0.0.1:8765` | MVP 页在 `/ui/mvp.html` |
| React 版 | **`http://localhost:5173`** | ⚠️ **必须用 `localhost`** —— dev server 只绑了 IPv6 `[::1]`，用 `127.0.0.1` 连不上 |

重启命令（若需要）：

```bash
cd D:/coding/powerMcp_Pskills/gateway && ./run_gateway.sh     # 网关
cd D:/coding/powerMcp_Pskills/frontend && npm run dev          # React dev
```

⚠️ **诊断网关问题先看启动日志的 `fence =` 一行** —— 它必须是 `D:/coding/...` 形态；
若是 `/d/coding/...`，说明用了旧版脚本，围笼会整体失效（缺陷 F-1，已修）。

---

## 二、界面测试（点着看）

### React 版 `http://localhost:5173`

默认落在**对话**标签（③ 是主界面）。逐项看：

| # | 操作 | 预期 |
|---|---|---|
✔| 1 | 看顶部**校验层状态条** | 初始应为 **`? 未知`** + `✔ 0 · ▲ 0 · ✖ 0` —— **不是「通过」**（0 条检查 = 未判定，不是通过） |
✔| 2 | 左栏「算例库」 | 5 张卡（见页首清单）；项目内 4 张正常；`case_fencetest.m` 带 **`server 读不到`** 徽标 **+ 一行可执行指引**（把 `C:\Users\Z\Downloads` 加进 `POWERIO_MCP_ALLOWED_ROOTS`） |
✔| 3 | 点 `case_fencetest.m` 的**解析** | 面板内出 **错误横幅（`! 事故` 签名）**，文案含「请把 `C:\Users\Z\Downloads` 加入该变量后重启网关」；⚠️ 若先做步骤 4，这里上一条「已解析 case39.m」提示会**消失**（2026-09-27 修复：旧提示曾残留，被误读成本卡结果） |
✔| 4 | 点 `case39.m` 的**解析** | 面板内提示「**已解析 case39.m：**powerio.BalancedNetwork（51.0 KB，IR 可读：是）」（带算例名，反馈可归因） |
✔| 5 | 登记框粘一条**带引号**的路径（如 `"D:/coding/powerMcp_Pskills/examples/data/case39.m"`）→ 登记 | 提示「已登记算例（路径已自动归一化：剥离首尾引号）」 |
✔| 6 | 对话框输入 `只回答两个字：收到` → 发送 | 助手气泡出「收到」；底部进度「对话完成：2 帧」；连接状态 `● 已连接` |
✔| 7 | 点「技能手册」标签 | 22 张卡 / 10 个触发表；计数行 `22 个技能 · tool 11 · engineering 10 · meta 1 · 10 个带触发表`；健康度 `unknown` |
✔| 8 | 对话框输入 `对 case39 跑一次 N-1 支路巡检，给我违规清单` → 发送 | 工具行下出现两块结构化呈现（见下「★ N-1 违规表怎么验」） |
✔| 9 | 点「深色」 | 双主题切换，深色下文字可读 |
✔| 10 | 点状态条「展开 ▾」 | 出**四个标签**：契约 · 跨引擎一致性 · 能力矩阵 · IR 检查器（默认在契约） |

#### ★ N-1 违规表怎么验（步骤 8 之后，看工具行下方）

✔1. **结构化结果块**：标题「结构化结果（由工具结果直接计算，**非**模型转述）」，
   含 场景数 `46（收敛 45）`、越限 `23 个场景 / 52 条`、最重载 Top-1 `161.84% (MVA 判据)`。
   ⚠️ 若模型正文自述的数字/母线号与此不同，**以结构化块为准**（F-4：模型会把数组位置当母线号）。
✔2. **违规表**：列 = 场景 / 类型 / 位置 / 负载率 / 视在功率-限值 / 电压-限值。
   - 第 1 行应为 `branch_26` · 热越限 ThermalOverload · `23 (1-based) → 24 (1-based)` ·
     `161.84% (MVA 判据)` 带「超限」文字 · `971.0 MVA / 限 600.0 MVA`；
   - 表尾一行 **「共 52 条 · 以上为严重度前 10 条（完整清单见原始工具结果）」** —— 截断必须可见；
   - 母线/支路编号都带 `(1-based)` 后缀（surge 输出按源文件编号，F-5 实测裁定）。
✔3. （可选）换 case118 再跑一次：应为 `186` 场景 / **28** 条违规、负载率全 0 ——
   case118 的 MATPOWER 数据**未给热极限**（rate_a 全 0，判据 #1 已核实），违规全是电压/孤岛类。
   若界面把负载率画成非 0，那是**编造**，立刻报。

### ⑥ 校验层四标签（步骤 10 之后）

| 标签 | 操作 | 预期 |
|---|---|---|
✔| **契约** | 看列表 | 有违规/未知 → 契约事件卡片。**跑了工具但没有卡片 ≠ 没检查**：全部通过时不发事件（网关显式设计），空态会如实显示「本会话已执行 N 次工具调用…参数契约（契约 3）都校验且全部通过」。契约 1/2/5/6/7 是 T0 静态的 → 看**能力矩阵**标签 |
✔| **跨引擎一致性** | 直接看 | 无可配对调用时空态文案。**配对已支持真实场景**（2026-09-27 修复：此前 pandapower 的潮流结果形状不被适配层认识，永远配不上）：对话「用 pandapower 和 surge 分别对 case39 跑基态潮流」→ 出现 Δ 行（最低/最高电压的 Δ，如 `Δ = 0 pu`）+ `✔ 满足` 徽章 + 阈值说明「相对偏差 ≤ 1e-4」；`run_*` 调用无参时算例标识继承自该引擎**会话内最近载入**（行内标注「会话内最近载入」）；两引擎最近载入**不同**算例 → 不配对（宁可不比）；标识完全缺失时判定列是 `? 无法判定` —— 均为**有意设计** |
| **能力矩阵** | 直接看 | 9 行引擎 × 动态列（契约 1/契约 2 徽章，**点击可下钻**看网关原文）× 静态能力列（潮流/OPF/N-1/…）；页首注明「静态能力列是文档知识（v4 §5.3），**不是**运行时探测」；`powerio` 行的契约列显示 **`无记录`**（t0 findings 没有它），不显示成正常 |
| **IR 检查器** | 选 `case118` → 点「跑诊断」 | `powerio.BalancedNetwork` · 解析于 … · `ok: no diagnostics（错误 0 · 警告 0 · 备注 0 · 提示 0）`；底部注明 selection 树 / edits 时间线尚未实现；再选 `case14`（未解析）→ 409 原文可见：「该算例尚未解析 —— 先 `POST /cases/{id}/parse`」 |

### MVP 对照 `http://127.0.0.1:8765/ui/mvp.html`

同一份数据、同一套交互。**唯一应看到的差异**：MVP 的初始状态条是 `✔ 0 通过`
（**假绿灯**），React 版是 `? 未知` —— 这是按规范修正，不是回归。
（MVP 没有 ⑥ 四标签与违规表 —— 那是 React 版独有。）

---

## 三、curl 测试命令

> 说明：`--noproxy '*'` 是为了绕开本机可能存在的代理（否则 localhost 可能被劫持成 502）。
> 若你的终端没有代理，去掉它也能跑。
> ⚠️ **路径一律用正斜杠**（`D:/...`）：反斜杠在 shell 里可能被改写，且网关侧也会自动归一化。

### A. 环境与总览

```bash
curl -s --noproxy '*' http://127.0.0.1:8765/health
# → {"status":"ok","audit":{...},"server_pool":{"mounted":N,...}}

curl -s --noproxy '*' http://127.0.0.1:8765/cases
# → 5 张卡（清单见页首）；summary.available / drifted / unreadable_by_servers 现算
```

### B. 算例库（含两个关键分支）

```bash
# B1 登记·干净路径 → 200（已登记过则 created=false）
curl -s --noproxy '*' -X POST http://127.0.0.1:8765/cases \
  -H "Content-Type: application/json" \
  -d '{"path":"D:/coding/powerMcp_Pskills/examples/data/case39.m"}'

# B2 ★ 输入规范化：带引号的路径 → 200 + path_normalized
curl -s --noproxy '*' -X POST http://127.0.0.1:8765/cases \
  -H "Content-Type: application/json" \
  -d '{"path":"\"D:/coding/powerMcp_Pskills/examples/data/case39.m\""}'
# → "path_normalized":["剥离首尾引号"]   ✅ 2026-09-27 实测

# B3 干净路径但文件不存在 → 400（**不带**多余提示，防误报）
curl -s --noproxy '*' -X POST http://127.0.0.1:8765/cases \
  -H "Content-Type: application/json" -d '{"path":"C:/no/such/file.m"}'
# → 算例文件不存在：C:\no\such\file.m   ✅ 实测

# B4 解析·项目内算例 → 200（首次会真实拉起 powerio，数秒）
curl -s --noproxy '*' -X POST http://127.0.0.1:8765/cases/cd4cf1328477/parse
# → value_type=powerio.BalancedNetwork, ir_bytes=52233   ✅ 实测

# B5 ★ 围笼 409：解析项目外算例（case_fencetest.m 在 Downloads，项目外）
curl -s --noproxy '*' -X POST http://127.0.0.1:8765/cases/e6abcfc1f695/parse
# → 409：算例所在目录不在 `POWERIO_MCP_ALLOWED_ROOTS` 内 … 请把 `C:\Users\Z\Downloads`
#        加入该变量后重启网关（当前允许根：['D:\\coding\\powerMcp_Pskills', 'C:\\Users\\Z\\.powermcp']）
#        ✅ 2026-09-27 实测（⚠️ 2026-09-26 版用 case5.m 测这条——它已移进项目内，用例作废）

# B6 诊断·已解析算例 → 200（IR 检查器面板的数据源）
curl -s --noproxy '*' http://127.0.0.1:8765/cases/cd4cf1328477/diagnostics
# → stale:false · summary.status=ok · text="ok: no diagnostics" · diagnostics:[]   ✅ 实测

# B7 诊断·未解析算例 → 409（IR 检查器的错误分支）
curl -s --noproxy '*' http://127.0.0.1:8765/cases/e6a7e04090fc/diagnostics
# → 409：该算例尚未解析 —— 先 `POST /cases/{id}/parse`   ✅ 实测
```

### C. 契约拦截（确定性路径 —— 不依赖模型配合）

```bash
# 先建会话
SID=$(curl -s --noproxy '*' -X POST http://127.0.0.1:8765/sessions \
  -H "Content-Type: application/json" -d '{"servers":["surge","powerio"]}' \
  | grep -o '"id":"[^"]*"' | cut -d'"' -f4)

# C1 缺必填参数 → ok:false + missing_required
curl -s --noproxy '*' -X POST "http://127.0.0.1:8765/sessions/$SID/tools/call" \
  -H "Content-Type: application/json" -d '{"server":"surge","tool":"load_network","args":{}}'
# ✅ 实测：violations[0] = {kind:"missing_required", arg:"file_path", detail:"缺少必填参数 `file_path`"}

# C2 类型错 → wrong_type
curl -s --noproxy '*' -X POST "http://127.0.0.1:8765/sessions/$SID/tools/call" \
  -H "Content-Type: application/json" -d '{"server":"surge","tool":"load_network","args":{"file_path":123}}'

# C3 ★ 未知参数（方案 §2.3 那个 linearized 事故的复刻）→ unknown_arg
curl -s --noproxy '*' -X POST "http://127.0.0.1:8765/sessions/$SID/tools/call" \
  -H "Content-Type: application/json" \
  -d '{"server":"surge","tool":"load_network","args":{"file_path":"D:/coding/powerMcp_Pskills/examples/data/case39.m","linearized":true}}'
```

三条预期都是 `"ok": false`、`"result": null`、`violations` 指出具体参数，
且 `"remounted": false` —— **证明调用根本没转发到 server**（fail-closed 是前置校验）。

### D. 对话（SSE 流）

```bash
SID=$(curl -s --noproxy '*' -X POST http://127.0.0.1:8765/sessions \
  -H "Content-Type: application/json" -d '{"servers":["surge"]}' \
  | grep -o '"id":"[^"]*"' | cut -d'"' -f4)

curl -s --noproxy '*' -N -X POST "http://127.0.0.1:8765/sessions/$SID/chat" \
  -H "Content-Type: application/json" -d '{"message":"只回答两个字：收到"}'
# → event: text   data: {"text": "收到"}
#   event: final  data: {"text": "收到"}     ✅ 2026-09-27 实测
```

`-N` 关掉 curl 的缓冲，才能看到流式逐帧。首字节会被 `build_inventory` 阻塞数秒（挂载 server）。

### E. N-1 确定性直构（不走模型 —— 违规表的 HTTP 级验证）

```bash
SID=$(curl -s --noproxy '*' -X POST http://127.0.0.1:8765/sessions \
  -H "Content-Type: application/json" -d '{"servers":["surge"]}' \
  | grep -o '"id":"[^"]*"' | cut -d'"' -f4)

# E1 载入 case118（★ surge 的载入工具叫 load_network，**没有** load_network_from_any
#    —— 那是 pandapower 的；同名不同义正是契约 5 管的事）
curl -s --noproxy '*' -X POST "http://127.0.0.1:8765/sessions/$SID/tools/call" \
  -H "Content-Type: application/json" \
  -d '{"server":"surge","tool":"load_network","args":{"file_path":"D:/coding/powerMcp_Pskills/GridData/MatpowerData/case118.m"}}'
# ✅ 实测：status=success，n_buses=118 / n_branches=186

# E2 跑 N-1 → 186 场景 / 28 条违规
curl -s --noproxy '*' -X POST "http://127.0.0.1:8765/sessions/$SID/tools/call" \
  -H "Content-Type: application/json" \
  -d '{"server":"surge","tool":"run_n1_branch_contingency","args":{}}'
# ✅ 实测：n_contingencies=186 · n_violations=28 · max_loading_pct 全 0
#    （case118 无热极限 rate_a=0 —— 不是 bug）
```

> 对话路径的期望值（case39）：46 场景 / 52 条违规 / Top-1 branch_26 = 161.84%（MVA 判据），
> 来自真实夹具 `frontend/src/__fixtures__/gateway/result-n1.json`（抓自运行中的网关）。

### F. 技能 · 契约 T0 · 模块 · checks · servers

```bash
curl -s --noproxy '*' http://127.0.0.1:8765/skills
# → 22 个技能 / tool 11 · engineering 10 · meta 1 / 10 个带触发表；health.level = unknown   ✅ 实测

curl -s --noproxy '*' http://127.0.0.1:8765/servers
# → 9 个 server id（能力矩阵的行）   ✅ 实测

curl -s --noproxy '*' http://127.0.0.1:8765/contracts/t0
# → ⚠️ 慢（约 90 秒，会真实拉起 server）；⚠️ 结果随环境变化（装了哪些 extra / 挂载成败）：
#   2026-09-26 实测 summary = {"primary":"incident","structural_unknown":12,"incident_unknown":1}
#   2026-09-27 实测 summary = {"primary":"degraded","structural_unknown":11,"incident_unknown":0}（38 findings）
#   以「结构合法 + 数字与 findings 一致」为验收，不钉死具体值

curl -s --noproxy '*' http://127.0.0.1:8765/modules
# → modules: cross-engine-consistency(L1) · n1-ranking(L1)，均 enabled=true；failures=[]   ✅ 实测

curl -s --noproxy '*' -X POST http://127.0.0.1:8765/checks/run \
  -H "Content-Type: application/json" -d '{"module_id":"n1-ranking","rows":{}}'
# → summary: {checks_run:0, checks_skipped:2, ...}（rows 为空故全部 skipped）   ✅ 实测
```

---

## 四、环境坑（四条，都会误导判断）

1. ⚠️ **React dev 只绑 `localhost`（IPv6）** —— 用 `127.0.0.1:5173` 会连不上。
2. ⚠️ **不要在以 `/` 开头的 shell 参数里写路径** —— MSYS 会把它改写成 Windows 路径
   （实测：`curl -w "/contracts/t0 …"` 里的格式串被吃掉）。
3. ⚠️ **Windows 反斜杠路径在 shell 里可能被改写** —— 一律用正斜杠 `D:/...`。
4. ⚠️ **同名工具不同引擎语义不同**（契约 5 的活例子）：surge 的载入是 `load_network`，
   `load_network_from_any` 是 pandapower/andes 的 —— 直构 curl 时写错会报
   「不存在或该 server 未拉起」（✅ 实测踩过）。

## 五、一键复跑（把 A–F 串起来）

```bash
cd D:/coding/powerMcp_Pskills
B=http://127.0.0.1:8765

curl -s --noproxy '*' $B/health; echo
curl -s --noproxy '*' $B/cases | head -c 200; echo
curl -s --noproxy '*' -X POST $B/cases -H "Content-Type: application/json" \
  -d '{"path":"\"D:/coding/powerMcp_Pskills/examples/data/case39.m\""}' | head -c 200; echo
curl -s --noproxy '*' -X POST $B/cases/e6abcfc1f695/parse | head -c 200; echo
curl -s --noproxy '*' $B/cases/cd4cf1328477/diagnostics | head -c 200; echo
SID=$(curl -s --noproxy '*' -X POST $B/sessions -H "Content-Type: application/json" \
  -d '{"servers":["surge"]}' | grep -o '"id":"[^"]*"' | cut -d'"' -f4)
curl -s --noproxy '*' -X POST "$B/sessions/$SID/tools/call" -H "Content-Type: application/json" \
  -d '{"server":"surge","tool":"load_network","args":{}}'; echo
```

## 六、前端自检三连（改代码后跑）

```bash
cd D:/coding/powerMcp_Pskills/frontend
npm run build && npm run guard && npx vitest run
# 三段全绿 = 前端健康（当前基线：126 passed / 7 文件，2026-09-27）
```
