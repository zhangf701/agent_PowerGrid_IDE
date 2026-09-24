# PowerMCP 仓库扫描报告

- **扫描日期**：2026-09-21
- **目标仓库**：https://github.com/Power-Agent/PowerMCP （PUBLIC）
- **扫描提交**：`a21ea6b8813f5af5516d4f18596a4fadbb36b8a5` （2026-09-20 15:19:59 -0400，`main`）
- **本地路径**：`d:/coding/powerMcp_Pskills/PowerMCP`（shallow clone，depth 50）
- **版本**：`powermcp == 0.4.0`（`powermcp/__init__.py` / `pyproject.toml` 一致）

---

## 一、仓库定位与规模

| 指标 | 值 |
|---|---|
| 文件总数 | 2375（不含 `.git`） |
| Python 文件 | 103 个，27,709 行 |
| JSON 文件 | 2190 个（**2185 个集中在 `PSSE/psspy_command_json/`**） |
| Markdown | 23 个，3836 行 |
| 其他 | `.txt` ×26、`.toml` ×4、`.dss` ×3、`.sav/.pwd` 各 2 |

**核心结论**：`2190 个 JSON` 不是数据集，而是 **PSS/E `psspy` API 函数的自动生成规格**（每个函数一个 JSON，形如 `abusreal.json`、`branchar.json`、`a2trmdcconvreal.json`）。这是全仓最大的文件量来源，也是打包时必须原样保留的关键资产。

仓库定位（`pyproject.toml:14`）：面向电力系统软件的 MCP server 集合，覆盖 PowerWorld、OpenDSS、PSS/E、pandapower、PyPSA 等。

---

## 二、架构总览

### 2.1 双层结构

```
PowerMCP/                         ← Monorepo
├── powermcp/                     ← ★ 核心胶水包（pip 发行版本体）
│   ├── registry.py               ← 声明式单一真源（16 个 Tool 定义）
│   ├── runner.py                 ← 三种启动方式
│   ├── config.py                 ← 四级路径解析
│   ├── sandbox.py                ← 路径围笼（re-export powerio 策略）
│   ├── solver_case.py            ← PowerIO IR → 求解器的路由
│   ├── doctor.py / detect.py / paths.py / wizard.py / cli.py
│   └── clients/                  ← 客户端配置写入器
│       claude_desktop.py / claude_code.py / codex.py
├── <15 个厂商目录>/               ← 各自独立可运行的 server
│   pandapower, PyPSA, ANDES, Egret, surge, OpenDSS, HOPE, GenX,
│   PSCAD, PSSE, PSLF, PowerWorld, PowerFactory, LTSpice, PLEXOSDB
└── tests/                        ← 跨切面测试套件
```

**设计要点**：厂商目录在仓库根目录保持原样、可独立运行（`python pandapower/panda_mcp.py`）；`powermcp` 通过 hatchling `force-include` **零源码改动**地把它们映射进 wheel 的 `powermcp/_servers/<Dir>`。

### 2.2 声明式注册表（`powermcp/registry.py`）

`Tool` 是一个 `frozen dataclass`，为每个 server 描述：启动方式、pip extra、是否 Windows-only、需要捕获的本地软件路径。**CLI、runner、wizard、doctor、客户端配置写入器全部从这里读元数据** —— 单一真源，无重复定义。

`resolve_server_dir()`（`registry.py:53`）同时适配三种布局：
1. 已安装 wheel → `powermcp/_servers/<dir>`
2. editable 安装 / 原始 checkout → `<repo>/<dir>`

### 2.3 三级启动模型（`powermcp/runner.py`）

| `run_kind` | 机制 | 使用者 | 原因 |
|---|---|---|---|
| `script` | `runpy.run_path(..., run_name="__main__")` | 多数 server | 只把脚本自身目录入 `sys.path`，**刻意不加父目录** |
| `module` | `runpy.run_module(..., alter_sys=True)` | HOPE、PSCAD | 包结构需要模块根入 `sys.path` |
| `package` | `runpy.run_module(...)`，不动 `sys.path` | powerio | server 由依赖本身提供，本仓不打包副本 |

**`_launch_script` 里有个精细的回避**（`runner.py:87-97`）：父目录**不能**进 `sys.path`，因为仓库根下有名为 `pandapower/`、`surge/` 的目录，会把同名已安装库遮蔽掉。这是真实踩过的坑，注释写明了原因。

### 2.4 跨 server 交换格式：PowerIO IR

README `## Case compilation between servers (PowerIO)` 段落定义了本仓的**数据交换契约**：

- 交换格式是 **PowerIO IR generation 2**（`"schema": "pio-ir"`, `"version": 2`）
- powerio **自带** MCP server（`python -m powerio.mcp`），本仓不复制其代码，`powermcp run powerio` 直接跑依赖里的那个
- 所有适配器（pandapower / PyPSA / ANDES / Egret）统一接受 `powerio_ir` 参数
- 明确边界：**"PowerMCP itself never re-parses, re-validates, or recomputes what PowerIO states"** —— 只负责路由，不重算

`powermcp/solver_case.py`（523 行）实现"从 PowerIO 值中选一个类型化状态交给平衡求解器"。

---

## 三、工具接口面（16 个 server）

### 3.1 关键发现：存在**两种不同的工具注册风格**

初版用装饰器正则 `@mcp.tool` 统计时，**OpenDSS 与 PSCAD 计数为 0**，原因是它们不用装饰器语法：

- **PSCAD** — 函数式注册：`mcp.tool()(func)`，分散在 `pscad_mcp/tools/{app,project,data,simset}_tools.py` 的 `register_*_tools(mcp)` 中
- **OpenDSS** — 工厂模式：`opendss_mcp.py`（仅 618 字节的薄壳）调用 `core.server.create_mcp()`，工具在 `opendss_tools/*.py` 内注册

这意味着**任何基于装饰器正则的静态统计都会漏掉这两个 server**。下表已修正：

### 3.2 工具数量（双路交叉校验后）

下表的工具数为**两次独立统计的一致结果**：一次是我用 `grep` 扫描注册点，一次是子 agent 逐文件核对注册函数体。两者**逐项吻合**。

| Server | 工具数 | 注册风格 | 传输 | 目录 |
|---|---:|---|---|---|
| OpenDSS | **55** | 函数式（工厂） | stdio | `OpenDSS/` |
| surge | 44 | 装饰器 | stdio | `surge/` |
| PLEXOSDB | **2 自有 + 29 上游 = 31** | 装饰器（挂在上游对象上） | stdio | `PLEXOSDB/plexosdb_mcp/` |
| PSCAD | **26** | 函数式 | stdio | `PSCAD/pscad_mcp/` |
| PowerFactory | 22 | 装饰器 | **stdio 或 SSE** | `PowerFactory/` |
| HOPE | 20 | 装饰器 | stdio（另有 HTTP 只读变体） | `HOPE/src/hope_mcp_server/` |
| PyPSA | 17 | 装饰器 | stdio | `PyPSA/` |
| PowerWorld | 14 | 装饰器 | stdio | `PowerWorld/` |
| PSLF | 12 | 装饰器 | stdio | `PSLF/` |
| pandapower | 8 | 装饰器 | stdio | `pandapower/` |
| LTSpice | 7 | 装饰器 | stdio | `LTSpice/` |
| GenX | 7 | 装饰器 | stdio | `GenX/` |
| ANDES | 6 | 装饰器 | stdio | `ANDES/` |
| PSSE | 5 | 装饰器 | stdio | `PSSE/` |
| Egret | 5 | 装饰器 | stdio | `Egret/` |
| powerio | **10** | — | — | 不在本仓，来自 `powerio` 依赖 |
| **合计（本仓自有作者）** | **≈250** | | | |

> **OpenDSS 拆分**（55）：`model.py` 27 + `results.py` 23 + `configuration.py` 2 + `interactive_view.py` 2 + `simulation.py` 1。

#### 运行时复核（2026-09-21 实测）

静态统计曾出过一次错（漏掉 OpenDSS/PSCAD），因此对**已安装的 5 个 server** 做了运行时复核：实际拉起 server、经 stdio 握手、调 `list_tools` 取真实返回值。

核验脚本：[tools/runtime_tool_census.py](../../tools/runtime_tool_census.py)

```bash
PYTHONIOENCODING=utf-8 ./PowerMCP/.venv/Scripts/python.exe tools/runtime_tool_census.py
```

| server | 运行时 `list_tools` | 静态统计 | 结论 |
|---|---:|---:|---|
| pandapower | 8 | 8 | ✓ MATCH |
| pypsa | 17 | 17 | ✓ MATCH |
| surge | 44 | 44 | ✓ MATCH |
| hope | 20 | 20 | ✓ MATCH |
| powerio | 10 | 10 | ✓ MATCH |

**结论**：本仓 15 个 server 的静态计数中，已有 4 个（pandapower / PyPSA / surge / HOPE，合计 89 个工具）**经运行时证实**。其余 server 因未安装对应 extra 或依赖本机商业软件，仍为静态统计值（已双路交叉校验，但仍属推断）。

### 3.3 ★ 工具名跨 server 冲突 —— 对"构建 Skill"影响最大的一条

子 agent 扫描发现大量**同名工具**分布在不同 server：

| 工具名 | 出现在 |
|---|---|
| `open_case` / `solve_case` | PSSE、PSLF |
| `load_network` | pandapower、PyPSA、surge |
| `run_power_flow` | pandapower、PyPSA、PowerWorld |
| `run_contingency_analysis` | pandapower、PyPSA、PowerWorld、PowerFactory |
| `get_network_info` | pandapower、PyPSA、surge |
| `add_bus` / `add_generator` / `add_load` / `add_line` | ANDES、PyPSA、pandapower、surge、PSLF |
| `read_documentation` | PSCAD（及可能的 HOPE 系列 `hope_read_output` 风格） |

**含义**：若把多个 server 挂进同一个 MCP 客户端命名空间，模型面对 `load_network` 时**无法从名字判断该调用哪一个**。这不只是命名问题 —— 不同 server 的同名工具语义、参数、单位可能不同（例如 PSSE 的 `solve_case` 走 `psseinit` + 平衡潮流，PSLF 的走 GE 求解器）。

### 3.4 其他值得注意的实现

- **无任何运行时 mock/stub 降级路径**。全仓 15 个 server 在生产代码中**没有** mock/fake/stub（仅测试里用 `unittest.mock`）。厂商库缺失时的统一做法是**延迟导入 + 可操作报错**：server 本身能启动，直到真正调用该工具才失败。涉及 `PSSE._ensure_psse()`、`PowerFactory._ensure_powerfactory_on_path()`、`GenX.genx_dir()`、PSCAD 等。

- **PLEXOSDB 的自遮蔽陷阱**：本仓包目录**故意**命名为 `plexosdb_mcp` 以镜像上游，因此 `run_kind` **刻意不用 `module`**（`registry.py:224-232`）—— 否则 `PLEXOSDB/` 入 `sys.path` 后 `import plexosdb_mcp` 会解析到自己而非 site-packages 的上游包。改用 `script` 只把文件自身目录入路径。注释注明"a self-shadow, confirmed by direct testing"。

- **GenX 的 `tool_logic/`**：**零个** `@mcp.tool`（6 个文件全部为纯逻辑）。`server.py` 是唯一注册点，导入 `tool_logic/` 并在注册前包 `_guarded()` + 沙箱检查。`tool_logic/slurm.py` 负责生成 SLURM 脚本并经 `sbatch` 提交，设 `SBATCH_TIMEOUT_S = 60` 上限（防止卡死的调度器拖垮单线程 stdio 循环），作业名以 `^[A-Za-z0-9._-]{1,64}$` 校验。

- **PowerFactory 两个文件的真实分工**（澄清我最初的疑问）：
  - `MCP_PowerFactory.py` —— **唯一的 MCP server**，22 个工具
  - `Agent_DIgSILENT.py`（2327 行，仓库最大文件）—— **仿真引擎，零个 MCP 工具**。它是可独立使用的库（`DIgSILENTAgent.run_pipeline()`），带自有 `__main__` 入口，**可不经 MCP 直接跑**；`MCP_PowerFactory.py` 延迟导入它来支撑 `run_simulation` / `run_custom_case`。

- **PSCAD 的可靠性层**：30 秒执行看门狗（应对 PSCAD 冻结/模态对话框）、OS 级进程监控、线程安全命令队列（PSCAD 的 COM/RMI 接口是单线程的）、`ThreadPoolExecutor` 封装，以及从 `mhi-pscad` 抽取 `@rmi`/`@requires` 装饰器与类型提示生成 Markdown 的 AST 文档器。

- **PSLF 的外部进程调用**：`run_contingency_analysis` 写 `template.ctab` + `run.bat`，用 `subprocess.run(..., shell=True)` 调 **ProvisoHD**，路径**硬编码**为 `C:\Program Files (x86)\ProvisoHD\Release`，以 `jre\bin\java.exe ... gui.Face1 -batch` 启动，结果经 `pandas.read_excel` 读回。

- **HOPE 的只读模式**：`create_mcp_server(read_only=True)` 只注册读工具，5 个写/执行工具被 `if not read_only:` 门控；且只读模式下**拒绝非回环地址绑定**（`server.py:85`）。这是全仓唯一的"分级权限"设计。

---

## 四、安全控制面 ★

这是本仓**最值得关注**的部分，投入远超一般开源 MCP 项目。

### 4.1 路径围笼（Path Containment）

`powermcp/sandbox.py` 的定位（`sandbox.py:1-19`）写得非常明确：

> "An MCP tool argument is attacker-influenced input: whatever the model was persuaded to ask for, the server does."（MCP 工具参数是**受攻击者影响的输入**：模型被说服要什么，服务器就执行什么。）

策略实现不在本仓，而是 **re-export `powerio.mcp.sandbox`** —— 避免两份策略实现走样（"no second copy to keep in step"）。配置方式：环境变量 `POWERIO_MCP_ALLOWED_ROOTS`（`os.pathsep` 分隔的目录列表）。

关键性质：**先解析、后比较**，所以 `..` 段和指向根外的符号链接都逃不掉（"it is the real target that is compared, not the spelling"）。

`ensure_checked_directory()` 额外处理了"多级父目录都不存在"的场景，并专门为 Windows 加了锚点检查（不可用盘符/UNC 锚点的父目录是锚点自身）。

### 4.2 ★ AST 静态强制检查 —— 本仓最有特色的工程实践

`tests/test_sandbox.py:249-286` 定义 `GUARDED` 字典（声明每个 server 中接收模型路径参数的 tool 及其参数名），然后用 `ast.parse` + `ast.walk` **静态解析源码**，断言每个声明的函数真的调用了 `checked_path`：

```python
def test_every_path_taking_tool_checks_its_argument(server):
    tree = ast.parse((REPO / server).read_text(encoding="utf-8"))
    # 遍历 FunctionDef，检查函数体内是否调用了 checked_path
```

**这不是单元测试，是"契约一致性门禁"**：`GUARDED` 是人工维护的声明，AST 检查强制源码符合声明。新增一个接收路径的 tool 却忘了走围笼，CI 会直接红。

### 4.3 PSS/E 命令禁止清单（prompt-injection → RCE 防御）

`PSSE/psse_mcp.py:108` 定义 `_PROHIBITED_PSSPY_COMMANDS`（22 条），注释直指动机：

> "These APIs load, execute, or activate programs, native libraries, Python callbacks, user extensions, or PSS/E command files. **Path containment does not make executable input safe** for the generic MCP dispatcher."

被禁的命令类别：

| 类别 | 命令示例 |
|---|---|
| 启动任意程序 | `launch_program`、`user` |
| 执行命令文件 | `runiplanfile`、`runrspnsfile` |
| **Python 代码注入** | `addpythonconditionelement`、`addpythoncontingencyelement`、`addpythonremedialactionelement` |
| 加载原生库/模型 | `addmodellibrary`、`dropmodellibrary`、`allow_pssuserpf`、`retry_pssuserpf` |
| RAS 文件（可含 Python） | `read_ras`、`append_ras`、`accc_ras` |
| I/O 重定向 | `set_input_dev`、`setdiagautofile` |

拦截点在 `PSSE/psse_mcp.py:611`，**早于引擎启动**，且由测试强制：

```python
def test_psse_generic_dispatch_refuses_executable_commands_before_engine_start(monkeypatch, command):
    monkeypatch.setattr(psse_mcp, "_ensure_psse", unexpected_engine_start)
    ...
    assert engine_starts == []   # 引擎绝不能启动
```

另有 `test_psse_prohibited_command_list_matches_the_server` 保证**测试清单与服务端清单不脱节**，以及 `test_psse_path_metadata_covers_every_pathish_spec_parameter` 保证 2185 份 JSON 规格里所有"类路径"参数都被覆盖。

**评价**：这是一套针对"LLM 被诱导调用危险电力系统 API"的纵深防御，设计意识高于同类项目。

---

## 五、工程化与 CI

### 5.1 CI 工作流

| 工作流 | 触发 | 要点 |
|---|---|---|
| `test.yml` | push `main` / PR | 矩阵 `3.10, 3.12, 3.13, 3.14`；跑 `tests/` + PowerFactory + HOPE + PSCAD + PLEXOSDB + surge 各套件 |
| `publish.yml` | Release published / 手动 | PyPI **Trusted Publishing (OIDC)**，无 API token 落库 |

### 5.2 ⚠️ 发现：CI 矩阵缺 Python 3.11

- `pyproject.toml:24` classifiers 声明支持：3.10 / 3.11 / 3.12 / 3.13 / 3.14
- `.github/workflows/test.yml` 矩阵：`["3.10", "3.12", "3.13", "3.14"]`

CI 注释自称 *"floor of requires-python, and every version the classifiers claim"*，但**实际遗漏 3.11** —— 声明与实际验证不一致。属轻微问题（非缺陷），但会掩盖 3.11 特有的 `tomllib`/依赖解析差异。

### 5.3 打包约束（Windows 相关）

`pyproject.toml:1-6` 说明必须**零源码改动**映射厂商目录，原因包括：
- 保留 PSSE 的 2184 份 JSON 命令规格
- 保留 OpenDSS **大小写敏感**的 `.DSS` 文件（Windows 上易被破坏）

`[tool.hatch.build.targets.wheel.force-include]` 逐项列出映射；PowerFactory 因只需部分文件而逐文件列出。

### 5.4 依赖锁定策略

`dependencies` 中有大量**带原因的版本钉死**，注释解释了每个上界：

- `pypsa>=0.35.2,<2` — 0.35.2 是最后一条兼容 py3.10 的现代优化器线
- `pandas>=2.0,<3` — pandapower 的 PYPOWER 转换器尚不支持 pandas 3
- `mcp>=2,<3` — mcp 2.0 把 server 类从 `mcp.server.fastmcp.FastMCP` 移到 `mcp.server.mcpserver.MCPServer`
- `powerio[mcp,matrix]>=0.11.2,<0.12`

`plexosdb` extra 的注释尤其详尽（`pyproject.toml:97-106`），记录了上游 `r2x==2.1.0` / `plexos2duckdb` 的连锁版本问题及规避方式。

---

## 六、本机运行前置条件检查

### 6.1 初检发现（2026-09-21 扫描时）

按全局规则执行前置条件检查，最初**存在阻塞**：

| 检查项 | 初检状态 | 说明 |
|---|---|---|
| 默认 `python` | ❌ **3.9.23** | PowerMCP 要求 `>=3.10`，默认解释器无法安装 |
| `powermcp` / `powerio` / `mcp` / `pandapower` / `pypsa` | ❌ 均未安装 | |

**已存在但不可直接复用的解释器**：

| 环境 | Python | 问题 |
|---|---|---|
| `andes_env` | 3.10.19 | 有 andes 1.9.3，但缺核心依赖 |
| `powerGrid_RL` | 3.10.19 | 缺核心依赖 |
| `power_grid_rag` | 3.11.15 | 其 `mcp 1.27.0` **低于**要求的 `mcp>=2` |
| `base` / `drl-andes` | 3.8 / 3.9 | 版本过低 |

### 6.2 处置结果（✅ 已解决，详见环境搭建记录）

经用户确认后，采用 `uv` 建立**独立隔离环境**，未触碰任何现有 conda 环境或系统配置：

- 位置：`d:\coding\powerMcp_Pskills\PowerMCP\.venv`（Python 3.12.6，已在 `.gitignore` 中）
- 安装范围：**核心 + `[hope,surge]`**（用户选定）
- `powermcp doctor` 与运行时 `list_tools` 核验**均通过**

完整过程见 [2026-09-21-env-setup.md](2026-09-21-env-setup.md)。

### 6.3 ⚠️ Git 代理配置与本次无关但已记录

`git config --global http.proxy = http://127.0.0.1:7897`，但该端口**无监听**。实际 VPN 代理端口为 `127.0.0.1:10090`。

本次全部网络操作使用**命令级覆盖**，**未修改** `.gitconfig`：
```bash
git -c http.proxy=http://127.0.0.1:10090 -c https.proxy=http://127.0.0.1:10090 clone ...
```

### ⚠️ Git 代理配置已过期

`git config --global http.proxy = http://127.0.0.1:7897`，但该端口**无监听**（代理软件未运行或端口已变更为 `10090`）。直连 GitHub 正常。

本次扫描使用**命令级覆盖**绕过，**未修改**你的 `.gitconfig`：
```bash
git -c http.proxy=http://127.0.0.1:10090 -c https.proxy=http://127.0.0.1:10090 clone ...
```

---

## 七、观察与风险汇总

| # | 观察 | 严重度 | 说明 |
|---|---|---|---|
| 1 | **工具名跨 server 冲突** | **高（架构）** | 同名工具语义可能不同，多 server 共存时模型无法靠名字消歧 |
| 2 | Python 3.9 为默认解释器 | **高（本机）** | 直接阻塞安装 |
| 3 | 闭源 server 依赖本机商业软件 | 高（使用侧） | PowerWorld / PSSE / PSLF / PowerFactory / PSCAD 需各自授权与安装 |
| 4 | 无运行时降级路径 | 中 | 工具调用才失败；对 Skill 的"可用性探测"设计有影响 |
| 5 | 两种工具注册风格并存 | 中 | 装饰器正则统计会漏 OpenDSS/PSCAD |
| 6 | `plexosdb-mcp` 未上 PyPI | 中 | 需手动 git 安装，`pip install powermcp[all]` 无法开箱即用 |
| 7 | CI 矩阵漏 Python 3.11 | 低 | classifier 声明 3.11 但未验证 |
| 8 | 安全控制面成熟 | — | **正向**：路径围笼 + AST 门禁 + 命令黑名单 + HOPE 只读模式 |
| 9 | 版本 0.4.0 / Alpha | 信息 | `Development Status :: 3 - Alpha`，API 可能变动 |

### 7.1 关于「工具名冲突」的进一步说明

这不是缺陷，而是**多 server 聚合的固有代价**。但对本项目（构建 Skill）影响直接：

- 若 Skill 需要"跨工具编排"（如 pandapower 算潮流 → PyPSA 做优化），必须**显式指定目标 server**，不能依赖工具名
- 若 Skill 只绑定单个 server，则无冲突问题
- PowerIO IR 是官方给出的跨 server 数据契约 —— 这可能是比"直接串联工具"更稳的编排路径

---

## 八、后续建议（待你确认，不自行推进）

1. **环境搭建**（阻塞性，优先）：按第六节方案 A 或 B 建立可用 Python 环境并安装 `powermcp`。
2. **运行时工具清单核验**：本报告的工具数来自静态统计。装好环境后可运行 `powermcp doctor` 与 `powermcp list`，并通过 MCP 客户端实际调用 `list_tools` 做**运行时交叉校验**。
3. **明确本项目的目标**：工作目录名 `powerMcp_Pskills` 暗示后续要"基于 PowerMCP 构建 Skills"。若是，下一步应确定：
   - 目标 server 子集（全部 16 个？还是仅 pandapower/PyPSA/PowerIO 这类无需商业授权的？）
   - Skill 的粒度（每个 tool 一个技能？还是每个业务流程一个？）
   - 是否需要 PowerIO IR 作为技能间的数据契约

---

## 附：本次扫描的验证方法

所有结论均来自以下可复现操作，未含推测：

| 结论 | 验证方式 |
|---|---|
| 文件规模 | `find` + `sed` 扩展名统计 |
| 工具数量 | `grep` 装饰器计数 **+** 对 OpenDSS/PSCAD 的**反向核查**（发现计数为 0 后逐一排查注册方式） |
| 安全机制 | 直接 `Read` 源码 + `Read` 测试断言 |
| CI 矩阵缺口 | 对照 `pyproject.toml` classifiers 与 `test.yml` matrix |
| 本机环境 | 逐个解释器执行 `--version` 与 `pip list` |
| 代理问题 | `git config --get-regexp` + `netstat` + 直连 `curl` 对照 |
