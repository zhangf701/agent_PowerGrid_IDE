# #6 结案 + #8 补测通过 + F-1 修复（围笼路径形态 · 输入规范化）

日期：2026-09-26 ｜ 前置：`2026-09-26-mvp-manual-test-results.md`（#6/#8 的原始记录）
方法：起一次网关，**全部走 HTTP 直构**（不依赖界面与模型），修复后再闭环验证。

> ⚠️ **本机 HTTP 探测必须加 `--noproxy '*'`** —— 沙箱注入了
> `http_proxy=127.0.0.1:62137`，localhost 会被代理劫持并返回 **502**，
> 极易误判为「网关没起来」。与用户 VPN 的 `127.0.0.1:10090` 是两回事。

## 结论速览

| 项 | 结果 |
|---|---|
| **#6 登记误报 400** | **结案 = 输入侧**（粘贴带入引号），**不是网关 bug**；已加输入规范化 + 可操作 400 文案 |
| **#6 涉及的 409 围笼分支** | **首次真实触发** ✓（此前从未被真跑过） |
| **#8 契约拦截** | **通过 3/3**（`missing_required` / `wrong_type` / `unknown_arg`） |
| **★ F-1** `run_gateway.sh` 使围笼整体失效 | **已修**（`pwd -W`）+ 闭环验证 |
| 测试基线 | **501 → 515 passed, 2 deselected**（+14）；变异探针 **2/2 全红** |

---

## 一、#6 结案：输入侧

### 1. 二分结果

| 探针 | 请求 | 结果 |
|---|---|---|
| A | `POST /cases`，**干净**路径 `C:\Users\Z\Downloads\_科研项目\case5.m` | **HTTP 201**，`available=true`、`within_allowed_roots=false` |
| B | 对照：项目内 `examples\data\case39.m` | HTTP 200（已登记过，`created=false`） |

**A 的 `available=true` 是关键**：它意味着网关进程**真的读到了**该文件
（`view()` 要 `stat()` + 算 sha256 才能填 `current_size` / `current_sha256`）。
⇒ **排除「网关运行时读不到文件」**，问题在**到达网关的字符串**。

### 2. 污染形态穷举（探针 `.superpowers/sdd/m34-case-register-input.py`）

| # | 形态 | 结果 |
|---|---|---|
| ① | 干净（基线） | **200** |
| ② | Explorer「复制为路径」双引号 `"..."` | **400** 算例文件不存在：`"C:\...\case5.m"` |
| ③ | 前置零宽空格 U+200B | **400** |
| ④ | 全角反斜杠 U+FF3C | **400** |
| ⑤ | 正斜杠 `/` | **200**（`Path` 在 Windows 上等价） |
| ⑥ | 尾部空格 | **200**（前端 `trim()` + API `strip()` 都清掉） |
| ⑦ | **单引号包裹** `'...'` | **400** 算例文件不存在：**`'C:\Users\Z\Downloads\_科研项目\case5.m'`** |

**★ ⑦ 的回显与张老师记录在指引里的原文逐字符一致**（含那对单引号）。
⇒ **真凶是输入被引号类字符包裹**，最可能是从别处粘贴时带上的。

### 3. 修复（已实施）

**服务端（唯一收口点，`cases.py`）**

- 新增 `normalize_case_path(raw) -> (normalized, notes)`：
  去除首尾空白 · 剥离**首尾成对**引号（`"` `'` 以及中文弯引号，支持成对嵌套）·
  剔除零宽字符（U+200B/200C/200D/2060/FEFF）· 全角标点归一为半角（`＼／：．`）。
  **只映射在 Windows 路径里不可能合法出现的标点**，故是无损的。
- 新增 `suspicious_case_path(raw) -> list[str]`：只报**类别名**（不回显不可见字符）。

**API（`api.py`）**

- `_parse_case_request` 归一后返回 `path_notes`。
- 登记成功：**仅当确有改动**时返回 `path_normalized` + `path_used` ——
  **不静默修正**，如实告诉调用方路径被改成了什么。
- 400 文案补上**可操作**线索（`_case_error_detail`）：
  「路径含可疑字符：引号 —— 常见于从聊天/文档粘贴。请改用纯文本粘贴，或清掉路径外层的引号」
  ＋「已自动归一化：剥离首尾引号；实际检查的是 `…`」。

**前端（`frontend/mvp.html`）**

- 登记成功后，若响应带 `path_normalized`，在系统提示里显示「路径已自动归一化：…」。

**⚠️ 未做**：`suspicious_case_path` **不把中文目录名当可疑字符**（有专门测试钉住）——
否则 #6 会变成大面积误报。

---

## 二、#8 契约拦截补测：通过 3/3

会话 `be1baacc6cb4`，`servers=["surge","powerio","pandapower","pypsa","andes"]`。

| # | 违规类型 | 请求 | 响应 |
|---|---|---|---|
| 1 | `missing_required` | `surge.load_network` + `{}` | `ok:false`，`violations[0].arg=file_path`「缺少必填参数 `file_path`」 |
| 2 | `wrong_type` | `surge.load_network` + `{"file_path":123}` | `ok:false`，「参数 `file_path` 期望 string，实际 int」 |
| 3 | `unknown_arg` | `pypsa.run_power_flow` + `{"network_name":"case39","linearized":true}` | `ok:false`，「参数 `linearized` 不在工具声明的 input_schema 中 —— 引擎可能静默忽略它」 |

三次响应均为 `result:null` + **`remounted:false`** —— 后者证明**调用根本没转发到 server**
（fail-closed 在网关校验层就拦住了）。第 3 条即方案 §2.3 里 PyPSA `linearized`
被 `**kwargs` 静默吞掉那个事故的**复刻验证**。

⇒ **#8 由「未完成」转为「通过」，覆盖三类违规（超出原计划的 1 类）。**
对话路径触发不可靠（模型会拒绝/改道）的结论不变；**验收以 HTTP 直构为准绳**。

---

## 三、F-1：`run_gateway.sh` 使允许根写错，围笼整体失效（已修）

### 现象与根因

用 `./run_gateway.sh` 启动后打印 `fence = /d/coding/powerMcp_Pskills;...`（POSIX 形态），
网关进程内解析出的允许根是 `D:\d\coding\powerMcp_Pskills`（**多一层 `d`**）。

`run_gateway.sh:15` 原为 `ROOT="$(cd "$(dirname "$0")/.." && pwd)"` ——
Git Bash 的 `pwd` 给 `/d/...`，而 Windows Python 把前导 `/` 当作**当前盘根**：

```
Path('/d/coding/powerMcp_Pskills').resolve() → 'D:\d\coding\powerMcp_Pskills'
Path('/d/coding/powerMcp_Pskills').is_dir()  → False          ← 根根本不存在
```

`_is_within()`（`cases.py`）用 `target.relative_to(root)`，根不存在 → 恒 `False`。
**该行是已提交的原样，非本轮引入。**

### 影响面（功能阻断级）

| 算例 | `within_allowed_roots`（修复前） | 解析 |
|---|---|---|
| `examples\data\case39.m`（**项目内**） | **False** ← 应为 True | **409** ✗ |
| `C:\Users\Z\Downloads\_科研项目\case5.m`（项目外） | False（结论对，理由错） | 409 ✓（歪打正着） |

⇒ **用 `.sh` 启动的网关，「算例 → 解析 → IR → diagnostics」整条链路不可用**
（`_load_artifact_or_409` 在调用 server **之前**就按错误的根判 409）。
而 `run_gateway.cmd` 用 `%~dp0..`（`cmd.exe` 给原生 `D:\coding\...`）**正常** ——
这也解释了为何此前实测能跑通（张老师是双击 `.cmd`）。

### 修复

```bash
ROOT="$(cd "$(dirname "$0")/.." && (pwd -W 2>/dev/null || pwd))"
```

`pwd -W` 给原生形态（`D:/coding/powerMcp_Pskills`，`Path.resolve()` 正确）；
它是 MSYS 专有，故带回退以保真 Linux 可用。

### 闭环验证（用修复后的脚本重启）

| 检查 | 结果 |
|---|---|
| 启动日志 `fence =` | **`D:/coding/powerMcp_Pskills;C:\Users\Z\.powermcp`** ✓ |
| `case39.m` 视图 | `available=True` **`within_allowed_roots=True`** ✓ |
| `case39.m` 解析 | **HTTP 200**，`ir_bytes=52233` ✓ |
| `case5.m`（项目外）解析 | **HTTP 409**，提示的允许根正确 ✓ |
| 带引号路径登记 | **HTTP 200 + `path_normalized:["剥离首尾引号"]`** ✓ |

⇒ **围笼实现本身正确**，坏的只是 `.sh` 的路径形态。
同时这也**首次真实触发了 409 围笼分支**（单测里一直是 monkeypatch 覆盖）。

---

## 四、验证与护栏

| 项 | 结果 |
|---|---|
| 定向测试（`test_cases.py` + `test_api_cases.py`） | **61 passed** |
| 全量回归 | **515 passed, 2 deselected**（基线 501 → +14） |
| ★ **顺带确证** | **≈501 的基线估计成立**（+14 = 515），上期遗留的「待复跑确证」可关闭 |
| **变异探针**（`.superpowers/sdd/m35-case-normalize-mutation.py`） | **2/2 全红** —— 关闭归一化 / 关闭可疑字符检测，钉住它们的测试确实变红 |

新增测试覆盖：干净路径**逐字符不变**（防误报"已归一化"）· 成对/嵌套引号 ·
零宽字符 · 全角标点 · 正斜杠不被多手改 · 空白 trim ·
**中文目录名不得被当成可疑字符** · 干净路径的 400 不得出现假提示（反向断言）。

---

## 五、环境备忘与踩坑（可复用）

1. ⚠️ **本机 HTTP 探测一律 `--noproxy '*'`**（沙箱代理会把 localhost 变 502）。
2. ⚠️ **MSYS 会改写 Bash 参数里的 Windows 路径**：独立参数 `'C:\Users\Z'`
   → `C:/Users/Z`；JSON 块内的 `\\` 不受影响。
   ⇒ **含反斜杠的代码/数据不要用 shell 写入**（heredoc 同样被改）。
3. ⚠️ **本次踩过一次**：用 heredoc 追加测试文件时反斜杠被改写成 `/`，
   `_CLEAN` 变成 `C:/Users/...`，两个测试假失败。
   处置：`git checkout --` 恢复（两文件当时是干净的）→ 改用编辑工具重写。
   **教训：改代码用编辑工具，shell 只用来跑命令。**
4. `run_gateway.sh` 的 `fence =` 一行是**诊断网关围笼问题的第一现场**。

---

## 六、未决与交接

| # | 事项 | 状态 |
|---|---|---|
| 1 | `case5.m` 已登记（id `4da0b6c8d9f6`，项目外） | 本次验证副产物，**建议保留**（视图 2 测围笼分支要用）；移除：`DELETE /cases/4da0b6c8d9f6` |
| 2 | MVP 前端「脏路径 → 看到归一化提示」的交互 | 服务端已 E2E 验证；前端提示行过语法检查 + 无头渲染无报错，**交互需人工点一次确认** |
| 3 | 视图 2（算例库）迁移 | 未开始；**F-1 已修，阻塞已解除** |
| 4 | 探针 `m34-*` / `m35-*` | 已入 `.superpowers/sdd/`（gitignored） |

**本次未提交**（沿用上期建议：`frontend/` 骨架 + 文档一并提交）：
`gateway/run_gateway.sh` · `gateway/src/powermcp_gateway/cases.py` · `gateway/src/powermcp_gateway/api.py` ·
`gateway/tests/test_cases.py` · `gateway/tests/test_api_cases.py` · `frontend/mvp.html` · 本文件 + `_index.md`。
