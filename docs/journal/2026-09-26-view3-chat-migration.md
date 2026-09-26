# S2 视图迁移：③ 对话分析（含 ⑥ 校验层的状态条）

日期：2026-09-26 ｜ 前置：`2026-09-26-view2-cases-migration.md`（② 算例库）
定位：第 2 步「逐视图迁移」的**第 3 个视图**，也是**主界面**。串行顺序：⑤ → ② → **③** →（⑥ 剩余部分）

> 一句话：**对话流与工具轨迹已迁完，SSE 入站边界（§8.4）第一次真正落地；
> 顺带修掉了 MVP 初始状态条「✔ 0 通过」这个假绿灯。**

---

## 一、范围：为什么 ③ 与 ⑥ 不能干净切开

方案 §4.3 的「工具轨迹」块头就带 **契约告警计数 + [展开校验]**，
而 §4.7.1 要求校验层的**顶部状态条「所有视图共有」**（MVP 也把它放在 `<header>`）。
故本次交付 **③ 的全部 + ⑥ 的「契约面板/状态条」部分**；⑥ 的其余三块
（跨引擎一致性 §5.2 / 能力矩阵 §5.3 / IR 检查器 §5.4）留待下一步。

---

## 二、交付

| 文件 | 内容 |
|---|---|
| `src/sse.ts`（新） | SSE 帧解析**纯函数**：`parseFrameBlock` / `drainFrames` / `parseAllFrames` / `readSse`。两条流（`/chat` 与 `/events`）**帧语法相同**，共用一份 |
| `src/api.ts` | `SessionSchema` · `parseChatFrame`（按 `event:` 名分派）· `EvidenceEventSchema` · `ContractFindingSchema` · `parseEvidence` / `parseEvidenceFrame`（按 `kind` 分派） |
| `src/session.ts`（新） | `useSession()` —— 会话 + evidence 事件流，**提到 App 层**（状态条所有视图共有）。含 **按 `seq` 去重** |
| `src/components/ToolCallRow.tsx` | §4.3 审计行；徽标文案与 MVP 同口径（`已执行`/`失败`）；**契约标注默认折叠** |
| `src/components/ContractBadge.tsx` | §4.1；`state='unknown'` 无 `reason` → **抛错**；传 `contractType` 时渲染「契约 N · 标签」 |
| `src/components/ContractCard.tsx` | §4.2；detail 原文 + evidence 默认折叠 |
| `src/components/VerificationLayer.tsx` | §4.7.1；`summarizeFindings()` 双轨汇总 + 状态条 + 折叠详情 |
| `src/views/ChatView.tsx` | ③ 对话分析：回合组装 · 流式回答 · 工具轨迹分组 · 进度与连接状态 |
| `src/App.tsx` | 主区**标签页**（对话 默认 / 技能手册，与 MVP 同布局）· 校验层状态条挂在 header · `#skills` 深链 |
| 夹具 | `chat.sse`（**真实** /chat 流）· `evidence.sse`（**真实** /events 流：tool_call + contract_violation） |

---

## 三、★ §8.4 的落地：SSE 入站边界

§8.4 的原文要求是**三条同时满足**，本实现逐条对应：

| 要求 | 实现 |
|---|---|
| 必须经 `safeParse` 才允许进入状态树 | 每个帧都过 `parseChatFrame` / `parseEvidenceFrame`（Zod） |
| **禁止 throw**（炸掉整个流） | 坏帧返回 `{kind:'malformed'}`，**流继续**；`JSON.parse` 失败也不抛 |
| **禁止静默丢弃**（= fail-open） | `malformed` 由 App 渲染成 **`incident`** 横幅（可见）；未知 kind 保留为 `unknown` 并计数 |

★ **按 `seq` 去重是必须的**：服务端**不解析 `Last-Event-ID`**，断线重连一律历史全量重放 ——
事件**不丢但会重复**（`events.py` docstring 明载）。不去重就会重复计数契约告警。

★ **工具轨迹取自 evidence 通道，不取 chat 帧**（与 MVP 同取舍）：evidence 有 `seq`
（可去重、可排序）且重连可重放；chat 帧里的 `tool_call`/`tool_error` 是它的**子集且无 `seq`**，
渲染两处会重复计数。此取舍已写进 `applyChatFrame` 的注释与测试（`tool_call` 帧**有意忽略**）。

---

## 四、★ 顺带修掉的一个 MVP 缺陷：初始状态条是假绿灯

MVP 的初始状态条是：

```html
<span class="sig satisfied">✔ <span id="cOk">0</span> 通过</span>
```

**0 条检查却显示「✔ 通过」** —— 正是 §4.7.1 反例点名的「静默 fail-open，最危险」：
用户以为有保护，实际什么都没检查。

React 版按规范实现：**空集汇总 = `unknown`**（`? 未知`），不是 `satisfied`。
这不是风格差异 —— 自然的 `reduce(…, 'satisfied')` 会把「没检查」渲染成「检查过且正常」。

---

## 五、验证

| 项 | 结果 |
|---|---|
| `npm run build` | ✅（JS 262.94 kB / CSS 14.98 kB） |
| `npm run guard` | ✅ 88 令牌 |
| `npx vitest run` | ✅ **73 passed / 5 文件**（48 → +25） |
| 原始色扫描 | ✅ 0 命中 |

**新增测试（25 条）里最要紧的**：

- **真实 SSE 夹具必须能解析**：`chat.sse` → 2 帧（text + final）；`evidence.sse` → 3 帧带 `seq=[1,2,3]`，
  含 `tool_call` 与 `contract_violation`，且 finding **与 `/contracts/t0` 同形**（尤其有 `state`）。
- **坏帧不毁流**：缺 `event` / 缺 `data` / 非法 JSON 各只跳过该帧，好帧照常出来。
- **未知 kind → `unknown`**（前向兼容，不当畸形）；已知 kind 结构不符 → `malformed`。
- **`seq` 去重**：用伪造 `EventSource` 把同一条证据投递两次 → 契约计数仍是 `✖ 1`（不是 2）。
- **端到端**：把**真实 `chat.sse` 字节**喂给 `ChatView` → 渲染出回答且进度为「对话完成：2 帧」。
- **校验层三条硬规则**：折叠时状态条仍在 · `incident` 计数升到状态条（`2 项事故`）·
  `structural` 只作次级标记 `+?4` 不抢主徽标 · 空集 = `unknown` · `disabled` 留可恢复入口。
- **`ContractBadge`**：`unknown` 不给 `reason` → **抛错**（无法决定渲染「未知」还是「事故」）。

### A/B 对照 MVP

| 指标 | MVP | React | 判定 |
|---|---|---|---|
| composer placeholder | 有 | 有 | ✓ |
| 发送按钮 | 有 | 有 | ✓ |
| 校验层 展开/收起 按钮 | 有 | 有 | ✓ |
| 标签「对话 / 技能手册」 | 有 / 有 | 有 / 有 | ✓ |
| 状态条计数（初始） | `✔ 0` | `✔ 0 · ▲ 0 · ✖ 0` | ✓（React 多列两态） |
| **状态条主徽标（0 条 finding）** | **`✔ 通过`** | **`? 未知`** | ★ **有意修正**（见上节） |
| 空 stream | 空着 | 「问点什么开始研究…」 | ★ 有意追加（§4.6.5：空态须说明**为什么空**） |
| findings 空态 / T0 提示 | 在 DOM 里（隐藏） | 折叠时**不渲染** | 可见行为一致，实现不同 |

### ⚠️ 诚实边界（三处未验）

1. **无头 DOM 对照本次未能执行**：headless Chrome 在本会话已不可用
   （11 个残留进程，`--virtual-time-budget` 一律超时；且**我不做全量 kill** ——
   不排除其中含用户自己的浏览器）。故 React 侧指标改由 **vitest 渲染真实夹具**产出，
   MVP 侧指标取自 15:11 的有效转储。**这不是同一时刻的同构对照**，已在表中标明。
2. **`EventSource` 接线**：jsdom 无 `EventSource`，故用**伪造实现**测通（含去重）；
   真实浏览器的**断线自动重连**行为未真机验证。
3. **真实 LLM 端到端**（浏览器 → 网关 → DeepSeek → 渲染）本轮未跑；`chat.sse` 夹具是
   在网关侧真实抓取的，端到端测试用的是**真实字节**但喂进的是 jsdom。

---

## 六、未决与下一步

| # | 事项 | 状态 |
|---|---|---|
| 1 | **⑥ 剩余三块**：跨引擎一致性 §5.2 · 能力矩阵 §5.3 · IR 检查器 §5.4 | 下一步 |
| 2 | `Toast` §4.6.4 | 未做（算例库的操作反馈仍就地显示） |
| 3 | `EngineStatusIndicator` §4.6.6 | 仍待进程监管（§11.3）落地 |
| 4 | 算例选择并入对话上下文（§4.3 控制头部的「算例」选择器） | 未做 —— 需先定「对话如何引用算例」 |
| 5 | headless Chrome 环境 | 本机有 11 个残留进程；**未清理**（可能含用户浏览器）—— 需张老师确认后再处理 |
| 6 | 本轮**未提交** | `frontend/` 全部 + 四份 journal + `_index.md` |

**DoD 三连（`frontend/` 下）**：`npm run build && npm run guard && npx vitest run` —— 三段全绿。
