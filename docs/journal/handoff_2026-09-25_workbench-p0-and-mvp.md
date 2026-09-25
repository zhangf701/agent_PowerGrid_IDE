---
date: 2026-09-25
type: handoff
keywords: [前端重定位, 通用研究工作台, P0 完成, 模块机制, 设计系统, MVP, 接口冻结暂缓, 扩展点缺口]
git_branch: master
git_head: 8064da6
previous_handoff: handoff_2026-09-24_subproject3-closed.md
note: 本会话把前端从「服务论文选题的契约审计界面」**重定位为通用研究工作台**，并完成 P0 全部内容 + 单文件 MVP。接手请先读本文件与 `.superpowers/sdd/progress.md`。
---

# Handoff: 前端重定位 + P0 完成 + MVP 跑通

## 一、项目定位（本会话的起点与终点）

**张老师原话**（2026-09-25）：

> 我做的前端是希望能**直观、方便的使用 powermcp、powerskills 做电力系统相关的任何研究，
> 不限定于某一个具体科研方向**。

核查后发现 v3 方案与之**在设计意图上冲突**（原文自陈「而不是一个通用聊天前端」，
且 `skill` 在 UI 规范出现 **0 次**）。经三次裁决：

1. **重定位为通用研究工作台**（契约从「第一公民」降为**可开关的校验层**，能力一个不丢）
2. **前端与论文选题解绑**，作为自用工具
3. 提案 §九 五项设计判断**全部采纳建议值**
4. MVP 用**单文件 HTML**（零构建）；LLM 用 **DeepSeek**

## 二、本会话交付（16 个提交）

| 提交 | 内容 |
|---|---|
| `84cbb66` | 文档重定位：提案 + 模块化架构 + **方案 v4** |
| `8786495` | **P0-1** LLM 对话链路（`llm.py` + `agent.py` + `/chat`） |
| `1b87182` | **P0-2a** `/environment` + `/skills` |
| `3dbb37d` | **★ 修复阻塞级 env 缺陷** + **P0-2b** 算例库 |
| `578b3f4` | **P0-2b-2** 算例解析为 PowerIO IR |
| `638c269` | **P0-3** 模块装配机制 + 脚手架（**内核自证条件落地**） |
| `0d05616` | **UI 设计规范同步至 v2**（跟随方案 v4） |
| `bd439b3` | **设计系统落地**（令牌生成链 + 双护栏 + 可视化预览） |
| `f97baa5` | **两个真实模块** + 扩展点验证结论 |
| `8064da6` | **单文件 MVP** + 网关静态挂载 |

（另有 5 个 journal 提交：`6b0fc45` `369d6b3` `9b1763f` `2227326` `83ed135`）

## 三、当前状态（**接手前请先复跑这两条**）

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest -q -m "not integration" \
  -p no:cacheprovider --basetemp=./.pytest_tmp/rNN     # → 433 passed, 2 deselected
cd .. && PowerMCP/.venv/Scripts/python.exe tools/check_design_tokens.py   # → 全绿
PowerMCP/.venv/Scripts/python.exe tools/build_design_tokens.py --check    # → 全绿
```

| 项 | 状态 |
|---|---|
| 测试 | **433 passed, 2 deselected**（`deselected` = 2 个 integration 标记） |
| 网关端点 | **15 个**（见下表） |
| `PowerMCP/` · `PowerSkills/` | **0 行改动** ✓ |
| 文档 | 方案 **v4** · UI 规范 **v2** · 模块化架构 · 重定位提案 |
| 选题模块 | **2 个**（`n1-ranking` · `cross-engine-consistency`，均 L1、零 UI） |
| 前端 | `frontend/`：设计系统产物 + `preview.html` + **`mvp.html`**；**React 工程尚未起步** |

**端点**：`/health` `/servers` `/contracts/t0` `/sessions` `/sessions/{sid}/events`
`/sessions/{sid}/tools/call` `/sessions/{sid}/chat` `/environment` `/skills` `/modules`
`/cases` `/cases/{cid}` `/cases/{cid}/parse` `/cases/{cid}/ir` `/cases/{cid}/diagnostics`
+ **`/ui/*`**（前端静态挂载）

## 四、★ 本会话最重要的五个发现

### 1. ★★ MCP SDK 只继承白名单环境变量（已修）

`POWERIO_MCP_ALLOWED_ROOTS` 与 `HIGHS_LIB_DIR` **都不在** `DEFAULT_INHERITED_ENV_VARS` 里 ——
不显式传就等于「父进程设了也不生效」。**后果：路径围笼此前形同虚设**（server 只认默认根 =
`PowerMCP` 仓库根，读不到算例目录）。
已修：`config.SERVER_ENV_PASSTHROUGH` + `server_env()` + `proxy._server_params()` 显式传 `env`。
**新增任何要传给 server 的环境变量都必须加进该清单**，否则静默失效。

### 2. ★ 接口冻结**暂缓**（10 条扩展点缺口）

两个真实模块（L1、零 UI）证明 **L0/L1 装得下真实选题**，但暴露 10 条缺口。
**最要紧的 G-4**：`prompts` / `checks` / `exports` **声明了却未接线** ——
`/modules` 显示 `enabled: 2` **不等于"这两个模块已经能干活"**。
完整清单与**可运行的实测复现**见 [`modules/README.md`](../modules/README.md) +
`.superpowers/sdd/m15-module-gaps.py`。

### 3. ★ MVP 暴露的首个真实可用性问题

`/chat` 的**首字节被 `build_inventory` 阻塞**（挂载 server，秒级）——
用户点发送后**盯着空白气泡等十几秒**，看起来像卡住。已在界面加「正在准备工具面」提示，
**根因是 T6-M5**（每轮都重新挂载 server），归子项目 4。

### 4. ★ 无头测试测不了流式

Chrome `--dump-dom` 的**虚拟时间不把响应体当作 pending**，预算会在流中途耗尽
（实测：进度栏停在「等待首帧」）。**EventSource 是永不结束的请求**，普通模式更会让
dump 永远等不到网络空闲。→ MVP 因此有 `?nosse=1` / `?fullbody=1` / `?selftest=1` 三个调试模式；
**帧解析代码抽成纯函数**，流式与全量两条路径共用，使同一份代码可被无头验证。

### 5. ★ 网关的 `notes` 字段带 markdown

`**粗体**` 会被界面当纯文本渲染成字面星号。界面必须做最小 markdown 渲染（先 `esc` 再渲染）。

## 五、未完成 / 下一步（按优先级）

1. **【最高】设路径围笼** —— `POWERIO_MCP_ALLOWED_ROOTS` 目前为空，**server 读不到算例目录**。
   这是 MVP 真正可用的**唯一硬前置**（界面已会提示，但需张老师设）。
2. **【高】裁决 4 条影响 P1 设计的缺口**：G-1（无默认算例字段）· G-2（静态列 vs 动态列）·
   G-4（prompts/checks/exports 未接线）· G-5（checks 契约未定义）。
   **接口冻结与 P1.5 都卡在这里。**
3. **【高】决定 MVP 的去向** —— 它是**弃子**（跑通即弃，转 React）还是**扶正**？
   张老师说过「单文件 HTML 做 MVP」，但**没定跑通后怎么走**。
4. **【中】React + Vite + TS 工程骨架** + 通用基础件（UI 规范 §4.6）——
   `tailwind.config.js` 应 import `src/design/tokens.generated.js` 的 `tailwindTheme`。
5. **【中】G-7/8/9/10 四条校验补强**（低成本、可独立成单元）。
6. **【低】P1 其余视图**（环境就绪 / 算例库 / 实验矩阵 / 技能手册）+ 校验层详情面板。
7. **【低】算例的 parse/diagnostics 未进审计**（`call_tool` 以 `bus=None` 调用）。
8. ⚠️ **未定**：`DEEPSEEK_API_KEY` 的归属 —— 它在环境里但**不在 shell 配置文件**，
   `reg.exe` 被安全策略禁用故查不到注册表。**若它是 WorkBuddy 自己的 key，用它跑网关可能不合适**。
   MVP 走 `POWERMCP_LLM_*` 环境变量，密钥不进代码，用哪个由张老师运行时决定。

## 六、给接手 agent 的提醒（本会话踩过的坑）

- **`reg.exe` 被安全策略禁用**（不可重试、不可绕过）；PowerShell 工具在本环境**不返回输出**；
  git-bash 里**没有 coreutils 的 `timeout`**（被 Windows 的 `timeout.exe` 顶掉，退出码 127）
  → 用「后台 + 轮询 + kill」代替。
- **后台进程随工具调用结束被回收** → 起网关 + 测它的动作必须在**同一次** Bash 调用内完成。
- **heredoc 会吞转义**：`<< 'PYEOF'` 里 Python 字符串的 `\n` 会变成字面 `/n`。
  **探针一律写成文件**（项目惯例本就是 `.superpowers/sdd/*.py`）。
- **mock 必须打在「使用它的模块命名空间」里**：`case_ir` 是 `from .inventory import build_inventory`，
  只 patch `api_mod.build_inventory` 不生效 → "单元测试"会真实拉起 server（2s → 36s）。
- **ASCII 架构图里有全角空格**，Edit 精确匹配不可靠 → 按**行范围**替换（Python 按章节标题定位）。
- **改完文档必须 grep 旧章节号查残留引用**（本会话抓到 5 处）。
- ⚠️ **`work/` 已被 gitignore** —— 归档不进版本控制，**权威版永远是 `docs/`**；
  且 `work/frontend-design/` 下曾出现**过期归档**（`_v3.md` 缺实测校正），比对用 `diff -q` 不要凭文件名。
- **变异探针"未变红"有两种解读**：测试没区分力，**或那段代码本身有问题**。
  本会话 4 轮探针共逼出 5 条假护栏（1 条真 bug + 4 条测试缺陷）。方法见技能 `mutation-probe-verification`。
- **`.superpowers/sdd/` 下的脚本不是幂等的**（m1–m14 会改真实文件，自行备份/还原；m18 是 e2e）。

## 七、快速上手

```bash
cd d:/coding/powerMcp_Pskills

# 1. 起网关（带 DeepSeek）
cd gateway
POWERMCP_LLM_BASE_URL=https://api.deepseek.com \
POWERMCP_LLM_API_KEY="$DEEPSEEK_API_KEY" \
POWERMCP_LLM_MODEL=deepseek-v4-pro \
../PowerMCP/.venv/Scripts/python.exe -m uvicorn \
  powermcp_gateway.api:create_app --factory --host 127.0.0.1 --port 8765

# 2. 打开 MVP（同源，避免跨源被拦）
#    http://127.0.0.1:8765/ui/mvp.html
#    调试模式：?selftest=1（自检渲染）· ?nosse=1（轻量）· ?dark（深色）

# 3. 设计令牌预览
#    http://127.0.0.1:8765/ui/preview.html

# 4. 端到端实测（一次调用内完成启停）
bash .superpowers/sdd/m18-mvp-e2e.sh
```

## 八、本会话产出的可复用探针

| 脚本 | 作用 |
|---|---|
| `.superpowers/sdd/m16-deepseek-toolcheck.py` | 测模型是否支持工具调用 + 流式 |
| `.superpowers/sdd/m17-gateway-chat-live.py` | 网关 + LLM 端到端对话（含密钥不外泄断言） |
| `.superpowers/sdd/m18-mvp-e2e.sh` | MVP 端到端（渲染 / 自检 / 对话 / 截图 / console 报错） |
| `.superpowers/sdd/m15-module-gaps.py` | 模块扩展点缺口实测复现 |
| `.superpowers/sdd/m14-tokens-guardrail.py` | 设计令牌双护栏的变异探针 |
| `.superpowers/sdd/m{1..13}-*.py` | 各网关单元的变异探针（累计 **69+ 条全红**） |
