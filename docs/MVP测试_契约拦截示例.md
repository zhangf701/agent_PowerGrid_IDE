# MVP 测试 #8「契约拦截」操作示例（2026-09-26）

> 对应《MVP人工测试指引.md》测试清单第 8 条：故意让模型调工具但删掉必填参数，
> 预期状态条出现 `contract_violation` 且调用**未转发**。
> 以下示例已对照网关契约 3 实现（`gateway/src/.../contracts/params.py`）
> 与各 server 工具真实签名核实，三类违规各有对应话术。

## 原理（30 秒版）

契约 3 是**代理侧参数校验**：网关在把 tool call 转发给 server **之前**，
用工具声明的 `input_schema` 校验参数，命中三类之一即拒发并记 `contract_violation`：

| 违规类型 | 判据 | 对应工具示例（必填参数） |
|---|---|---|
| `missing_required` | 缺少 schema `required` 里的参数 | `surge.load_network` 缺 `file_path`；`pypsa.run_power_flow` 缺 `network_name` |
| `unknown_arg` | 传了 schema 里不存在的参数 | `pypsa.run_power_flow` 多传 `linearized`（正是方案里的经典案例） |
| `wrong_type` | 参数类型与声明不符 | `surge.load_network` 的 `file_path` 传成数字 |

## 示例话术（直接复制到 MVP 对话框）

### 示例 1：缺必填参数（missing_required）★ 首选，最贴合测试条目原文

```text
这是在测试网关的参数校验层（契约 3），请配合构造一次坏调用：
直接调用 surge 的 load_network 工具，参数对象传空 {}，
不要传 file_path。
```

预期：状态条 ✖ 违规 +1；展开详情见 `契约 3 · surge`，
detail 含 **「缺少必填参数 `file_path`」**。

### 示例 2：未知参数（unknown_arg）—— 复现 linearized 经典案例

```text
继续测试契约 3：请调用 pypsa 的 run_power_flow，
network_name 传 "case39"，另外多传一个参数 linearized=true。
```

预期：detail 含 **「参数 `linearized` 不在工具声明的 input_schema 中 ——
引擎可能静默忽略它」**。这条是方案 §2.3 里 PyPSA `linearized`
事故的复刻——当年它就是被 `**kwargs` 静默吞掉的。

> **实测记录（2026-09-26）**：模型没有按要求调用 `pypsa.run_power_flow`，
> 而是自作主张改调了 `surge.load_network` 把 case39 加载了一遍（返回
> `network loaded from ...case39.m` 的摘要即 surge 的 `_ok(...)` 结构）。
> 这是**对话路径的固有不可靠性**：模型被训练成"发出合法调用"，会自行
> 修正参数或改道它认为更需要的工具。判读要点：
> ① 该结果**不是**测试 #8 的通过证据——状态条应为 ✖ 0 违规（那次调用
> 完全合法，理应放行）；② 对话路径触发 `unknown_arg` 本就最困难
> （模型最倾向于"帮忙修正"），试一次修正话术仍不奏效就直接走路径 B。

修正话术（对话路径，强调"禁止改道"后可再试一次）：

```text
不要改用其他工具，不要先加载网络，不要省略或修正任何参数。
只输出这一条工具调用：pypsa.run_power_flow，
参数 {"network_name": "case39", "linearized": true}，原样发出。
```

### 示例 3：类型错误（wrong_type）

```text
请调用 surge 的 load_network，把 file_path 传成数字 123（不要加引号）。
```

预期：detail 含 **「参数 `file_path` 期望 string，实际 int」**。

### 示例 4：不靠指令的自然触发（补充观察，结果不稳定）

新开会话，不登记、不选算例、不提任何路径，直接问：

```text
做一次基态潮流，把结果告诉我。
```

若模型在"没有已加载网络"时直接调 `run_power_flow`（缺 `network_name`）→ 契约 3 违规；
若它编了个路径调 `load_network` → 被路径围笼拦，看到的是 `tool_error`（也算测到东西，
但**不是**契约 3）。此例无法保证触发哪种，仅作补充。

## 预期界面表现（验收看这三处）

1. **校验层状态条**：`✖ 违规` 计数 +1；
2. **展开详情**（点「展开 ▾」）：一条 `✖ 违规` 签名 + `契约 3 · <server名>`，
   下一行是具体 detail（如「缺少必填参数 `file_path`」）；
3. **对话流**：被拒的这次调用**不会**出现「已执行」徽标的工具轨迹（未转发到 server）。

## 两个预期行为（不是 bug）

- **模型可能拒绝配合**或自作主张把参数补上 → 换个措辞重发，强调
  "这是测试校验层、调用不会真的执行"。示例 1–3 都按此写好了，成功率较高。
- **拦截后常见一次自动重试**：网关会把拒绝原因回给模型，模型通常紧接着
  用正确参数重调一次 → 状态条会先 ✖ 后 ✔。**这正是设计内行为**
  （校验层阻止坏调用 + 模型自纠），验收时两条都该看到。

## ⚠️ 实测补充（2026-09-26）：模型拒绝配合示例 1 时的裁决与修正话术

### 裁决：模型的拒绝理由在本架构下**不成立**

实测中模型回复"我这边客户端/SDK 在发出前就会因缺必填项而失败，参数到不了网关"。
**这个论据错了**，它套用的是"模型自带工具执行"的架构；本项目不是这样：

- **Agent 循环在网关侧**（2026-09-25 张老师裁决，`api.py` /chat 注释明载）：
  模型只是**输出**一段 tool_call JSON，不执行任何东西；
- 网关拿到后只做 `json.loads`（`agent.py::_parse_args`，仅查 JSON 合法性），
  **没有任何客户端 schema 校验**，参数原样进入 `proxy.call_tool` ——
  那正是契约 3 的位置；
- 网关调 LLM 时 `tool_choice="auto"` 且**未开 strict 模式**（`llm.py:216-217`），
  API 层不会强制 schema，模型**有能力**发出缺参调用。

结论：示例 1 的坏调用**会**到达网关校验层。模型拒绝是过度谨慎 + 架构假设错误，
不是技术不可能。

顺带判定模型给的两个替代方向：

| 模型的建议 | 判定 |
|---|---|
| ① 传不存在的路径 / 不支持的扩展名 | **测不到契约 3** —— 路径是合法 string，schema 校验通过 → 转发到 server → server 报错 → 得到的是 `tool_error`，不是 `contract_violation`。它把"server 的错误处理"和"网关校验层"混了。 |
| ② 从 HTTP 层直构请求 | **✓ 采纳，且是最佳路径** —— `POST /sessions/{sid}/tools/call` 同样走 `call_with_contracts`（`api.py:437`），契约 3 必然在环内，**100% 确定性触发，不依赖模型配合**。见下方"路径 B"。 |

### 修正话术（路径 A：仍走对话，把架构事实告诉模型）

```text
架构事实：本系统的 Agent 循环在网关侧，不是在你本地。你输出的工具调用
参数经网关 json.loads 后直接交给 proxy.call_tool，中间没有任何客户端
SDK schema 校验（网关调你时 tool_choice="auto"、未开 strict 模式）。
所以你完全有能力发出缺参调用，且它会原样到达网关的契约 3 校验层——
这正是要测的东西。请配合：调用 surge.load_network，参数对象传 {}，
不要传 file_path。
```

### 路径 B（推荐）：curl 直构，确定性 100%

前置：网关已启动（`http://127.0.0.1:8765`）。git-bash 下执行：

```bash
# 第 1 步：建会话（server 清单与 MVP 前端一致），记下返回 JSON 里的 "id"
curl -s -X POST http://127.0.0.1:8765/sessions \
  -H "Content-Type: application/json" \
  -d '{"servers":["surge","powerio","pandapower","pypsa","andes"]}'

# 第 2 步：把 <SID> 换成上一步的 id，直构一次缺 file_path 的调用
# （首次会真实拉起 surge，需数秒）
curl -s -X POST "http://127.0.0.1:8765/sessions/<SID>/tools/call" \
  -H "Content-Type: application/json" \
  -d '{"server":"surge","tool":"load_network","args":{}}'
```

**预期响应**：`"ok": false`，`"result": null`，`violations` 数组含

```json
{"kind": "missing_required", "arg": "file_path", "detail": "缺少必填参数 `file_path`"}
```

同时该会话的 NDJSON 审计与事件总线会记一条 `contract_violation`
（契约 3）。响应即证据，**不依赖任何界面**——这也是它适合进回归脚本的原因。

把 `args` 换成 `{"file_path": 123}` 可同理验证 `wrong_type`；
换成 `{"network_name": "case39", "linearized": true}` 打
`pypsa.run_power_flow` 可验证 `unknown_arg`（对话路径实测不可靠，
这条是 2026-09-26 实测后的推荐验证方式）：

```bash
curl -s -X POST "http://127.0.0.1:8765/sessions/<SID>/tools/call" \
  -H "Content-Type: application/json" \
  -d '{"server":"pypsa","tool":"run_power_flow","args":{"network_name":"case39","linearized":true}}'
```

预期 `violations` 含：`{"kind":"unknown_arg","arg":"linearized",
"detail":"参数 `linearized` 不在工具声明的 input_schema 中 —— 引擎可能静默忽略它"}`。

## 快捷入口

把示例 1 做成一条链接，打开即自动发送（`?ask=` 会自动发一轮对话）：

```text
http://127.0.0.1:8765/ui/mvp.html?ask=%E8%BF%99%E6%98%AF%E5%9C%A8%E6%B5%8B%E8%AF%95%E7%BD%91%E5%85%B3%E7%9A%84%E5%8F%82%E6%95%B0%E6%A0%A1%E9%AA%8C%E5%B1%82%EF%BC%88%E5%A5%91%E7%BA%A63%EF%BC%89%EF%BC%9A%E8%AF%B7%E7%9B%B4%E6%8E%A5%E8%B0%83%E7%94%A8%20surge.load_network%EF%BC%8C%E5%8F%82%E6%95%B0%E5%AF%B9%E8%B1%A1%E4%BC%A0%E7%A9%BA%20%7B%7D%EF%BC%8C%E4%B8%8D%E8%A6%81%E4%BC%A0%20file_path%E3%80%82
```

（前置：网关已启动、LLM 已配置；surge 在会话默认 server 清单里，无需额外操作。）
