# React 版测试命令（可直接复制）

> 2026-09-26 · 服务已在运行；下列命令**均已实跑验证**，预期结果取自实测。
> 覆盖：环境 · 算例库（含围笼 409 与输入规范化）· 契约拦截 · 对话 · 技能 · 契约 T0 · 模块 · checks。

## 一、服务地址

| 服务 | 地址 | 说明 |
|---|---|---|
| 网关 | `http://127.0.0.1:8765` | 端点 18 条；MVP 页在 `/ui/mvp.html` |
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
| 1 | 看顶部**校验层状态条** | 初始应为 **`? 未知`** + `✔ 0 · ▲ 0 · ✖ 0` —— **不是「通过」**（0 条检查 = 未判定，不是通过） |
| 2 | 左栏「算例库」 | 两张卡：`case39.m` 正常；`case5.m` 带 **`server 读不到`** 徽标 **+ 一行可执行指引**（把哪个目录加进 `POWERIO_MCP_ALLOWED_ROOTS`） |
| 3 | 点 `case5.m` 的**解析** | 顶部出 **错误横幅（`! 事故` 签名）**，文案含「加入该变量后重启网关」 |
| 4 | 点 `case39.m` 的**解析** | 面板内提示「已解析 powerio.BalancedNetwork（51.0 KB，IR 可读：是）」 |
| 5 | 登记框粘一条**带引号**的路径（如 `"D:/coding/powerMcp_Pskills/examples/data/case39.m"`）→ 登记 | 提示「已登记算例（路径已自动归一化：剥离首尾引号）」 |
| 6 | 对话框输入 `只回答两个字：收到` → 发送 | 助手气泡出「收到」；底部进度「对话完成：2 帧」；连接状态 `● 已连接` |
| 7 | 点「技能手册」标签 | 22 张卡 / 10 个触发表；计数行 `22 个技能 · tool 11 · engineering 10 · meta 1 · 10 个带触发表`；健康度 `unknown` |
| 8 | 点状态条「展开 ▾」 | 出契约事件列表（步骤 6 之后应有契约事件；空时显示「本次会话还没有契约事件」） |
| 9 | 点「深色」 | 双主题切换，深色下文字可读 |

### MVP 对照 `http://127.0.0.1:8765/ui/mvp.html`

同一份数据、同一套交互。**唯一应看到的差异**：MVP 的初始状态条是 `✔ 0 通过`
（**假绿灯**），React 版是 `? 未知` —— 这是按规范修正，不是回归。

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
# → summary: {"total":2,"available":2,"drifted":0,"unreadable_by_servers":1}
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
# → "path_normalized":["剥离首尾引号"]

# B3 干净路径但文件不存在 → 400（**不带**多余提示，防误报）
curl -s --noproxy '*' -X POST http://127.0.0.1:8765/cases \
  -H "Content-Type: application/json" -d '{"path":"C:/no/such/file.m"}'
# → 算例文件不存在：C:\no\such\file.m

# B4 ★ 带引号且不存在 → 400 + 可操作线索
curl -s --noproxy '*' -X POST http://127.0.0.1:8765/cases \
  -H "Content-Type: application/json" -d '{"path":"\"C:/no/such/file.m\""}'
# → …（路径含可疑字符：引号 —— 常见于从聊天/文档粘贴…）（已自动归一化：剥离首尾引号…）

# B5 解析·项目内算例 → 200（首次会真实拉起 powerio，数秒）
curl -s --noproxy '*' -X POST http://127.0.0.1:8765/cases/cd4cf1328477/parse

# B6 ★ 解析·项目外算例 → 409 围笼（这条此前从未被真实触发过）
curl -s --noproxy '*' -X POST http://127.0.0.1:8765/cases/4da0b6c8d9f6/parse
# → 409：算例所在目录不在 `POWERIO_MCP_ALLOWED_ROOTS` 内 … 请把 `C:\Users\Z\Downloads\_科研项目`
#        加入该变量后重启网关（当前允许根：[…]）
```

> 算例 id 可从 `GET /cases` 取。`4da0b6c8d9f6` = 项目外的 `case5.m`，`cd4cf1328477` = `examples/data/case39.m`。

### C. 契约拦截（确定性路径 —— 不依赖模型配合）

```bash
# 先建会话
SID=$(curl -s --noproxy '*' -X POST http://127.0.0.1:8765/sessions \
  -H "Content-Type: application/json" -d '{"servers":["surge","powerio"]}' \
  | grep -o '"id":"[^"]*"' | cut -d'"' -f4)

# C1 缺必填参数 → ok:false + missing_required
curl -s --noproxy '*' -X POST "http://127.0.0.1:8765/sessions/$SID/tools/call" \
  -H "Content-Type: application/json" -d '{"server":"surge","tool":"load_network","args":{}}'

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
#   event: final  data: {"text": "收到"}
```

`-N` 关掉 curl 的缓冲，才能看到流式逐帧。首字节会被 `build_inventory` 阻塞数秒（挂载 server）。

### E. 技能 · 契约 T0 · 模块 · checks

```bash
curl -s --noproxy '*' http://127.0.0.1:8765/skills
# → 22 个技能 / tool 11 · engineering 10 · meta 1 / 10 个带触发表；health.level = unknown

curl -s --noproxy '*' http://127.0.0.1:8765/contracts/t0
# → ⚠️ 慢（约 90 秒，会真实拉起全部 server）；约 14 KB
#   summary: {"primary":"incident","structural_unknown":12,"incident_unknown":1}
#   （incident 来自 opendss 无法经 SDK 挂载 —— 已知阻塞）

curl -s --noproxy '*' http://127.0.0.1:8765/modules
# → enabled = ['cross-engine-consistency','n1-ranking']

curl -s --noproxy '*' -X POST http://127.0.0.1:8765/checks/run \
  -H "Content-Type: application/json" -d '{"module_id":"n1-ranking","rows":{}}'
# → summary: {checks_run:0, checks_skipped:2, ...}（rows 为空故全部 skipped）
```

---

## 四、环境坑（三条，都会误导判断）

1. ⚠️ **React dev 只绑 `localhost`（IPv6）** —— 用 `127.0.0.1:5173` 会连不上。
2. ⚠️ **不要在以 `/` 开头的 shell 参数里写路径** —— MSYS 会把它改写成 Windows 路径
   （实测：`curl -w "/contracts/t0 …"` 里的格式串被吃掉）。
3. ⚠️ **Windows 反斜杠路径在 shell 里可能被改写** —— 一律用正斜杠 `D:/...`。

## 五、一键复跑（把 A–E 串起来）

```bash
cd D:/coding/powerMcp_Pskills
B=http://127.0.0.1:8765

curl -s --noproxy '*' $B/health; echo
curl -s --noproxy '*' $B/cases | head -c 200; echo
curl -s --noproxy '*' -X POST $B/cases -H "Content-Type: application/json" \
  -d '{"path":"\"D:/coding/powerMcp_Pskills/examples/data/case39.m\""}' | head -c 200; echo
curl -s --noproxy '*' -X POST $B/cases/4da0b6c8d9f6/parse | head -c 200; echo
SID=$(curl -s --noproxy '*' -X POST $B/sessions -H "Content-Type: application/json" \
  -d '{"servers":["surge"]}' | grep -o '"id":"[^"]*"' | cut -d'"' -f4)
curl -s --noproxy '*' -X POST "$B/sessions/$SID/tools/call" -H "Content-Type: application/json" \
  -d '{"server":"surge","tool":"load_network","args":{}}'; echo
```

## 六、前端自检三连（改代码后跑）

```bash
cd D:/coding/powerMcp_Pskills/frontend
npm run build && npm run guard && npx vitest run
# 三段全绿 = 前端健康（当前基线：73 passed / 5 文件）
```
