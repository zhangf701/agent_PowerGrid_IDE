# 网关骨架 + 契约引擎 T0 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建一个本地网关，拉起 9 个开源 MCP server，对它们求值 **T0 静态契约**，并通过 HTTP 暴露「契约状态」。

**Architecture:** 新建独立仓库（根目录 `git init`），新增 `gateway/` 子项目。网关是一个 FastAPI 应用 + 一个复用 `PowerMCP/.venv` 的 MCP stdio 客户端层。契约求值器是若干独立纯函数模块，各自实现 `ContractEvaluator` 协议，由一个编排器统一调度并按 `(server, 版本)` 缓存。**不改动 `PowerMCP/` 一行**（继承其 *zero source mutation* 哲学）。

**Tech Stack:** Python 3.12（复用 `PowerMCP/.venv`）· FastAPI · uvicorn · `mcp>=2,<3` 官方 SDK · pytest + pytest-asyncio

## Global Constraints

- **Python 解释器**：一律使用 `PowerMCP/.venv/Scripts/python.exe`（本机默认 `python` 是 3.9，**低于项目要求的 3.10**，不可用）
- **`PowerMCP/` 与 `PowerSkills/` 是上游 clone，一行不改**；两者已在非 main 分支上**有意冻结**，不得切换分支
- **`PowerMCP/` 必须写进 `.gitignore`** —— 它是嵌套的 git 仓库，根目录 `git init` 后若不忽略，`git add -A` 会把它记成 gitlink 而非普通目录
- **契约编号与状态取值必须与《UI 设计规范》v1.2 严格一致**：
  - 契约编号 1–8 与方案 §2.2 一致（1 API 版本 / 2 文档-实现 / 3 参数 / 4 状态映射 / 5 命名空间 / 6 标识符 / 7 量纲 / 8 运行时依赖）
  - 状态：`satisfied` / `degraded` / `violated` / `unknown`（`unknown` 必带 `reason: 'structural' | 'incident'`）
  - 汇总优先级：`incident > violated > degraded > satisfied`；**结构性未知不参与主徽标竞争**，空集汇总为 `unknown`
- **server id 一律小写**（`pandapower` / `pypsa` / `surge` / `andes` / `egret` / `opendss` / `hope` / `genx` / `powerio`），取自 `powermcp/registry.py` 的 `Tool.name`，**不得用显示名**

### ⚠️ 环境事实（2026-09-24 实测更正 —— 首版预测错误，已修订）

**首版断言「hope / genx 缺 Julia 会拉起失败」是错的。** 实测：**9 个 server 全部正常拉起**
（pandapower 8 · pypsa 17 · surge 44 · andes 6 · egret 5 · **opendss 55** · hope 20 · genx 7 · powerio 10）。

**错因**：把**「引擎求解需要 Julia」**（真，见方案 §11.3 的 Julia 子进程管理）
与**「server 进程无法启动」**混为一谈。`list_tools` 只要求 server 模块**可导入**；
Julia 只在真正执行求解时才是必需的 —— 而 T0 契约**一次求解都不跑**。

**真实的可启动性风险是另一个**：缺 pip extra。此时错误形如
`LaunchError: ANDES: required package 'andes' is not installed. Install it with: pip install powermcp[andes]`。
`powermcp/registry.py` 的 `Tool.extra` + `install_hint()` 已经知道该怎么修 —— Task 1 必须把它取出来（见下）。

> 📌 **因此本计划的验收标准不得依赖"哪个 server 会失败"** —— 那是环境相关的。
> 只验收"**失败时是否给出了可执行的修复路径**"（方案 §4.4 硬要求）。
- 本项目根目录**原先没有版本控制**，且 2026-09-24 已发生过一次交付物被覆盖、无法恢复的事故 —— Task 0 的 `git init` 是本计划的前置条件

> ⚠️ **一条范围收窄，需在执行前知悉**：方案 §2.2 把契约 1（API 版本）列为「比对 `list_tools` 实际返回 vs **工具实现调用的 API**」。
> 经核实，这**不能可靠地静态判定** —— 真实缺陷 `net.deepcopy()` 的接收者 `net` 是局部变量，
> 其类型来自 `pp.create_empty_network()` 的返回值，AST 无法在不做类型推断的情况下确定。
> 因此 **Task 7 实现的是「启发式 + 显式未知」**：能看到的（模块级导入绑定的属性调用）给出判定，
> **看不到的一律返回 `unknown / structural`，绝不猜测**。这是对本计划范围的诚实收窄，不是实现缺陷。

---

## File Structure

```
d:/coding/powerMcp_Pskills/                 ← git init 于此
├── .gitignore                              ← 新增：忽略 PowerMCP/ 等
├── gateway/
│   ├── pyproject.toml                      ← 新增
│   ├── README.md                           ← 新增
│   ├── src/powermcp_gateway/
│   │   ├── __init__.py
│   │   ├── config.py                       ← 路径与超时解析
│   │   ├── inventory.py                    ← MCP 客户端 + 工具清单
│   │   ├── contracts/
│   │   │   ├── __init__.py
│   │   │   ├── model.py                    ← 状态模型 + 汇总（与 UI 规范对齐）
│   │   │   ├── registry.py                 ← 求值器协议 + 注册表
│   │   │   ├── namespacing.py              ← 契约 5
│   │   │   ├── doc_impl.py                 ← 契约 2
│   │   │   ├── conventions.py              ← 契约 6 / 7
│   │   │   ├── api_version.py              ← 契约 1
│   │   │   └── engine.py                   ← T0 编排 + 缓存
│   │   └── api.py                          ← FastAPI 应用
│   └── tests/
│       ├── test_config.py
│       ├── test_inventory.py
│       ├── test_contract_model.py
│       ├── test_contract_registry.py
│       ├── test_contract_namespacing.py
│       ├── test_contract_doc_impl.py
│       ├── test_contract_conventions.py
│       ├── test_contract_api_version.py
│       ├── test_engine.py
│       └── test_api.py
└── ui/                                     ← 本计划不涉及（子项目 1/5）
```

---

### Task 0: 仓库初始化与配置

**Files:**
- Create: `.gitignore`
- Create: `gateway/pyproject.toml`
- Create: `gateway/src/powermcp_gateway/__init__.py`
- Create: `gateway/src/powermcp_gateway/config.py`
- Test: `gateway/tests/test_config.py`

**Interfaces:**
- Consumes: 无（首个任务）
- Produces: `GatewayConfig` —— 后续所有任务通过它拿路径与超时
  - `GatewayConfig.powermcp_root: Path` · `GatewayConfig.python: Path` · `GatewayConfig.server_timeout_s: float`
  - `GatewayConfig.discover(root: Path | None = None) -> GatewayConfig`
  - 异常 `ConfigError`

- [x] **Step 1: 在项目根初始化 git 仓库**

```bash
cd d:/coding/powerMcp_Pskills
git init
```

> ⚠️ 这是环境变更操作，计划执行前需用户确认。若根目录已有 `.git` 则跳过本步。

- [x] **Step 2: 写 `.gitignore`（必须在任何 `git add` 之前）**

创建 `d:/coding/powerMcp_Pskills/.gitignore`：

```gitignore
# 上游 clone —— 各自是独立的 git 仓库，绝不能记成 gitlink
/PowerMCP/
/PowerSkills/

# 大体积数据与中间产物
/GridData/
/work/

# Python
__pycache__/
*.py[cod]
.venv/
*.egg-info/
.pytest_cache/

# 运行产物
*.log
gateway/.cache/
```

- [x] **Step 3: 验证 `PowerMCP/` 确实被忽略**

```bash
cd d:/coding/powerMcp_Pskills
git status --porcelain | grep -c "^?? PowerMCP/" || echo "OK: PowerMCP 未被跟踪"
git check-ignore -v PowerMCP/
```
Expected: `git check-ignore` 输出匹配到 `/PowerMCP/` 那一行；`grep -c` 输出 `0`。

- [x] **Step 4: 写 `gateway/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "powermcp-gateway"
version = "0.1.0"
description = "PowerMCP 本地网关：契约引擎 + 编排（P1 子项目 2）"
requires-python = ">=3.12"
dependencies = [
    "mcp>=2,<3",
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "pydantic>=2",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "httpx>=0.27"]

[tool.hatch.build.targets.wheel]
packages = ["src/powermcp_gateway"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
markers = [
    "integration: 需要真实拉起 MCP server（慢，约 30–90 秒/个）",
]
```

- [x] **Step 5: 安装到 `PowerMCP/.venv`（可编辑模式）**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pip install -e ".[dev]"
```
Expected: `Successfully installed powermcp-gateway-0.1.0`（或已安装的最新版本提示）。

- [x] **Step 6: 写失败的测试 `gateway/tests/test_config.py`**

```python
from pathlib import Path

import pytest

from powermcp_gateway.config import ConfigError, GatewayConfig


def test_discover_finds_repo_and_interpreter():
    cfg = GatewayConfig.discover()
    assert cfg.powermcp_root.is_dir()
    assert (cfg.powermcp_root / "powermcp" / "registry.py").is_file()
    assert cfg.python.is_file()
    assert cfg.python.name == "python.exe"


def test_discover_from_explicit_root(tmp_path: Path):
    # 路径分隔符跨平台：Windows 上异常消息里是 powermcp\registry.py
    with pytest.raises(ConfigError, match=r"powermcp[\\/]registry\.py"):
        GatewayConfig.discover(root=tmp_path)


def test_discover_reports_missing_venv(tmp_path: Path):
    # 造一个只有 registry.py、没有 .venv 的假仓库根
    (tmp_path / "powermcp").mkdir()
    (tmp_path / "powermcp" / "registry.py").write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match=".venv"):
        GatewayConfig.discover(root=tmp_path)
```

- [x] **Step 7: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_config.py -v
```
Expected: FAIL —— `ModuleNotFoundError: No module named 'powermcp_gateway.config'`

- [x] **Step 8: 写 `gateway/src/powermcp_gateway/config.py`**

```python
"""网关的路径与超时解析。

本机默认 `python` 是 3.9，低于项目要求的 3.10，因此一律使用 PowerMCP 的 venv 解释器。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    """网关配置无法解析。"""


def _default_root() -> Path:
    """默认指向 PowerMCP 仓库根。

    路径推演：gateway/src/powermcp_gateway/config.py
      parents[0]=powermcp_gateway  [1]=src  [2]=gateway  [3]=<项目根>
    而 PowerMCP 仓库在 <项目根>/PowerMCP 下，故需再拼一层。
    """
    return Path(__file__).resolve().parents[3] / "PowerMCP"


@dataclass(frozen=True)
class GatewayConfig:
    powermcp_root: Path
    python: Path
    server_timeout_s: float = 90.0

    @classmethod
    def discover(cls, root: Path | None = None) -> "GatewayConfig":
        root = Path(root) if root is not None else _default_root()

        registry = root / "powermcp" / "registry.py"
        if not registry.is_file():
            raise ConfigError(
                f"未找到 {root / 'powermcp' / 'registry.py'} —— "
                f"root 应指向 PowerMCP 仓库根，实际为 {root}"
            )

        python = root / ".venv" / "Scripts" / "python.exe"
        if not python.is_file():
            raise ConfigError(
                f"未找到解释器 {python} —— "
                f"请先在 {root} 下建好 .venv（本机默认 python 是 3.9，不可用）"
            )

        if sys.version_info < (3, 10):
            raise ConfigError(
                f"网关自身运行在 Python {sys.version_info[:2]} 上，低于要求的 3.10"
            )

        return cls(powermcp_root=root, python=python)
```

- [x] **Step 9: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_config.py -v
```
Expected: PASS（3 passed）

- [x] **Step 10: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add .gitignore gateway/
git commit -m "feat(gateway): 仓库初始化与配置解析"
```

---

### Task 1: MCP 客户端与工具清单

**Files:**
- Create: `gateway/src/powermcp_gateway/inventory.py`
- Test: `gateway/tests/test_inventory.py`

**Interfaces:**
- Consumes: `GatewayConfig`（Task 0）· `powermcp.registry`（取 `extra` 与 `install_hint`）
- Produces:
  - `ToolRecord`：`server: str` · `name: str` · `description: str | None` · `input_schema: dict` · `output_schema: dict | None`
    - 类方法 `ToolRecord.from_sdk(server: str, tool: object) -> ToolRecord`
  - `ServerFailure`：`server: str` · `error: str` · `hint: str | None` · `probe_missing: str | None`
    （`error` 已含摊平后的完整原因文本；**无 `causes` 字段** —— 见执行记录的偏差表）
  - `ToolInventory`：`tools: tuple[ToolRecord, ...]` · `failures: tuple[ServerFailure, ...]` · **`requested: tuple[str, ...]`**
    - `names(server)` · `by_name(name)` · `servers()` · **`all_servers()`**
  - `def _describe_error(exc: BaseException) -> str` —— 递归摊平 `BaseExceptionGroup`，返回可读摘要
  - `def _is_timeout(exc: BaseException) -> bool` · `def _timeout_error(server, timeout) -> TimeoutError`
  - `def install_hint_for(server: str) -> tuple[str | None, str | None]` —— `(hint, probe_missing)`
  - `async def fetch_server_tools(cfg, server, timeout_s=None) -> list[ToolRecord]`
  - `async def build_inventory(cfg, servers, *, timeout_s=None) -> ToolInventory`

> ⚠️ **SDK 字段名是 `input_schema` / `output_schema`（snake_case）**，不是 JSON 里的 `inputSchema`。
> 已实测确认；写成驼峰会 `AttributeError`。

### ★ 两个必须修的缺陷（首版实测暴露）

#### 缺陷 A：`ExceptionGroup` 把可执行信息吞掉了

首版写的是 `f"{type(exc).__name__}: {exc}"`。而 anyio 把子进程错误包在 `ExceptionGroup` 里，
于是契约 8 的 detail 只剩：

```
unhandled errors in a TaskGroup (1 sub-exception)
```

真实的 `LaunchError: ANDES: required package 'andes' is not installed.
Install it with: pip install powermcp[andes]` **完全丢失**。

这直接违反**方案 §4.4**：*「⚠️ / ❌ 必须给出可执行修复路径」* —— 也让能力矩阵的修复指引失效。
**修法**：递归摊平 `BaseExceptionGroup`（已交付 `_describe_error`），并把 `powermcp.registry`
已有的 `Tool.extra` + `install_hint()` 取出来作为 `hint`（已交付 `install_hint_for`）。

> ★ **已交付实现额外加了「门控」**（原方案未写，实测后补）：
> 只有"看起来属于依赖缺失"时才给安装提示 —— `_looks_dependency_related(error)` 命中关键词，
> 或 `_probe_importable(probe)` 判定该 linchpin 依赖确实不可导入。
> **超时/崩溃时提示 `pip install` 帮不上忙**，给了反而不满足"可执行"的要求。
> 另：`asyncio.timeout` 原生抛出的 `TimeoutError` **消息为空**，detail 会退化成
> `"TimeoutError:"` —— 已交付 `_is_timeout` / `_timeout_error` 补上 server 名、超时值与卡住的阶段。

#### 缺陷 B：未请求到的 server 从 `servers()` 里消失

首版的 `servers()` 是「有工具返回的 server」，于是**拉起失败的 server 不进任何求值器的视野** ——
契约 2 根本没检查到 opendss（首版恰好拉不起来），实际变成"静默跳过"。
**修法**：`ToolInventory.requested` 记录本次请求的全集，求值器一律迭代 `all_servers()`。

> ★ 契约 2 命中失败 server 时，已交付实现报 **`unknown / structural`**（"拿不到运行时工具清单，
> **无法比对**"），**不是 `violated`** —— 那些名字并非"不存在"，而是"无从核对"，
> 报 violated 只会制造新一批误报。该失败本身记在契约 8。
>
> ★ 连带：契约 8 的失败项 `reason` 改为 **`"structural" if failure.hint else "incident"`** ——
> 「知道怎么修」与「出了事故」是两种不同信号，混在一起会让事故标记失去意义。

- [x] **Step 1: 写失败的测试**

```python
from types import SimpleNamespace

import pytest

from powermcp_gateway.inventory import (
    ServerFailure,
    ToolInventory,
    ToolRecord,
    _describe_error,
    _is_timeout,
    _timeout_error,
    build_inventory,
    install_hint_for,
)


def _fake_sdk_tool(name: str = "run_power_flow", schema: dict | None = None):
    return SimpleNamespace(
        name=name,
        description="Run a power flow.",
        input_schema=schema or {"properties": {"net": {"type": "string"}}, "required": ["net"]},
        output_schema=None,
    )


def test_from_sdk_maps_snake_case_fields():
    rec = ToolRecord.from_sdk("pandapower", _fake_sdk_tool())
    assert rec.server == "pandapower"
    assert rec.name == "run_power_flow"
    assert rec.input_schema["required"] == ["net"]
    assert rec.output_schema is None


def test_from_sdk_tolerates_missing_description():
    tool = _fake_sdk_tool()
    tool.description = None
    assert ToolRecord.from_sdk("pypsa", tool).description is None


def test_inventory_names_and_by_name():
    a = ToolRecord.from_sdk("pandapower", _fake_sdk_tool("load_network"))
    b = ToolRecord.from_sdk("pypsa", _fake_sdk_tool("load_network"))
    c = ToolRecord.from_sdk("surge", _fake_sdk_tool("compute_lodf"))
    inv = ToolInventory(tools=(a, b, c), failures=())

    assert inv.names("pandapower") == ("load_network",)
    assert [r.server for r in inv.by_name("load_network")] == ["pandapower", "pypsa"]
    assert inv.by_name("nope") == ()


def test_inventory_is_hashable_and_serialisable():
    inv = ToolInventory(
        tools=(ToolRecord.from_sdk("surge", _fake_sdk_tool("compute_lodf")),),
        failures=(ServerFailure("genx", "RuntimeError: no julia"),),
    )
    assert inv.names("surge") == ("compute_lodf",)
    assert inv.failures[0].server == "genx"


@pytest.mark.integration
async def test_fetch_real_server():
    from powermcp_gateway.config import GatewayConfig
    from powermcp_gateway.inventory import fetch_server_tools

    cfg = GatewayConfig.discover()
    tools = await fetch_server_tools(cfg, "pandapower")
    assert len(tools) == 8
    assert "run_power_flow" in {t.name for t in tools}


# —— 失败原因的展开（契约 8 的 detail 必须可执行）——

def test_describe_error_unwraps_exception_group():
    """anyio 把子进程错误包在 ExceptionGroup 里，必须展开。

    真实案例：opendss 的契约 8 detail 曾只剩
    "ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)"，
    而真正可执行的 "pip install powermcp[opendss]" 被吞掉 ——
    这违反方案 §4.4「⚠️/❌ 必须给出可执行修复路径」。
    """
    inner = RuntimeError(
        "ANDES: required package 'andes' is not installed.\n"
        "  Install it with:  pip install powermcp[andes]"
    )
    group = ExceptionGroup("unhandled errors in a TaskGroup", [inner])

    text = _describe_error(group)

    assert "pip install powermcp[andes]" in text   # 可执行信息必须保住
    assert "RuntimeError" in text                  # 叶子异常类型必须保住
    assert "\n" not in text                        # 折叠为单行，便于徽章渲染


def test_describe_error_handles_plain_exception():
    assert _describe_error(ValueError("boom")) == "ValueError: boom"


def test_describe_error_handles_nested_groups():
    inner = ExceptionGroup("inner", [KeyError("k")])
    outer = ExceptionGroup("outer", [inner, TimeoutError("t")])
    text = _describe_error(outer)
    assert "KeyError" in text
    assert "TimeoutError" in text


def test_describe_error_deduplicates_repeated_leaves():
    dup = RuntimeError("same")
    group = ExceptionGroup("g", [dup, RuntimeError("same")])
    assert _describe_error(group).count("same") == 1


async def test_build_inventory_surfaces_grouped_reason(monkeypatch):
    """build_inventory 归集失败时，必须把 ExceptionGroup 展开后写入 failures。"""

    async def boom(cfg, server, timeout_s=None):
        raise ExceptionGroup(
            "unhandled errors in a TaskGroup",
            [RuntimeError("Install it with:  pip install powermcp[opendss]")],
        )

    monkeypatch.setattr("powermcp_gateway.inventory.fetch_server_tools", boom)

    inv = await build_inventory(cfg=None, servers=["opendss"])  # type: ignore[arg-type]

    assert len(inv.failures) == 1
    assert inv.failures[0].server == "opendss"
    assert "pip install powermcp[opendss]" in inv.failures[0].error


# —— 超时路径也必须可执行（asyncio.timeout 原生抛出的 TimeoutError 消息为空）——

def test_is_timeout_detects_plain_timeout():
    assert _is_timeout(TimeoutError()) is True


def test_is_timeout_detects_nested_timeout():
    """anyio 的清理异常可能把 TimeoutError 包在 ExceptionGroup 里。"""
    group = ExceptionGroup("g", [RuntimeError("x"), TimeoutError()])
    assert _is_timeout(group) is True


def test_is_timeout_rejects_other_errors():
    assert _is_timeout(RuntimeError("x")) is False
    assert _is_timeout(ExceptionGroup("g", [ValueError("v")])) is False


def test_timeout_error_carries_server_and_stage():
    """超时异常必须自带上文 —— 否则契约 8 的 detail 退化成 "TimeoutError:"。"""
    err = _timeout_error("opendss", 90.0)
    text = _describe_error(err)

    assert "opendss" in text                      # 哪个 server
    assert "90s" in text                          # 等了多久
    assert "握手" in text                          # 卡在哪一阶段
    assert text != "TimeoutError:"                # 不再是无信息的空消息


# —— ★ 完成标准 #5：可执行修复路径从 registry 取，且只在"依赖缺失"时才给 ——

def test_install_hint_for_known_server_with_extra():
    hint, probe = install_hint_for("andes")
    assert hint == "pip install powermcp[andes]"
    assert probe == "andes"


def test_install_hint_for_core_server_has_no_extra():
    hint, probe = install_hint_for("pandapower")
    assert hint == "pip install powermcp"      # 核心包，无 extra
    assert probe == "pandapower"


def test_install_hint_for_unknown_server_is_none():
    hint, probe = install_hint_for("no_such_server")
    assert hint is None
    assert probe is None


def test_all_servers_includes_failed_ones():
    """★ 缺陷 B：未拉起的 server 不得从求值器视野里消失。"""
    inv = ToolInventory(
        tools=(ToolRecord.from_sdk("pandapower", _fake_sdk_tool()),),
        failures=(ServerFailure("opendss", "LaunchError: ..."),),
        requested=("pandapower", "opendss"),
    )
    assert inv.servers() == ("pandapower",)
    assert inv.all_servers() == ("opendss", "pandapower")


def test_all_servers_falls_back_without_requested():
    """未显式传 requested 时，用 tools ∪ failures 兜底，失败 server 仍不丢。"""
    inv = ToolInventory(
        tools=(ToolRecord.from_sdk("surge", _fake_sdk_tool("compute_lodf")),),
        failures=(ServerFailure("genx", "boom"),),
    )
    assert inv.all_servers() == ("genx", "surge")


async def test_build_inventory_records_hint_on_dependency_failure(monkeypatch):
    """拉起失败且**看起来是依赖缺失**时，failure 必须带上可执行修复路径（方案 §4.4）。"""

    async def boom(cfg, server, timeout_s=None):
        raise ExceptionGroup("unhandled errors in a TaskGroup", [
            RuntimeError("ANDES: required package 'andes' is not installed. "
                         "Install it with: pip install powermcp[andes]"),
        ])

    monkeypatch.setattr("powermcp_gateway.inventory.fetch_server_tools", boom)

    result = await build_inventory(cfg=None, servers=["andes"])  # type: ignore[arg-type]

    assert result.requested == ("andes",)
    assert result.all_servers() == ("andes",)
    f = result.failures[0]
    assert "pip install powermcp[andes]" in f.error     # 摊平后的真实原因
    assert f.hint == "pip install powermcp[andes]"      # 结构化修复路径


async def test_timeout_failure_gets_no_install_hint(monkeypatch):
    """超时不是依赖缺失 —— 给安装提示是误导。

    方案 §4.4 要的是"**可执行**修复路径"，不是"随便给条命令"。
    """

    async def boom(cfg, server, timeout_s=None):
        raise TimeoutError("opendss 在 90s 内未完成 MCP 握手")

    monkeypatch.setattr("powermcp_gateway.inventory.fetch_server_tools", boom)

    result = await build_inventory(cfg=None, servers=["opendss"])  # type: ignore[arg-type]

    assert result.failures[0].hint is None
```

- [x] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_inventory.py -v -m "not integration"
```
Expected: FAIL —— `ModuleNotFoundError: No module named 'powermcp_gateway.inventory'`

- [x] **Step 3: 写 `gateway/src/powermcp_gateway/inventory.py`**

```python
"""MCP stdio 客户端与工具清单。

启动方式复用 tools/runtime_tool_census.py 已验证的写法：
    <venv python> -m powermcp.cli run <server>   （cwd = PowerMCP 仓库根）
"""

from __future__ import annotations

import asyncio
import importlib.util
from dataclasses import dataclass
from typing import Any, Iterable

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import GatewayConfig

# 依赖缺失类错误的关键词 —— 命中才给安装提示。
# 超时/崩溃时提示 `pip install` 是没有帮助的（方案 §4.4 要的是"可执行"路径）。
_DEP_PATTERNS = (
    "not installed",
    "install it with",
    "no module named",
    "importerror",
    "modulenotfounderror",
)


def _looks_dependency_related(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in _DEP_PATTERNS)


def _probe_importable(probe: str) -> bool:
    """该 linchpin 依赖在当前解释器里是否可导入。网关与 server 共用同一个 venv。"""
    try:
        return importlib.util.find_spec(probe) is not None
    except (ImportError, ValueError, ModuleNotFoundError):
        return False


def install_hint_for(server: str) -> tuple[str | None, str | None]:
    """从 `powermcp.registry` 取该 server 的可执行安装提示与 linchpin 依赖。

    返回 `(hint, probe)`；registry 不可用或不认识该 server 时返回 `(None, None)`。
    **不解析错误文本** —— 提示来源是 registry 的 `Tool.extra` + `install_hint()`，
    错误文本只用于**判断是否属于依赖缺失**（见 `_looks_dependency_related`）。
    """
    try:
        from powermcp import registry
    except Exception:  # noqa: BLE001 —— 网关可在没有 powermcp 的环境下被导入
        return None, None

    try:
        tool = registry.get_tool(server)
    except Exception:  # noqa: BLE001 —— 未知 server
        return None, None

    try:
        hint = registry.install_hint(tool.extra)
    except Exception:  # noqa: BLE001
        hint = None
    return hint, getattr(tool, "probe", None)


@dataclass(frozen=True)
class ToolRecord:
    server: str
    name: str
    description: str | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None

    @classmethod
    def from_sdk(cls, server: str, tool: Any) -> "ToolRecord":
        # ⚠️ SDK 用 snake_case：input_schema / output_schema
        return cls(
            server=server,
            name=tool.name,
            description=getattr(tool, "description", None),
            input_schema=dict(getattr(tool, "input_schema", None) or {}),
            output_schema=getattr(tool, "output_schema", None),
        )


@dataclass(frozen=True)
class ServerFailure:
    server: str
    error: str
    hint: str | None = None           # 可执行安装提示（来自 registry；仅依赖缺失类失败）
    probe_missing: str | None = None  # 缺失的 linchpin 依赖名


@dataclass(frozen=True)
class ToolInventory:
    tools: tuple[ToolRecord, ...]
    failures: tuple[ServerFailure, ...]
    requested: tuple[str, ...] = ()   # 本次请求的 server 全集（含拉起失败的）

    def names(self, server: str) -> tuple[str, ...]:
        return tuple(sorted(t.name for t in self.tools if t.server == server))

    def by_name(self, name: str) -> tuple[ToolRecord, ...]:
        return tuple(sorted((t for t in self.tools if t.name == name), key=lambda t: t.server))

    def servers(self) -> tuple[str, ...]:
        """**成功**返回工具清单的 server。"""
        return tuple(sorted({t.server for t in self.tools}))

    def all_servers(self) -> tuple[str, ...]:
        """本次请求的全部 server，**含拉起失败的**。

        ★ 求值器一律迭代本方法，不要用 `servers()` ——
        否则失败的 server 会从视野里消失，变成**静默跳过**。
        """
        if self.requested:
            return tuple(sorted(self.requested))
        return tuple(sorted({t.server for t in self.tools} | {f.server for f in self.failures}))


async def fetch_server_tools(
    cfg: GatewayConfig, server: str, timeout_s: float | None = None
) -> list[ToolRecord]:
    """拉起单个 server 并取回其工具清单。失败时抛异常，由 build_inventory 归集。"""
    params = StdioServerParameters(
        command=str(cfg.python),
        args=["-m", "powermcp.cli", "run", server],
        cwd=str(cfg.powermcp_root),
    )
    timeout = timeout_s if timeout_s is not None else cfg.server_timeout_s

    try:
        async with asyncio.timeout(timeout):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return [ToolRecord.from_sdk(server, t) for t in result.tools]
    except Exception as exc:  # noqa: BLE001 —— 见下：超时需补上下文后重抛，其余原样上抛
        if _is_timeout(exc):
            raise _timeout_error(server, timeout) from exc
        raise


def _describe_error(exc: BaseException) -> str:
    """把异常展开为**可执行的叶子原因**。

    anyio 会把子进程的 `LaunchError` 包在 `ExceptionGroup` 里。直接 `str(exc)`
    只能得到 `"unhandled errors in a TaskGroup (1 sub-exception)"` ——
    真正可执行的信息（如 `pip install powermcp[opendss]`）会被吞掉，
    使契约 8 的 detail 变得不可读。

    方案 §4.4 要求 ⚠️/❌ 必须给出**可执行修复路径**，故此处必须递归展开，
    并把空白折叠为单行（detail 会渲染成徽章/卡片，多行不便展示）。
    """
    leaves: list[str] = []

    def walk(e: BaseException) -> None:
        subs = getattr(e, "exceptions", None)  # ExceptionGroup / BaseExceptionGroup
        if subs:
            for sub in subs:
                walk(sub)
            return
        leaves.append(f"{type(e).__name__}: {e}")

    walk(exc)

    seen: list[str] = []
    for leaf in leaves:
        flat = " ".join(leaf.split())  # 折叠换行与连续空白
        if flat not in seen:
            seen.append(flat)
    return " | ".join(seen)[:400]


def _is_timeout(exc: BaseException) -> bool:
    """判断异常（含 ExceptionGroup 嵌套）是否由超时引起。"""
    if isinstance(exc, TimeoutError):
        return True
    for sub in getattr(exc, "exceptions", ()) or ():
        if _is_timeout(sub):
            return True
    return False


def _timeout_error(server: str, timeout: float) -> TimeoutError:
    """构造**带上下文**的超时异常。

    `asyncio.timeout` 原生抛出的 `TimeoutError` **消息为空** —— 契约 8 的 detail
    会退化成 `"TimeoutError:"`，既不说明是哪个 server、等了多久，也不说明卡在哪一步，
    同样违反方案 §4.4「⚠️/❌ 必须给出可执行修复路径」。
    """
    return TimeoutError(
        f"{server} 在 {timeout:g}s 内未完成 MCP 握手（initialize / list_tools 无响应）"
        f" —— 进程可能已启动但不响应，需单独排查该 server 的 stdio 管道"
    )


async def build_inventory(
    cfg: GatewayConfig,
    servers: Iterable[str],
    timeout_s: float | None = None,
) -> ToolInventory:
    """并发拉起多个 server；单个失败不影响其余，缺口记入 failures。

    失败时**必须保留可执行信息**：摊平 ExceptionGroup 取真实原因，
    并在**确属依赖缺失**时从 registry 附上安装提示（方案 §4.4 硬要求）。
    """
    names = list(servers)

    async def one(server: str) -> tuple[str, list[ToolRecord] | None, ServerFailure | None]:
        try:
            return server, await fetch_server_tools(cfg, server, timeout_s), None
        except Exception as exc:  # noqa: BLE001 —— 单 server 失败不应拖垮整体
            error = _describe_error(exc)
            hint, probe = install_hint_for(server)

            # 只在"看起来与依赖缺失有关"时才给安装提示，避免误导
            # （超时、崩溃时提示 `pip install` 帮不上忙）
            probe_missing = probe if (probe is not None and not _probe_importable(probe)) else None
            dependency_related = _looks_dependency_related(error) or probe_missing is not None

            return server, None, ServerFailure(
                server=server,
                error=error,
                hint=hint if dependency_related else None,
                probe_missing=probe_missing,
            )

    results = await asyncio.gather(*(one(s) for s in names))

    tools: list[ToolRecord] = []
    failures: list[ServerFailure] = []
    for server, recs, failure in results:
        if failure is not None:
            failures.append(failure)
        else:
            tools.extend(recs or [])

    return ToolInventory(
        tools=tuple(tools),
        failures=tuple(failures),
        requested=tuple(sorted(names)),
    )
```

- [x] **Step 4: 跑单元测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_inventory.py -v -m "not integration"
```
Expected: PASS（20 passed）

- [x] **Step 5: 跑集成测试（真实拉起 pandapower，约 30 秒）**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_inventory.py -v -m integration
```
Expected: PASS（1 passed）—— 实测 pandapower 返回 **8** 个工具。

- [x] **Step 6: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): MCP stdio 客户端与工具清单"
```

---

### Task 2: 契约状态模型与汇总

**Files:**
- Create: `gateway/src/powermcp_gateway/contracts/__init__.py`
- Create: `gateway/src/powermcp_gateway/contracts/model.py`
- Test: `gateway/tests/test_contract_model.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `KnownState = Literal["satisfied", "degraded", "violated"]`
  - `UnknownReason = Literal["structural", "incident"]`
  - `ContractState = Literal["satisfied", "degraded", "violated", "unknown"]`
  - `ContractFinding`：`contract: int` · `state: ContractState` · `reason: UnknownReason | None` · `subject: str` · `detail: str` · `evidence: dict`
    - `__post_init__` 强制：`state == "unknown"` 时 `reason` 必填，否则 `ValueError`
  - `ReportSummary`：`primary: str` · `structural_unknown: int` · `incident_unknown: int`
  - `summarize(findings) -> ReportSummary`
  - `CONTRACT_NAMES: dict[int, str]` —— 1–8 的中文名，与 UI 规范 `tokens.json#contractTypes` 一致

> 本任务是 **UI 规范 §4.3 双轨汇总的服务端实现**。两端的汇总语义必须逐字一致 —— 测试里用规范表格里的例子做断言。

- [x] **Step 1: 写失败的测试**

```python
import pytest

from powermcp_gateway.contracts.model import (
    CONTRACT_NAMES,
    ContractFinding,
    summarize,
)


def _f(contract: int, state: str, reason: str | None = None) -> ContractFinding:
    return ContractFinding(
        contract=contract, state=state, reason=reason,
        subject="test", detail="", evidence={},
    )


def test_unknown_requires_reason():
    with pytest.raises(ValueError, match="reason"):
        ContractFinding(contract=4, state="unknown", reason=None,
                        subject="x", detail="", evidence={})


def test_known_state_must_not_carry_reason():
    with pytest.raises(ValueError, match="reason"):
        ContractFinding(contract=3, state="degraded", reason="structural",
                        subject="x", detail="", evidence={})


def test_contract_names_cover_1_to_8():
    assert set(CONTRACT_NAMES) == set(range(1, 9))
    assert CONTRACT_NAMES[3] == "参数契约"
    assert CONTRACT_NAMES[5] == "命名空间契约"


# —— 以下四例逐字取自《UI 设计规范》§4.3 的双轨汇总表 ——

def test_structural_unknown_does_not_outrank_degraded():
    s = summarize([_f(7, "satisfied"), _f(4, "unknown", "structural"), _f(3, "degraded")])
    assert s.primary == "degraded"
    assert s.structural_unknown == 1
    assert s.incident_unknown == 0


def test_structural_unknown_alone_leaves_primary_satisfied():
    s = summarize([_f(7, "satisfied"), _f(1, "satisfied"), _f(4, "unknown", "structural")])
    assert s.primary == "satisfied"
    assert s.structural_unknown == 1


def test_incident_escalates_over_everything():
    s = summarize([_f(7, "satisfied"), _f(4, "unknown", "structural"), _f(3, "unknown", "incident")])
    assert s.primary == "incident"
    assert s.structural_unknown == 1
    assert s.incident_unknown == 1


def test_empty_is_unknown_not_satisfied():
    s = summarize([])
    assert s.primary == "unknown"
    assert s.structural_unknown == 0
    assert s.incident_unknown == 0


def test_all_structural_unknown_yields_unknown_primary():
    s = summarize([_f(4, "unknown", "structural"), _f(6, "unknown", "structural")])
    assert s.primary == "unknown"
    assert s.structural_unknown == 2


def test_violated_outranks_degraded():
    s = summarize([_f(3, "degraded"), _f(7, "violated")])
    assert s.primary == "violated"
```

- [x] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_model.py -v
```
Expected: FAIL —— `ModuleNotFoundError: No module named 'powermcp_gateway.contracts'`

- [x] **Step 3: 写 `gateway/src/powermcp_gateway/contracts/model.py`**

```python
"""契约状态模型与汇总。

取值与汇总规则必须与《PowerMCP UI 设计规范》v1.2 §3.8 / §4.3 逐字一致：
前端与网关对"同一份契约数据"的汇总结论不能出现两个版本。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

KnownState = Literal["satisfied", "degraded", "violated"]
UnknownReason = Literal["structural", "incident"]
ContractState = Literal["satisfied", "degraded", "violated", "unknown"]

# 1–8，与方案 §2.2 及 tokens.json#contractTypes 一致
CONTRACT_NAMES: dict[int, str] = {
    1: "API 版本契约",
    2: "文档-实现一致性",
    3: "参数契约",
    4: "状态映射契约",
    5: "命名空间契约",
    6: "标识符契约",
    7: "量纲契约",
    8: "运行时依赖契约",
}

# 已知状态的严重度。unknown 不在此表 —— 它走双轨，不参与主徽标竞争
_KNOWN_SEVERITY: dict[KnownState, int] = {"satisfied": 0, "degraded": 1, "violated": 2}
_UNKNOWN_REASONS: frozenset[str] = frozenset({"structural", "incident"})


@dataclass(frozen=True)
class ContractFinding:
    contract: int
    state: ContractState
    reason: UnknownReason | None
    subject: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.contract not in CONTRACT_NAMES:
            raise ValueError(f"契约编号必须是 1–8，收到 {self.contract}")
        if self.state not in (*_KNOWN_SEVERITY, "unknown"):
            raise ValueError(f"未知的状态取值：{self.state!r}")
        if self.state == "unknown" and self.reason not in _UNKNOWN_REASONS:
            raise ValueError(
                f"state='unknown' 时必须给出 reason（structural/incident），收到 {self.reason!r}"
            )
        if self.state != "unknown" and self.reason is not None:
            raise ValueError(
                f"state={self.state!r} 不得携带 reason，收到 {self.reason!r}"
            )


@dataclass(frozen=True)
class ReportSummary:
    primary: KnownState | Literal["unknown", "incident"]
    structural_unknown: int
    incident_unknown: int


def summarize(findings: Iterable[ContractFinding]) -> ReportSummary:
    """双轨汇总 —— 与 UI 规范 §4.3 同规则。

    primary 的确定顺序：
      1. 有 incident 未知  → 'incident'          （整体不可信，必须喧宾夺主）
      2. 否则取已知项的最差 → violated > degraded > satisfied
      3. 无任何已知项      → 'unknown'           （绝不取 satisfied）
    structural 未知只计数，不参与 primary 竞争。
    """
    items = list(findings)
    structural = sum(1 for f in items if f.state == "unknown" and f.reason == "structural")
    incident = sum(1 for f in items if f.state == "unknown" and f.reason == "incident")

    if incident:
        return ReportSummary("incident", structural, incident)

    known = [f.state for f in items if f.state != "unknown"]
    if not known:
        return ReportSummary("unknown", structural, incident)

    worst = max(known, key=lambda s: _KNOWN_SEVERITY[s])  # type: ignore[index]
    return ReportSummary(worst, structural, incident)  # type: ignore[arg-type]
```

- [x] **Step 4: 写 `gateway/src/powermcp_gateway/contracts/__init__.py`**

```python
from .model import (
    CONTRACT_NAMES,
    ContractFinding,
    ContractState,
    KnownState,
    ReportSummary,
    UnknownReason,
    summarize,
)

__all__ = [
    "CONTRACT_NAMES",
    "ContractFinding",
    "ContractState",
    "KnownState",
    "ReportSummary",
    "UnknownReason",
    "summarize",
]
```

- [x] **Step 5: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_model.py -v
```
Expected: PASS（9 passed）

- [x] **Step 6: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): 契约状态模型与双轨汇总"
```

---

### Task 3: 求值器协议、注册表与登记表

**Files:**
- Create: `gateway/src/powermcp_gateway/contracts/registry.py`
- Test: `gateway/tests/test_contract_registry.py`

**Interfaces:**
- Consumes: `ContractFinding`（Task 2）· `ToolInventory`（Task 1）· `GatewayConfig`（Task 0）
- Produces:
  - `class ContractEvaluator(Protocol)`：`contract: int` · `name: str` · `timeframe: Literal["T0"]` · `def evaluate(self, inv, cfg) -> list[ContractFinding]`
  - `EvaluatorRegistry`：`register(ev)`（编号冲突时抛 `ValueError`）· `all() -> tuple[ContractEvaluator, ...]` · `get(contract: int)`
  - `REGISTRY: EvaluatorRegistry` —— 模块级单例，后续 Task 逐个注册

- [x] **Step 1: 写失败的测试**

```python
import pytest

from powermcp_gateway.contracts.registry import EvaluatorRegistry


class _Stub:
    # 契约编号受 Global Constraints 约束为 1–8；此处用 8 作为"合法编号"的桩
    contract = 8
    name = "stub"
    timeframe = "T0"

    def evaluate(self, inv, cfg):
        return []


def test_register_and_get():
    reg = EvaluatorRegistry()
    reg.register(_Stub())
    assert reg.get(8).name == "stub"
    assert len(reg.all()) == 1


def test_duplicate_contract_number_rejected():
    reg = EvaluatorRegistry()
    reg.register(_Stub())
    with pytest.raises(ValueError, match="已注册"):
        reg.register(_Stub())


def test_invalid_contract_number_rejected():
    class Bad(_Stub):
        contract = 99

    reg = EvaluatorRegistry()
    with pytest.raises(ValueError, match="1–8"):
        reg.register(Bad())


def test_get_unknown_raises():
    with pytest.raises(KeyError):
        EvaluatorRegistry().get(5)
```

- [x] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_registry.py -v
```
Expected: FAIL —— `ModuleNotFoundError`

- [x] **Step 3: 写 `gateway/src/powermcp_gateway/contracts/registry.py`**

```python
"""契约求值器的协议与注册表。"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from ..config import GatewayConfig
from ..inventory import ToolInventory
from .model import CONTRACT_NAMES, ContractFinding


@runtime_checkable
class ContractEvaluator(Protocol):
    """一个契约的求值器。求值器必须是纯函数式：给定同样的输入，给出同样的输出。"""

    contract: int
    name: str
    timeframe: Literal["T0"]

    def evaluate(self, inv: ToolInventory, cfg: GatewayConfig) -> list[ContractFinding]:
        ...


class EvaluatorRegistry:
    def __init__(self) -> None:
        self._by_contract: dict[int, ContractEvaluator] = {}

    def register(self, evaluator: ContractEvaluator) -> None:
        n = evaluator.contract
        if n not in CONTRACT_NAMES:
            raise ValueError(f"契约编号必须是 1–8，收到 {n}")
        if n in self._by_contract:
            raise ValueError(
                f"契约 {n} 已注册（{self._by_contract[n].name}），不能重复注册 {evaluator.name}"
            )
        self._by_contract[n] = evaluator

    def all(self) -> tuple[ContractEvaluator, ...]:
        return tuple(self._by_contract[k] for k in sorted(self._by_contract))

    def get(self, contract: int) -> ContractEvaluator:
        return self._by_contract[contract]


REGISTRY = EvaluatorRegistry()
```

- [x] **Step 4: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_registry.py -v
```
Expected: PASS（4 passed）

- [x] **Step 5: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): 契约求值器协议与注册表"
```

---

### Task 4: 契约 5 —— 命名空间

**Files:**
- Create: `gateway/src/powermcp_gateway/contracts/namespacing.py`
- Test: `gateway/tests/test_contract_namespacing.py`

**Interfaces:**
- Consumes: `ToolInventory` · `ContractFinding` · `EvaluatorRegistry`
- Produces: `NamespacingEvaluator`（`contract = 5`）· `schema_fingerprint(schema: dict) -> str`

**规则**（方案 §2.2：契约 5 的输出只有 `✅`/`⚠️`）：
- 无任何跨 server 重名 → `satisfied`
- 有重名 → `degraded`，**每条重名各出一条 finding**
- 指纹相同（`same`）与不同（`differ`）都要报，**但都在 detail 里写明** —— 后者更危险，因为同名不同义

**已知证据（必须被这条规则抓到）**：`load_network` 同时存在于 pandapower / pypsa / surge。

- [x] **Step 1: 写失败的测试**

```python
from types import SimpleNamespace

from powermcp_gateway.contracts.namespacing import NamespacingEvaluator, schema_fingerprint
from powermcp_gateway.inventory import ToolInventory, ToolRecord


def _rec(server: str, name: str, schema: dict | None = None) -> ToolRecord:
    return ToolRecord.from_sdk(
        server,
        SimpleNamespace(name=name, description=None,
                        input_schema=schema or {"properties": {}, "required": []},
                        output_schema=None),
    )


def _inv(*recs: ToolRecord) -> ToolInventory:
    return ToolInventory(tools=tuple(recs), failures=())


def test_fingerprint_is_order_insensitive():
    a = {"properties": {"x": {"type": "string"}}, "required": ["x"]}
    b = {"required": ["x"], "properties": {"x": {"type": "string"}}}
    assert schema_fingerprint(a) == schema_fingerprint(b)


def test_fingerprint_differs_on_different_types():
    a = {"properties": {"x": {"type": "string"}}}
    b = {"properties": {"x": {"type": "integer"}}}
    assert schema_fingerprint(a) != schema_fingerprint(b)


def test_no_collision_is_satisfied():
    ev = NamespacingEvaluator()
    inv = _inv(_rec("pandapower", "run_power_flow"), _rec("surge", "compute_lodf"))
    findings = ev.evaluate(inv, cfg=None)  # type: ignore[arg-type]
    assert len(findings) == 1
    assert findings[0].state == "satisfied"
    assert findings[0].contract == 5


def test_collision_is_degraded_with_both_servers():
    ev = NamespacingEvaluator()
    inv = _inv(
        _rec("pandapower", "load_network"),
        _rec("pypsa", "load_network"),
        _rec("surge", "compute_lodf"),
    )
    findings = ev.evaluate(inv, cfg=None)  # type: ignore[arg-type]
    assert len(findings) == 1
    f = findings[0]
    assert f.state == "degraded"
    assert f.reason is None
    assert f.evidence["tool"] == "load_network"
    assert f.evidence["servers"] == ["pandapower", "pypsa"]
    assert f.evidence["schemas_match"] is True


def test_same_name_different_schema_is_flagged_as_differ():
    ev = NamespacingEvaluator()
    inv = _inv(
        _rec("pandapower", "load_network", {"properties": {"path": {"type": "string"}}}),
        _rec("pypsa", "load_network", {"properties": {"name": {"type": "string"}}}),
    )
    f = ev.evaluate(inv, cfg=None)[0]  # type: ignore[arg-type]
    assert f.state == "degraded"
    assert f.evidence["schemas_match"] is False
    assert "不同" in f.detail


def test_real_collision_load_network_spans_three_servers():
    """已知实测重名：load_network 在 pandapower / pypsa / surge 三者中同名。"""
    ev = NamespacingEvaluator()
    inv = _inv(
        _rec("pandapower", "load_network"), _rec("pypsa", "load_network"),
        _rec("surge", "load_network"), _rec("powerio", "parse"),
    )
    f = ev.evaluate(inv, cfg=None)[0]  # type: ignore[arg-type]
    assert f.evidence["servers"] == ["pandapower", "pypsa", "surge"]
```

- [x] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_namespacing.py -v
```
Expected: FAIL —— `ModuleNotFoundError`

- [x] **Step 3: 写 `gateway/src/powermcp_gateway/contracts/namespacing.py`**

```python
"""契约 5：命名空间。

跨 server 的工具重名。PowerMCP 有约 250 个工具分布在 9 个 server 上，
重名在语义上可能相同也可能完全不同 —— 后者会让"调用了哪个"变得不可判定。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..config import GatewayConfig
from ..inventory import ToolInventory
from .model import ContractFinding


def schema_fingerprint(schema: dict[str, Any]) -> str:
    """对 input_schema 做稳定哈希 —— 键序无关，但类型差异必须体现。"""

    def normalise(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: normalise(v) for k, v in sorted(node.items())}
        if isinstance(node, list):
            return [normalise(v) for v in node]
        return node

    blob = json.dumps(normalise(schema), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class NamespacingEvaluator:
    contract = 5
    name = "命名空间契约"
    timeframe = "T0"

    def evaluate(self, inv: ToolInventory, cfg: GatewayConfig) -> list[ContractFinding]:
        findings: list[ContractFinding] = []

        for name in sorted({t.name for t in inv.tools}):
            hits = inv.by_name(name)
            if len(hits) < 2:
                continue

            servers = sorted(t.server for t in hits)
            prints = {schema_fingerprint(t.input_schema) for t in hits}
            same = len(prints) == 1

            findings.append(
                ContractFinding(
                    contract=5,
                    state="degraded",
                    reason=None,
                    subject=name,
                    detail=(
                        f"工具 `{name}` 在 {len(servers)} 个 server 中同名："
                        f"{'、'.join(servers)}；"
                        + ("入参 schema 一致。" if same else "**入参 schema 不同** —— 同名不同义，易误调用。")
                    ),
                    evidence={
                        "tool": name,
                        "servers": servers,
                        "schemas_match": same,
                        "fingerprints": {t.server: schema_fingerprint(t.input_schema) for t in hits},
                    },
                )
            )

        if not findings:
            findings.append(
                ContractFinding(
                    contract=5,
                    state="satisfied",
                    reason=None,
                    subject="*",
                    detail=f"已挂载 {len(inv.servers())} 个 server，无跨 server 工具重名。",
                    evidence={"servers": list(inv.servers()), "tool_count": len(inv.tools)},
                )
            )
        return findings
```

- [x] **Step 4: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_namespacing.py -v
```
Expected: PASS（6 passed）

- [x] **Step 5: 在 `contracts/__init__.py` 末尾注册**

在 `gateway/src/powermcp_gateway/contracts/__init__.py` 追加：

```python
from .namespacing import NamespacingEvaluator
from .registry import REGISTRY

REGISTRY.register(NamespacingEvaluator())

__all__ += ["REGISTRY", "NamespacingEvaluator"]
```

- [x] **Step 6: 跑全部单元测试确认无回归**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest -v -m "not integration"
```
Expected: PASS（全部）

- [x] **Step 7: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): 契约 5 命名空间求值器"
```

---

### Task 5: 契约 2 —— 文档-实现一致性

**Files:**
- Create: `gateway/src/powermcp_gateway/contracts/doc_impl.py`
- Test: `gateway/tests/test_contract_doc_impl.py`

**Interfaces:**
- Consumes: `GatewayConfig.powermcp_root`（定位 `<ServerDir>/README.md`）· `ToolInventory.all_servers()` · `ToolInventory.schema_property_names(server)`
- Produces:
  - `DocImplEvaluator`（`contract = 2`）
  - `SERVER_DOC_DIRS: dict[str, str]`
  - `extract_declared_tool_names(markdown: str) -> set[str]`
    （结构化提取 v2：只认工具名位置，无 kwargs、无 `split_sections` —— 见执行记录偏差表）
  - `TOOL_SECTIONS: tuple[str, ...]` —— 实测自 8 个 README 的清单区块标题

**规则**（方案 §2.2：契约 2 输出 `✅`/`⚠️`/`❌`）：
- 文档中声明、但 `list_tools` 里不存在 → **`violated`**
- `list_tools` 里有、但文档没提 → `degraded`
- 二者皆无 → `satisfied`
- `README.md` 缺失 → `unknown / structural`（**不是** satisfied —— 没检查 ≠ 没问题）
- **server 未拉起** → `unknown / structural`，detail 指向契约 8（**不得静默跳过**）

### ★ 工具名识别规则的修正（首版误报率极高）

首版规则是「反引号包裹 + 含下划线的 snake_case」，实测在 8 个引擎上**误报 73 条**
（pypsa 36 · opendss 16 · andes 13 · hope 3 · genx 3 · surge 2），
全部是 README 里的 **API 方法名 / 参数名 / 响应字段名**，而不是工具名。
更糟的是**真证据漏检** —— opendss 因拉不起来而未进 inventory，契约 2 根本没检查到它。
即首版是「**误报满屏 + 真证据漏检**」。

#### 已交付口径（v2）：结构化提取

只在**工具清单区块**内、只认**工具名位置**的标识符。实测自 8 个引擎 README，共 5 种写法：

| 引擎 | 写法 |
|---|---|
| pandapower · ANDES · Egret | `- **name(params)**: 说明` |
| surge | `` - `name(params)` — 说明 `` |
| PyPSA · GenX | `` - [x] `name` - 说明 `` |
| OpenDSS | 表格首列 `\| **name** \| 用途 \|` |
| HOPE | `## Tool split` 下的 `` - `name` `` |

**规则（三者取并集）**：
1. **列 0 列表项**的第一个粗体/反引号标识符（`- ` / `- [x] `）
2. **表格行**的第一个粗体/反引号标识符
3. **续行**：缩进且**直接以**粗体/反引号标识符开头的行（surge 的多工具枚举）

**两道排除**：
- **必须含下划线** —— 排除 `summary` / `sparse` / `full` 这类参数取值
- **缩进子项（以 `- ` 开头）不算** —— 排除 ANDES 式的参数/字段说明

标题别名 `Available Tools` / `Tools` / `Tool split`（大小写不敏感，1–2 级标题）；遇同级标题终止。

#### 与「数据驱动章节作用域 + schema 属性名排除」方案的实测对比

曾评估过另一套规则（② 工具章节 = 正文含至少一个真实工具名的章节；③ 排除 schema properties 中的名字）。
按该口径**原样**实测，结果明显更差：

| 引擎 | 实际 | v2 声明 / 误报 | 另一方案 声明 / 误报 / 漏报 |
|---|---|---|---|
| pandapower | 8 | 8 / 0 | **0 / 0 / 8** |
| pypsa | 17 | 17 / 0 | 17 / 0 / 0 |
| surge | 44 | 38 / 0 | 14 / 1 / **31** |
| andes | 6 | 6 / 0 | 14 / **11** / 3 |
| egret | 5 | 5 / 0 | **0 / 0 / 5** |
| hope | 20 | 20 / 0 | 21 / 1 / 0 |
| genx | 7 | 4 / 0 | 7 / 0 / 0 |
| **合计** | | **0** | **13 / 47** |

**两条已证据化的原因**：
1. **只认反引号、不认粗体** —— pandapower / ANDES / Egret 用粗体写工具名，候选为空 →
   声明 0 → 全部误报为"未声明"。
2. **schema 属性名排除覆盖不到"文档描述的返回字段名"** —— 实测 andes 的
   `damping_ratio_pct` / `dynamic_models_loaded` / `frequency_hz` **不在** schema properties
   （andes 全部 properties 仅 16 个，`dyr_path` / `file_path` 在、上述不在）→ 清不掉。
   v2 靠「缩进子项不算」这条结构判据把它们全挡住。

> ⚠️ **v2 仍是启发式，不是解析器**。已知残余局限：
> - **行内提及的 helper 提取不到** —— GenX 的 `` `plot_capacity` `` 后跟
>   "(with helpers `check_capacity_setting` and `summarize_capacity`)"，后两个被判"未声明"
>   （表现为 `degraded` 而非 `violated`，危害有限）
> - README 若新增第 6 种写法，需同步扩展
>
> **不声称完全消除误报** —— 但每条 finding 都带 `evidence`，可下钻核对（P4）。


- [x] **Step 1: 写失败的测试**

```python
from types import SimpleNamespace

import pytest

from powermcp_gateway.contracts.doc_impl import (
    DocImplEvaluator,
    extract_declared_tool_names,
)
from powermcp_gateway.inventory import ToolInventory, ToolRecord


def _rec(server: str, name: str) -> ToolRecord:
    return ToolRecord.from_sdk(
        server, SimpleNamespace(name=name, description=None, input_schema={}, output_schema=None)
    )


# —— 提取口径：实测自 8 个引擎 README 的 5 种写法（见 doc_impl 模块 docstring）——

def test_extract_from_bullet_list_with_bold():
    """pandapower / ANDES / Egret 的写法。"""
    md = """
## Available Tools

- **run_power_flow(algorithm, tolerance_mva)**: Run power flow analysis.
- **load_network(file_path: str)**: Load a network from a `.json` file.
"""
    assert extract_declared_tool_names(md) == {"run_power_flow", "load_network"}


def test_extract_from_backtick_bullets_and_checkboxes():
    """surge 用反引号；PyPSA / GenX 用 `- [x]` 复选框。"""
    md = """
## Tools

- `create_empty_network(name?, base_mva?)`.
- [x] `get_network_info` - Get basic network statistics.
"""
    assert extract_declared_tool_names(md) == {"create_empty_network", "get_network_info"}


def test_extract_from_table_first_column():
    """OpenDSS 的写法：工具名在表格首列的粗体中。"""
    md = """
## Available Tools

| Tool | Purpose |
|------|---------|
| **compile_opendss_file** | compile a master DSS file |
| **clear_all_opendss_memory** | `ClearAll`; resets state |
"""
    assert extract_declared_tool_names(md) == {
        "compile_opendss_file", "clear_all_opendss_memory"}


def test_extract_accepts_indented_continuation_lines():
    """surge 的写法：一个列表项内换行枚举多个工具名（续行直接以反引号开头）。"""
    md = """
## Tools

- `create_empty_network(name?, base_mva?)`.
- `add_bus(number, bus_type)`,
  `add_generator(bus, p_mw)`,
  `add_line(from_bus, to_bus)`.
"""
    assert extract_declared_tool_names(md) == {
        "create_empty_network", "add_bus", "add_generator", "add_line"}


def test_extract_ignores_nested_sub_bullets():
    """ANDES 的写法：缩进子项是参数/字段说明，不是工具。"""
    md = """
## Available Tools

- **run_power_flow(file_path: str)**: Run power flow analysis.
  - `dyr_path`: optional dynamic-model file.
    - `n_dynamic_generators`: how many the loaded system carries.
"""
    assert extract_declared_tool_names(md) == {"run_power_flow"}


def test_extract_ignores_parameter_enumeration_values():
    """surge 的写法：`format` 的取值 `summary`/`sparse`/`full` 是参数取值，不是工具。

    这是旧口径（全文反引号 snake_case）误报的主因之一。
    """
    md = """
## Tools

- `compute_ptdf(monitored_branches?, format)`.

`format` controls serialization:

- `summary` (default): shape, sparsity.
- `sparse`: CSR for 2-D.
- `full`: dense nested list.
"""
    assert extract_declared_tool_names(md) == {"compute_ptdf"}


def test_extract_requires_underscore():
    """工具名一律含下划线；无下划线的标识符（包名、取值）不算。"""
    md = """
## Tools

- `pandapower` — the package.
- `run_power_flow(...)`.
"""
    assert extract_declared_tool_names(md) == {"run_power_flow"}


def test_extract_ignores_text_outside_tool_sections():
    md = """
# Server

## Requirements

- `some_python_package` must be installed.

## Available Tools

- `the_tool(...)`.
"""
    assert extract_declared_tool_names(md) == {"the_tool"}


def test_extract_stops_at_next_same_level_heading():
    md = """
## Available Tools

- `the_tool(...)`.

## Resources

- `not_a_tool(...)`.
"""
    assert extract_declared_tool_names(md) == {"the_tool"}


def test_extract_accepts_tool_split_section():
    """HOPE 用 `## Tool split` 作为工具清单标题。"""
    md = """
## Tool split

Claude/local full-access server:

- `hope_warmup`
- `hope_job_status`
"""
    assert extract_declared_tool_names(md) == {"hope_warmup", "hope_job_status"}


# —— DocImplEvaluator 的判定规则（不受口径改动影响）——

def test_declared_but_missing_is_violated(tmp_path):
    server_dir = tmp_path / "FakeServer"
    server_dir.mkdir()
    (server_dir / "README.md").write_text(
        "## Available Tools\n\n- `does_not_exist(...)`.\n- `also_missing(...)`.\n",
        encoding="utf-8",
    )

    class Cfg:
        powermcp_root = tmp_path

    ev = DocImplEvaluator(doc_dirs={"fake": "FakeServer"})
    findings = ev.evaluate(
        ToolInventory(tools=(_rec("fake", "real_tool"),), failures=()), cfg=Cfg()  # type: ignore[arg-type]
    )
    states = {f.state for f in findings}
    assert "violated" in states
    viol = [f for f in findings if f.state == "violated"][0]
    assert set(viol.evidence["declared_missing"]) == {"does_not_exist", "also_missing"}


def test_undocumented_is_degraded(tmp_path):
    server_dir = tmp_path / "FakeServer"
    server_dir.mkdir()
    (server_dir / "README.md").write_text(
        "## Available Tools\n\n- `documented_tool(...)`.\n", encoding="utf-8"
    )

    class Cfg:
        powermcp_root = tmp_path

    ev = DocImplEvaluator(doc_dirs={"fake": "FakeServer"})
    findings = ev.evaluate(
        ToolInventory(tools=(_rec("fake", "documented_tool"), _rec("fake", "secret_tool")), failures=()),
        cfg=Cfg(),  # type: ignore[arg-type]
    )
    deg = [f for f in findings if f.state == "degraded"]
    assert deg and deg[0].evidence["undocumented"] == ["secret_tool"]


def test_missing_readme_is_structural_unknown(tmp_path):
    class Cfg:
        powermcp_root = tmp_path

    ev = DocImplEvaluator(doc_dirs={"fake": "NoSuchDir"})
    findings = ev.evaluate(
        ToolInventory(tools=(_rec("fake", "x_tool"),), failures=()), cfg=Cfg()  # type: ignore[arg-type]
    )
    assert len(findings) == 1
    assert findings[0].state == "unknown"
    assert findings[0].reason == "structural"


def test_all_consistent_is_satisfied(tmp_path):
    server_dir = tmp_path / "FakeServer"
    server_dir.mkdir()
    (server_dir / "README.md").write_text(
        "## Available Tools\n\n- `the_tool(...)`.\n", encoding="utf-8"
    )

    class Cfg:
        powermcp_root = tmp_path

    ev = DocImplEvaluator(doc_dirs={"fake": "FakeServer"})
    findings = ev.evaluate(
        ToolInventory(tools=(_rec("fake", "the_tool"),), failures=()), cfg=Cfg()  # type: ignore[arg-type]
    )
    assert findings[0].state == "satisfied"


def test_section_without_tool_names_is_not_satisfied(tmp_path):
    """README 有工具清单标题但一个工具都没列 → 全部未声明，判 degraded（不是 satisfied）。"""
    server_dir = tmp_path / "FakeServer"
    server_dir.mkdir()
    (server_dir / "README.md").write_text("## Available Tools\n\n(待补)\n", encoding="utf-8")

    class Cfg:
        powermcp_root = tmp_path

    ev = DocImplEvaluator(doc_dirs={"fake": "FakeServer"})
    findings = ev.evaluate(
        ToolInventory(tools=(_rec("fake", "a_tool"),), failures=()), cfg=Cfg()  # type: ignore[arg-type]
    )
    assert findings[0].state == "degraded"
    assert findings[0].evidence["undocumented"] == ["a_tool"]
```

- [x] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_doc_impl.py -v
```
Expected: FAIL —— `ModuleNotFoundError`

- [x] **Step 3: 写 `gateway/src/powermcp_gateway/contracts/doc_impl.py`**

```python
r"""契约 2：文档-实现一致性。

比对 server 的 README.md 所声明的工具面 vs `list_tools` 实际返回。

## 提取口径 v2（2026-09-24 重写）

v1 的口径是"全文任意被反引号包裹的 snake_case 标识符"。实测在 8 个引擎上
产生**大量误报** —— pypsa 36 条、andes 13 条、genx 3 条、hope 3 条、surge 2 条，
全部是 README 里的 **API 方法名 / 参数名 / 响应字段名**，而不是工具名。
（例：pypsa 的 `add_constraint`、andes 的 `dyr_path`、surge 的 `summary`。）
更糟的是：真正的已知证据 opendss 因拉不起来而未进入 inventory，
契约 2 根本没检查到它 —— 即 v1 是"误报满屏、真证据漏检"。

v2 改为**结构化提取**：只在"工具清单区块"内、只认"工具名位置"的标识符。
实测自 8 个引擎的 README，共 5 种写法，全部覆盖：

| 引擎 | 写法 |
|---|---|
| pandapower · ANDES · Egret | ``- **name(params)**: 说明`` |
| surge | ``- `name(params)` — 说明`` |
| PyPSA · GenX | ``- [x] `name` - 说明`` |
| OpenDSS | ``\| **name** \| 用途 \|``（表格首列） |
| HOPE | `## Tool split` 下的 ``- `name` `` |

提取规则（三者取并集）：
1. **列 0 列表项**的第一个粗体/反引号标识符（`- ` 或 `- [x] `）
2. **表格行**的第一个粗体/反引号标识符
3. **续行**：缩进且**直接以**粗体/反引号标识符开头的行（surge 的多工具枚举）

并施加两道排除：
- **必须含下划线** —— 工具名一律带 `_`；`summary` / `sparse` / `full` 这类参数取值被排除
- **缩进子项（以 `- ` 开头）不算** —— 那是 ANDES 式的参数/字段说明

## 已知局限（如实记录，不掩盖）

- **行内提及的 helper 提取不到**：GenX 的 `` `plot_capacity` `` 后跟
  "(with helpers `check_capacity_setting` and `summarize_capacity`)"，
  后两个会被判为"未声明"。当前仅 genx 命中，表现为 `degraded` 而非 `violated`。
- **判定为 `violated` 需要"声明的工具名在运行时不存在"**。v2 在 8 个引擎上
  **未产生任何 `violated`**（v1 曾产生 5 条，经逐条核实全部为误报）。
- 本口径是**启发式**，不是解析器。README 写法若再新增第 6 种，需同步扩展。
"""

from __future__ import annotations

import re
from pathlib import Path

from ..config import GatewayConfig
from ..inventory import ToolInventory
from .model import ContractFinding

# server id -> PowerMCP 仓库内的目录名（大小写敏感，实测自仓库结构）
SERVER_DOC_DIRS: dict[str, str] = {
    "pandapower": "pandapower",
    "pypsa": "PyPSA",
    "surge": "surge",
    "andes": "ANDES",
    "egret": "Egret",
    "opendss": "OpenDSS",
    "hope": "HOPE",
    "genx": "GenX",
}

# 实测自 8 个引擎 README 的工具清单标题（大小写不敏感）
TOOL_SECTIONS: tuple[str, ...] = ("Available Tools", "Tools", "Tool split")

_SECTION = re.compile(
    r"^#{1,2}\s+(?:" + "|".join(re.escape(s) for s in TOOL_SECTIONS) + r")\s*$",
    re.IGNORECASE,
)
_ANY_H12 = re.compile(r"^#{1,2}\s+")
_LIST_ITEM = re.compile(r"^-\s+(?:\[[ xX]\]\s+)?(?:\*\*|`)([A-Za-z_][A-Za-z0-9_]*)")
_TABLE_ROW = re.compile(r"^\|\s*(?:\*\*|`)([A-Za-z_][A-Za-z0-9_]*)")
_CONTINUATION = re.compile(r"^\s+(?:\*\*|`)([A-Za-z_][A-Za-z0-9_]*)")


def extract_declared_tool_names(markdown: str) -> set[str]:
    """从 README 的工具清单区块提取「声明的工具名」。

    只在清单区块内、只认工具名位置（列 0 列表项 / 表格首列 / 续行），
    并要求含下划线 —— 见模块 docstring 的口径说明与已知局限。
    """
    names: set[str] = set()
    inside = False

    for line in markdown.splitlines():
        if _SECTION.match(line):
            inside = True
            continue
        if inside and _ANY_H12.match(line):
            break  # 下一个同级或更高级标题 → 清单区块结束
        if not inside:
            continue

        m = _LIST_ITEM.match(line) or _TABLE_ROW.match(line) or _CONTINUATION.match(line)
        if m is None:
            continue

        name = m.group(1)
        if "_" in name:  # 工具名一律含下划线；参数取值/包名被排除
            names.add(name)

    return names


class DocImplEvaluator:
    contract = 2
    name = "文档-实现一致性"
    timeframe = "T0"

    def __init__(self, doc_dirs: dict[str, str] | None = None) -> None:
        self._doc_dirs = dict(doc_dirs) if doc_dirs is not None else dict(SERVER_DOC_DIRS)

    def evaluate(self, inv: ToolInventory, cfg: GatewayConfig) -> list[ContractFinding]:
        findings: list[ContractFinding] = []
        mounted = set(inv.servers())

        # ★ 迭代 all_servers() 而非 servers()：拉起失败的 server 也要被检查到。
        #   首版用 servers() 时，失败的 server 从视野里消失 —— 契约 2 变成"静默跳过"，
        #   看起来"没问题"，实际是"没检查"。
        for server in inv.all_servers():
            dirname = self._doc_dirs.get(server)
            readme = (cfg.powermcp_root / dirname / "README.md") if dirname else None

            if readme is None or not readme.is_file():
                findings.append(
                    ContractFinding(
                        contract=2, state="unknown", reason="structural", subject=server,
                        detail=f"未找到 {server} 的 README.md，无法比对文档与实现。",
                        evidence={"server": server, "readme": str(readme) if readme else None},
                    )
                )
                continue

            if server not in mounted:
                # 拿不到运行时工具清单 → **无法比对**。
                # 报 violated 会是误报（README 里的名字并非"不存在"，而是"无从核对"）。
                findings.append(
                    ContractFinding(
                        contract=2, state="unknown", reason="structural", subject=server,
                        detail=(
                            f"`{server}` 未能拉起，拿不到运行时工具清单，**无法比对**文档与实现。"
                            f"（该失败本身记在**契约 8**）"
                        ),
                        evidence={"server": server, "readme": str(readme), "mounted": False},
                    )
                )
                continue

            actual = set(inv.names(server))

            declared = extract_declared_tool_names(readme.read_text(encoding="utf-8"))
            declared_missing = sorted(declared - actual)
            undocumented = sorted(actual - declared)

            if declared_missing:
                findings.append(
                    ContractFinding(
                        contract=2, state="violated", reason=None, subject=server,
                        detail=(
                            f"README 声明的 {len(declared_missing)} 个工具在运行时不存在："
                            f"{'、'.join(declared_missing)}。"
                        ),
                        evidence={"server": server, "declared_missing": declared_missing,
                                  "readme": str(readme), "method": "structured-v2"},
                    )
                )
            if undocumented:
                findings.append(
                    ContractFinding(
                        contract=2, state="degraded", reason=None, subject=server,
                        detail=(
                            f"{len(undocumented)} 个工具未在 README 中声明："
                            f"{'、'.join(undocumented)}。"
                        ),
                        evidence={"server": server, "undocumented": undocumented},
                    )
                )
            if not declared_missing and not undocumented:
                findings.append(
                    ContractFinding(
                        contract=2, state="satisfied", reason=None, subject=server,
                        detail=f"{server} 的 README 与运行时工具面一致（{len(actual)} 个）。",
                        evidence={"server": server, "tool_count": len(actual)},
                    )
                )

        return findings
```

- [x] **Step 4: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_doc_impl.py -v
```
Expected: PASS（15 passed）

- [x] **Step 5: 注册并在真实数据上跑一次**

在 `contracts/__init__.py` 追加：

```python
from .doc_impl import DocImplEvaluator

REGISTRY.register(DocImplEvaluator())
__all__ += ["DocImplEvaluator"]
```

然后：

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest -m "not integration" -q
```
Expected: PASS（全部）

- [x] **Step 6: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): 契约 2 文档-实现一致性求值器"
```

---

### Task 6: 契约 6 / 7 —— 标识符与量纲约定表

**Files:**
- Create: `gateway/src/powermcp_gateway/contracts/conventions.py`
- Test: `gateway/tests/test_contract_conventions.py`

**Interfaces:**
- Consumes: `ToolInventory` · `design/tokens.json`（真源，见 Global Constraints 的路径）
- Produces:
  - `load_conventions(tokens_path: Path | None = None) -> Conventions`
    - `Conventions.identifier: dict[str, str]`（server id → `0-based`/`1-based`/`unknown`）
    - `Conventions.suffix: dict[str, str]`
  - `IdentifiersEvaluator`（`contract = 6`）· `DimensionsEvaluator`（`contract = 7`）

**规则**：
- 契约 6：挂了但**不在**约定表中的 server → `degraded`（**唯一来源必须是 tokens.json，不得在代码里硬编码**）；表中有但值为 `unknown` → `unknown / structural`（未实测，不猜）；全部有确定值 → `satisfied`
- 契约 7：`design/tokens.json` 的 `identifierConvention` 存在且四类量纲约定（长度/功率/电压/比值）可解析 → `satisfied`；缺失 → `unknown / structural`

> ⚠️ 引擎↔约定的键**一律小写 server id**。这条在 UI 规范 §4.5 里有明确记载：用显示名（`PyPSA`）会导致查表未命中、静默标错。

- [x] **Step 1: 写失败的测试**

```python
import json

import pytest

from powermcp_gateway.contracts.conventions import (
    IdentifiersEvaluator,
    load_conventions,
)
from powermcp_gateway.inventory import ToolInventory, ToolRecord
from types import SimpleNamespace


def _rec(server: str, name: str = "t_tool") -> ToolRecord:
    return ToolRecord.from_sdk(
        server, SimpleNamespace(name=name, description=None, input_schema={}, output_schema=None)
    )


def _write_tokens(tmp_path, identifier: dict, suffix: dict | None = None):
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps({
        "identifierConvention": {
            "byEngine": identifier,
            "suffix": suffix or {"0-based": "(0-based)", "1-based": "(1-based)",
                                 "unknown": "(约定未知)"},
        }
    }), encoding="utf-8")
    return path


def test_load_conventions_reads_by_engine(tmp_path):
    p = _write_tokens(tmp_path, {"pandapower": "0-based", "pypsa": "1-based"})
    c = load_conventions(p)
    assert c.identifier == {"pandapower": "0-based", "pypsa": "1-based"}
    assert c.suffix["unknown"] == "(约定未知)"


def test_engine_not_in_table_is_degraded(tmp_path):
    p = _write_tokens(tmp_path, {"pandapower": "0-based"})
    ev = IdentifiersEvaluator(load_conventions(p))
    f = [x for x in ev.evaluate(ToolInventory(tools=(_rec("genx"),), failures=()), None)  # type: ignore[arg-type]
         if x.state == "degraded"]
    assert f and f[0].evidence["missing"] == ["genx"]


def test_unknown_binding_is_structural_unknown(tmp_path):
    p = _write_tokens(tmp_path, {"andes": "unknown"})
    ev = IdentifiersEvaluator(load_conventions(p))
    f = ev.evaluate(ToolInventory(tools=(_rec("andes"),), failures=()), None)  # type: ignore[arg-type]
    assert any(x.state == "unknown" and x.reason == "structural" for x in f)


def test_all_bound_is_satisfied(tmp_path):
    p = _write_tokens(tmp_path, {"pandapower": "0-based", "pypsa": "1-based"})
    ev = IdentifiersEvaluator(load_conventions(p))
    f = ev.evaluate(ToolInventory(tools=(_rec("pandapower"), _rec("pypsa")), failures=()), None)  # type: ignore[arg-type]
    assert f[0].state == "satisfied"


def test_real_tokens_file_loads_and_covers_nine_engines():
    """真源 regressions：9 个开源引擎都必须出现在 byEngine 中。"""
    c = load_conventions()
    assert set(c.identifier) == {
        "pandapower", "pypsa", "surge", "andes", "egret",
        "opendss", "hope", "genx", "powerio",
    }
    # 只实测过三者，其余必须是 unknown，不许猜
    assert c.identifier["pandapower"] == "0-based"
    assert c.identifier["pypsa"] == "1-based"
    assert c.identifier["andes"] == "unknown"
```

- [x] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_conventions.py -v
```
Expected: FAIL —— `ModuleNotFoundError`

- [x] **Step 3: 写 `gateway/src/powermcp_gateway/contracts/conventions.py`**

```python
"""契约 6 / 7：标识符与量纲约定。

**唯一真源是 design/tokens.json** —— 代码里不得硬编码引擎↔约定的绑定。
理由见《UI 设计规范》v1.2 §4.5：用显示名（PyPSA）代替 server id（pypsa）
会导致查表未命中、进而静默标错编号约定（该缺陷曾把跨引擎偏差放大 3.1 亿倍）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..config import GatewayConfig
from ..inventory import ToolInventory
from .model import ContractFinding

_CONVENTION_VALUES = {"0-based", "1-based", "unknown"}


def _default_tokens_path() -> Path:
    # gateway/src/powermcp_gateway/contracts/conventions.py -> 项目根
    return Path(__file__).resolve().parents[4] / "design" / "tokens.json"


@dataclass(frozen=True)
class Conventions:
    identifier: dict[str, str]
    suffix: dict[str, str]


def load_conventions(tokens_path: Path | None = None) -> Conventions:
    path = Path(tokens_path) if tokens_path is not None else _default_tokens_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    node = data.get("identifierConvention") or {}
    by_engine = dict(node.get("byEngine") or {})
    bad = {k: v for k, v in by_engine.items() if v not in _CONVENTION_VALUES}
    if bad:
        raise ValueError(f"{path} 中 byEngine 取值非法：{bad}")
    return Conventions(identifier=by_engine, suffix=dict(node.get("suffix") or {}))


class IdentifiersEvaluator:
    contract = 6
    name = "标识符契约"
    timeframe = "T0"

    def __init__(self, conventions: Conventions | None = None) -> None:
        self._c = conventions if conventions is not None else load_conventions()

    def evaluate(self, inv: ToolInventory, cfg: GatewayConfig) -> list[ContractFinding]:
        # all_servers()：未拉起的 server 同样需要有编号约定（其数据一旦展示就要归一）
        mounted = set(inv.all_servers())
        missing = sorted(mounted - set(self._c.identifier))
        unverified = sorted(s for s in mounted if self._c.identifier.get(s) == "unknown")

        findings: list[ContractFinding] = []

        if missing:
            findings.append(
                ContractFinding(
                    contract=6, state="degraded", reason=None, subject="*",
                    detail=(
                        f"{len(missing)} 个已挂载 server 没有编号约定绑定：{'、'.join(missing)}。"
                        f"这些引擎的标识符无法被安全归一。"
                    ),
                    evidence={"missing": missing, "source": "design/tokens.json"},
                )
            )
        if unverified:
            findings.append(
                ContractFinding(
                    contract=6, state="unknown", reason="structural", subject="*",
                    detail=(
                        f"{len(unverified)} 个 server 的编号约定**未实测**，界面显示"
                        f"「{self._c.suffix.get('unknown', '(约定未知)')}」：{'、'.join(unverified)}。"
                    ),
                    evidence={"unverified": unverified},
                )
            )
        if not missing and not unverified:
            findings.append(
                ContractFinding(
                    contract=6, state="satisfied", reason=None, subject="*",
                    detail=f"{len(mounted)} 个 server 的编号约定均已实测绑定。",
                    evidence={"bindings": {s: self._c.identifier[s] for s in sorted(mounted)}},
                )
            )
        return findings


class DimensionsEvaluator:
    """契约 7：量纲约定。T0 只校验约定表本身可用（逐值校验在 T2 / 前端）。"""

    contract = 7
    name = "量纲契约"
    timeframe = "T0"

    def __init__(self, conventions: Conventions | None = None) -> None:
        self._c = conventions if conventions is not None else load_conventions()

    def evaluate(self, inv: ToolInventory, cfg: GatewayConfig) -> list[ContractFinding]:
        if self._c.suffix:
            return [ContractFinding(
                contract=7, state="satisfied", reason=None, subject="*",
                detail="量纲/标识符约定表已加载；逐值校验在 T2 与前端执行。",
                evidence={"suffix_keys": sorted(self._c.suffix)},
            )]
        return [ContractFinding(
            contract=7, state="unknown", reason="structural", subject="*",
            detail="约定表缺少 suffix 定义，无法渲染归一标记。",
            evidence={},
        )]
```

- [x] **Step 4: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_conventions.py -v
```
Expected: PASS（5 passed）

- [x] **Step 5: 注册**

在 `contracts/__init__.py` 追加：

```python
from .conventions import DimensionsEvaluator, IdentifiersEvaluator, load_conventions

REGISTRY.register(IdentifiersEvaluator())
REGISTRY.register(DimensionsEvaluator())
__all__ += ["DimensionsEvaluator", "IdentifiersEvaluator", "load_conventions"]
```

- [x] **Step 6: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): 契约 6/7 约定表加载与自洽校验"
```

---

### Task 7: 契约 1 —— API 版本（启发式 + 显式未知）

**Files:**
- Create: `gateway/src/powermcp_gateway/contracts/api_version.py`
- Test: `gateway/tests/test_contract_api_version.py`

**Interfaces:**
- Consumes: `GatewayConfig.powermcp_root`（定位 server 源码）
- Produces: `ApiVersionEvaluator`（`contract = 1`）· `collect_import_bound_symbols(source: str) -> set[str]` · `find_module_attr_calls(source: str, bound: set[str]) -> set[tuple[str, str]]`

> ⚠️ **本任务实现的是启发式，不是完整判定**（范围收窄见文件头）。它能看到的：形如
> `import pandapower as pp` 后出现 `pp.something(` 的调用。
> **它看不到的**：`net = pp.create_empty_network(); net.deepcopy()` —— 接收者 `net` 是局部变量。
> **这正是已知缺陷 `net.deepcopy()` 的形态**，所以本求值器对这类代码会返回 `unknown / structural`，**绝不猜**。

- [x] **Step 1: 写失败的测试**

```python
from powermcp_gateway.contracts.api_version import (
    ApiVersionEvaluator,
    collect_import_bound_symbols,
    find_module_attr_calls,
)


def test_binds_alias_import():
    src = "import pandapower as pp\nfrom pypsa import Network\n"
    assert collect_import_bound_symbols(src) == {"pp", "Network"}


def test_binds_plain_module_import():
    assert collect_import_bound_symbols("import powerio\n") == {"powerio"}


def test_finds_calls_on_bound_names_only():
    src = """
import pandapower as pp
net = pp.create_empty_network()
net.deepcopy()
other.something()
"""
    bound = collect_import_bound_symbols(src)
    calls = find_module_attr_calls(src, bound)
    assert ("pp", "create_empty_network") in calls
    # net 不是导入绑定 —— 不可静态判定，必须不被当作已判定
    assert ("net", "deepcopy") not in calls
    assert ("other", "something") not in calls


def test_local_receiver_yields_structural_unknown(tmp_path):
    """真实缺陷形态：接收者是局部变量 → 必须返回 unknown，不得猜。"""
    server_dir = tmp_path / "FakeServer"
    server_dir.mkdir()
    (server_dir / "server.py").write_text(
        "import pandapower as pp\n"
        "def tool():\n"
        "    net = pp.create_empty_network()\n"
        "    return net.deepcopy()\n",
        encoding="utf-8",
    )

    class Cfg:
        powermcp_root = tmp_path

    ev = ApiVersionEvaluator(source_dirs={"fake": "FakeServer"})
    findings = ev.evaluate(inv=None, cfg=Cfg())  # type: ignore[arg-type]
    assert len(findings) == 1
    assert findings[0].state == "unknown"
    assert findings[0].reason == "structural"
    assert "局部变量" in findings[0].detail or "静态可判定" in findings[0].detail


def test_syntax_error_is_structural_unknown(tmp_path):
    server_dir = tmp_path / "FakeServer"
    server_dir.mkdir()
    (server_dir / "server.py").write_text("def broken(:\n", encoding="utf-8")

    class Cfg:
        powermcp_root = tmp_path

    ev = ApiVersionEvaluator(source_dirs={"fake": "FakeServer"})
    findings = ev.evaluate(inv=None, cfg=Cfg())  # type: ignore[arg-type]
    assert findings[0].state == "unknown"
    assert findings[0].reason == "structural"
```

- [x] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_api_version.py -v
```
Expected: FAIL —— `ModuleNotFoundError`

- [x] **Step 3: 写 `gateway/src/powermcp_gateway/contracts/api_version.py`**

```python
"""契约 1：API 版本（启发式 + 显式未知）。

⚠️ 范围收窄（见计划文件头）：方案 §2.2 的原表述是「比对 list_tools 实际返回
vs 工具实现调用的 API」。经核实这**不能可靠地静态判定**：
真实缺陷 `net.deepcopy()` 的接收者 `net` 由 `pp.create_empty_network()` 返回，
AST 不做类型推断就无法确定其类型。

因此本求值器只判定"能看到的"（模块级导入绑定的属性调用），
**看不到的一律返回 unknown / structural** —— 依据 UI 规范 v1.2 §3.8.2：
结构性未知必须可表达，且不得猜测。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from ..config import GatewayConfig
from ..inventory import ToolInventory
from .model import ContractFinding

# server id -> PowerMCP 仓库内的目录名（与 doc_impl.SERVER_DOC_DIRS 同源）
SOURCE_DIRS: dict[str, str] = {
    "pandapower": "pandapower",
    "pypsa": "PyPSA",
    "surge": "surge",
    "andes": "ANDES",
    "egret": "Egret",
    "opendss": "OpenDSS",
    "hope": "HOPE",
    "genx": "GenX",
}


def collect_import_bound_symbols(source: str) -> set[str]:
    """源码中由 import 绑定的顶层名字：`import x as y` → y；`from m import n` → n。"""
    tree = ast.parse(source)
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name)
    return bound


def find_module_attr_calls(source: str, bound: set[str]) -> set[tuple[str, str]]:
    """形如 `bound_name.attr(...)` 的调用。只认导入绑定作为接收者。"""
    tree = ast.parse(source)
    calls: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id in bound
        ):
            calls.add((func.value.id, func.attr))
    return calls


@dataclass(frozen=True)
class _Scan:
    bound: set[str]
    calls: set[tuple[str, str]]


class ApiVersionEvaluator:
    contract = 1
    name = "API 版本契约"
    timeframe = "T0"

    def __init__(self, source_dirs: dict[str, str] | None = None) -> None:
        self._dirs = dict(source_dirs) if source_dirs is not None else dict(SOURCE_DIRS)

    def evaluate(self, inv: ToolInventory, cfg: GatewayConfig) -> list[ContractFinding]:
        findings: list[ContractFinding] = []

        for server, dirname in sorted(self._dirs.items()):
            server_dir = cfg.powermcp_root / dirname
            if not server_dir.is_dir():
                findings.append(ContractFinding(
                    contract=1, state="unknown", reason="structural", subject=server,
                    detail=f"未找到 {server} 的源码目录 {server_dir}，无法扫描。",
                    evidence={"server": server, "dir": str(server_dir)},
                ))
                continue

            scanned = 0
            unparseable: list[str] = []
            for py in sorted(server_dir.rglob("*.py")):
                try:
                    source = py.read_text(encoding="utf-8")
                    bound = collect_import_bound_symbols(source)
                    find_module_attr_calls(source, bound)
                except (SyntaxError, UnicodeDecodeError):
                    unparseable.append(str(py.relative_to(server_dir)))
                else:
                    scanned += 1

            findings.append(ContractFinding(
                contract=1, state="unknown", reason="structural", subject=server,
                detail=(
                    f"已扫描 {scanned} 个源文件；但**工具实现调用的 API 无法静态判定** —— "
                    f"接收者多为局部变量（如 `net = pp.create_empty_network(); net.deepcopy()`），"
                    f"AST 不做类型推断即无法确定其类型。本项**不做猜测**，标记为结构性未知。"
                    + (f" 另有 {len(unparseable)} 个文件无法解析。" if unparseable else "")
                ),
                evidence={"server": server, "scanned": scanned, "unparseable": unparseable,
                          "method": "heuristic", "limitation": "local-variable receivers"},
            ))

        return findings
```

- [x] **Step 4: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_contract_api_version.py -v
```
Expected: PASS（5 passed）

- [x] **Step 5: 注册**

在 `contracts/__init__.py` 追加：

```python
from .api_version import ApiVersionEvaluator

REGISTRY.register(ApiVersionEvaluator())
__all__ += ["ApiVersionEvaluator"]
```

- [x] **Step 6: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): 契约 1 API 版本（启发式 + 显式未知）"
```

---

### Task 8: T0 编排与缓存

**Files:**
- Create: `gateway/src/powermcp_gateway/contracts/engine.py`
- Test: `gateway/tests/test_engine.py`

**Interfaces:**
- Consumes: `REGISTRY`（Task 4–7）· `ToolInventory` · `summarize`
- Produces:
  - `async def evaluate_t0(inv: ToolInventory, cfg: GatewayConfig, *, registry=None) -> T0Report`
  - `T0Report`：`findings: tuple[ContractFinding, ...]` · `summary: ReportSummary` · `cache_key: str` · `evaluated_at: str`
  - `def cache_key(inv: ToolInventory) -> str` —— 由 server 集合 + 各 server 工具名与 schema 指纹派生
  - `class T0Cache`：`get(key) -> T0Report | None` · `put(report) -> None`（内存 + 可选磁盘）

**要点**：缓存按 `(server 组合, 工具面指纹)` 而非时间 —— 工具面没变就不重算。
求值器若抛异常，**必须降级为该契约的 `incident` 未知**，不得让整个报告失败。

- [x] **Step 1: 写失败的测试**

```python
from types import SimpleNamespace

import pytest

from powermcp_gateway.contracts.engine import T0Cache, cache_key, evaluate_t0
from powermcp_gateway.contracts.registry import EvaluatorRegistry
from powermcp_gateway.inventory import ToolInventory, ToolRecord


def _rec(server: str, name: str) -> ToolRecord:
    return ToolRecord.from_sdk(
        server, SimpleNamespace(name=name, description=None, input_schema={}, output_schema=None)
    )


class _Boom:
    contract = 3
    name = "boom"
    timeframe = "T0"

    def evaluate(self, inv, cfg):
        raise RuntimeError("evaluator exploded")


class _Ok:
    contract = 5
    name = "ok"
    timeframe = "T0"

    def evaluate(self, inv, cfg):
        from powermcp_gateway.contracts.model import ContractFinding
        return [ContractFinding(contract=5, state="satisfied", reason=None,
                                subject="*", detail="", evidence={})]


def test_cache_key_is_stable_for_same_inventory():
    a = ToolInventory(tools=(_rec("pandapower", "x_tool"),), failures=())
    b = ToolInventory(tools=(_rec("pandapower", "x_tool"),), failures=())
    assert cache_key(a) == cache_key(b)


def test_cache_key_changes_when_tools_change():
    a = ToolInventory(tools=(_rec("pandapower", "x_tool"),), failures=())
    b = ToolInventory(tools=(_rec("pandapower", "y_tool"),), failures=())
    assert cache_key(a) != cache_key(b)


async def test_evaluator_crash_becomes_incident_not_failure():
    reg = EvaluatorRegistry()
    reg.register(_Boom())
    inv = ToolInventory(tools=(_rec("pandapower", "x_tool"),), failures=())

    report = await evaluate_t0(inv, cfg=None, registry=reg)  # type: ignore[arg-type]

    assert report.summary.primary == "incident"
    boom = [f for f in report.findings if f.contract == 3]
    assert len(boom) == 1
    assert boom[0].state == "unknown"
    assert boom[0].reason == "incident"
    assert "RuntimeError" in boom[0].detail


async def test_report_summarises_overall():
    reg = EvaluatorRegistry()
    reg.register(_Ok())
    inv = ToolInventory(tools=(_rec("pandapower", "x_tool"),), failures=())

    report = await evaluate_t0(inv, cfg=None, registry=reg)  # type: ignore[arg-type]
    assert report.summary.primary == "satisfied"
    assert report.cache_key == cache_key(inv)
    assert report.evaluated_at.endswith("Z")


def test_cache_put_get_roundtrip():
    c = T0Cache()
    assert c.get("nope") is None


# —— ★ 完成标准 #5：失败路径的验收（注入构造，不依赖真实环境哪个 server 会失败）——

async def test_failed_server_yields_actionable_hint(monkeypatch):
    """未拉起的 server 必须：a) 给出可执行修复路径；b) 记为 structural（有路径 → 不是事故）；
    c) 在契约 2 里**不被静默跳过**。"""
    import powermcp_gateway.inventory as inv_mod
    from powermcp_gateway.config import GatewayConfig

    # ⚠️ 必须传真实 config：契约 2 要用 cfg.powermcp_root 定位 README。
    #    传 None 会让它抛异常并被 evaluate_t0 降级成 subject="*" 的 incident，
    #    下面 c2 的断言就落空了。
    cfg = GatewayConfig.discover()

    async def boom(cfg_, server, timeout_s=None):
        raise ExceptionGroup("unhandled errors in a TaskGroup", [
            RuntimeError("ANDES: required package 'andes' is not installed. "
                         "Install it with: pip install powermcp[andes]"),
        ])

    monkeypatch.setattr(inv_mod, "fetch_server_tools", boom)
    inv = await inv_mod.build_inventory(cfg, ["andes"])
    report = await evaluate_t0(inv, cfg)

    c8 = [f for f in report.findings if f.contract == 8 and f.subject == "andes"]
    assert c8, "未拉起的 server 没有产生契约 8 finding"
    assert "pip install powermcp[andes]" in c8[0].detail     # a) 可执行修复路径
    assert c8[0].state == "unknown"
    assert c8[0].reason == "structural"                      # b) 有修复路径 → 不是事故

    c2 = [f for f in report.findings if f.contract == 2 and f.subject == "andes"]
    assert c2, "该 server 在契约 2 里被静默跳过了"            # c)
    assert c2[0].state == "unknown" and c2[0].reason == "structural"
    assert c2[0].evidence["mounted"] is False


async def test_failed_server_without_hint_is_incident(monkeypatch):
    """超时类失败没有可执行修复路径 → 仍记为 incident（与 a/b 的区分不能混）。"""
    import powermcp_gateway.inventory as inv_mod
    from powermcp_gateway.config import GatewayConfig

    cfg = GatewayConfig.discover()

    async def boom(cfg_, server, timeout_s=None):
        raise TimeoutError(f"{server} 在 90s 内未完成 MCP 握手（initialize / list_tools 无响应）")

    monkeypatch.setattr(inv_mod, "fetch_server_tools", boom)
    inv = await inv_mod.build_inventory(cfg, ["surge"])
    report = await evaluate_t0(inv, cfg)

    c8 = [f for f in report.findings if f.contract == 8 and f.subject == "surge"]
    assert c8 and c8[0].reason == "incident"
```

- [x] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_engine.py -v
```
Expected: FAIL —— `ModuleNotFoundError`

- [x] **Step 3: 写 `gateway/src/powermcp_gateway/contracts/engine.py`**

```python
"""T0 契约求值编排与缓存。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import GatewayConfig
from ..inventory import ToolInventory
from .model import ContractFinding, ReportSummary, summarize
from .registry import REGISTRY, EvaluatorRegistry


def cache_key(inv: ToolInventory) -> str:
    """由"工具面"派生 —— 工具名或 schema 变了，缓存即失效。"""
    payload = {
        "servers": list(inv.servers()),
        "tools": sorted(
            (t.server, t.name, json.dumps(t.input_schema, sort_keys=True, ensure_ascii=False))
            for t in inv.tools
        ),
        "failures": sorted((f.server, f.error) for f in inv.failures),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class T0Report:
    findings: tuple[ContractFinding, ...]
    summary: ReportSummary
    cache_key: str
    evaluated_at: str


class T0Cache:
    """内存缓存。磁盘持久化留待需要时再加（YAGNI）。"""

    def __init__(self) -> None:
        self._mem: dict[str, T0Report] = {}

    def get(self, key: str) -> T0Report | None:
        return self._mem.get(key)

    def put(self, report: T0Report) -> None:
        self._mem[report.cache_key] = report


async def evaluate_t0(
    inv: ToolInventory,
    cfg: GatewayConfig,
    *,
    registry: EvaluatorRegistry | None = None,
    cache: T0Cache | None = None,
) -> T0Report:
    """求值全部已注册的 T0 契约。

    单个求值器崩溃 → 记为该契约的 incident 未知；**绝不让整体失败**。
    依据 UI 规范 v1.2 §4.6.6 的失败语义：fail-loud but non-blocking。
    """
    reg = registry if registry is not None else REGISTRY
    key = cache_key(inv)

    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return hit

    findings: list[ContractFinding] = []

    for evaluator in reg.all():
        try:
            findings.extend(evaluator.evaluate(inv, cfg))
        except Exception as exc:  # noqa: BLE001 —— 见 docstring：降级而非中断
            findings.append(
                ContractFinding(
                    contract=evaluator.contract,
                    state="unknown",
                    reason="incident",
                    subject="*",
                    detail=(
                        f"契约 {evaluator.contract}（{evaluator.name}）的求值器崩溃："
                        f"{type(exc).__name__}: {exc}"[:200]
                    ),
                    evidence={"evaluator": evaluator.name, "error": repr(exc)[:400]},
                )
            )

    # 挂了但拿不到清单的 server 本身也是一条 finding。
    # ★ 失败原因若**自带可执行修复路径**（依赖缺失类），记为 structural 而非 incident ——
    #   "知道怎么修" 与 "出了事故" 是两种不同的信号，混在一起会让事故标记失去意义。
    for failure in inv.failures:
        findings.append(
            ContractFinding(
                contract=8,
                state="unknown",
                reason="structural" if failure.hint else "incident",
                subject=failure.server,
                detail=(
                    f"server `{failure.server}` 未能拉起：{failure.error}"
                    + (f" 修复：{failure.hint}" if failure.hint else "")
                ),
                evidence={
                    "server": failure.server,
                    "error": failure.error,
                    "hint": failure.hint,
                    "probe_missing": failure.probe_missing,
                },
            )
        )

    report = T0Report(
        findings=tuple(findings),
        summary=summarize(findings),
        cache_key=key,
        evaluated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    if cache is not None:
        cache.put(report)
    return report
```

- [x] **Step 4: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_engine.py -v
```
Expected: PASS（7 passed）

- [x] **Step 5: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): T0 求值编排与缓存"
```

---

### Task 9: HTTP API

**Files:**
- Create: `gateway/src/powermcp_gateway/api.py`
- Test: `gateway/tests/test_api.py`

**Interfaces:**
- Consumes: `GatewayConfig` · `build_inventory` · `evaluate_t0`
- Produces: `create_app(cfg: GatewayConfig | None = None) -> FastAPI`
  - `GET /health` → `{"status": "ok"}`
  - `GET /servers` → 已挂载 server 列表
  - `GET /contracts/t0` → `T0Report` 的 JSON（含 `findings` 与 `summary`）

> `/contracts/t0` 是 P1 的**核心端点** —— 前端的契约面板（子项目 5）从它取数据。
> `summary.primary` 的取值集合必须与 UI 规范的 `SignatureKey` 一致（含 `incident`）。

- [x] **Step 1: 写失败的测试**

```python
import pytest
from httpx import ASGITransport, AsyncClient

from powermcp_gateway.api import create_app


@pytest.fixture
def app():
    return create_app()


async def test_health(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_servers_lists_open_source_nine(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/servers")
    assert r.status_code == 200
    servers = r.json()["servers"]
    assert "pandapower" in servers
    assert all(s == s.lower() for s in servers)
    # 商业引擎必须不在其中（方案 v3 已移除）
    for closed in ("powerworld", "psse", "pslf", "powerfactory", "pscad", "ltspice", "plexosdb"):
        assert closed not in servers
```

- [x] **Step 2: 跑测试，确认失败**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_api.py -v
```
Expected: FAIL —— `ModuleNotFoundError`

- [x] **Step 3: 写 `gateway/src/powermcp_gateway/api.py`**

```python
"""网关 HTTP API。"""

from __future__ import annotations

import dataclasses

from fastapi import FastAPI, HTTPException

from .config import GatewayConfig
from .contracts.engine import T0Cache, evaluate_t0
from .inventory import build_inventory

# P1 只挂开源引擎（方案 v3 已移除全部商业引擎）
OPEN_SOURCE_SERVERS: tuple[str, ...] = (
    "pandapower", "pypsa", "surge", "andes",
    "egret", "opendss", "hope", "genx", "powerio",
)

_cache = T0Cache()


def create_app(cfg: GatewayConfig | None = None) -> FastAPI:
    app = FastAPI(title="PowerMCP Gateway", version="0.1.0")
    config = cfg

    def _cfg() -> GatewayConfig:
        nonlocal config
        if config is None:
            config = GatewayConfig.discover()
        return config

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/servers")
    async def servers() -> dict[str, list[str]]:
        return {"servers": list(OPEN_SOURCE_SERVERS)}

    @app.get("/contracts/t0")
    async def contracts_t0() -> dict:
        try:
            c = _cfg()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        inv = await build_inventory(c, OPEN_SOURCE_SERVERS)
        report = await evaluate_t0(inv, c, cache=_cache)
        return {
            "cache_key": report.cache_key,
            "evaluated_at": report.evaluated_at,
            "summary": dataclasses.asdict(report.summary),
            "findings": [dataclasses.asdict(f) for f in report.findings],
        }

    return app
```

- [x] **Step 4: 跑测试，确认通过**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest tests/test_api.py -v
```
Expected: PASS（2 passed）

- [x] **Step 5: 真实启动并手工核验一次**

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m uvicorn powermcp_gateway.api:create_app --factory --port 8765 &
sleep 5
curl -s http://127.0.0.1:8765/health
curl -s http://127.0.0.1:8765/contracts/t0 | head -c 2000
```
Expected:
- `/health` → `{"status":"ok"}`
- `/contracts/t0` → JSON，含 `summary`（`primary` 为 `incident`/`satisfied`/`unknown` 之一）与 `findings`；
  其中应有**契约 5 的 `degraded`** 条目，evidence 里能列出 `load_network` 的多个 server。

> 首次调用会真实拉起 9 个 server，约需 1–3 分钟。
>
> ⚠️ **首版此处断言「`hope` / `genx` 因缺 Julia 会失败」是错的** —— 实测 **9 个全部可拉起**
> （含 opendss 55 个工具）。真实的失败模式是**缺 pip extra**，且**当前环境下可能一个都不失败**。
> 因此**不要期待某个特定 server 出现在 `failures` 里** —— 那会随环境变化。
> 失败路径的验收改用注入方式，见「完成标准」第 5 条。

- [x] **Step 6: 提交**

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/
git commit -m "feat(gateway): HTTP API 暴露 T0 契约状态"
```

- [x] **Step 7: 写 `gateway/README.md` 并提交**

```markdown
# PowerMCP Gateway

本地网关：拉起 9 个开源 MCP server，求值 T0 静态契约，通过 HTTP 暴露契约状态。

## 运行

```bash
../PowerMCP/.venv/Scripts/python.exe -m uvicorn powermcp_gateway.api:create_app --factory --port 8765
```

## 端点

| 端点 | 说明 |
|---|---|
| `GET /health` | 存活检查 |
| `GET /servers` | 已挂载的 9 个开源 server |
| `GET /contracts/t0` | T0 契约报告（`summary` + `findings`） |

## 测试

```bash
../PowerMCP/.venv/Scripts/python.exe -m pytest -m "not integration"   # 快
../PowerMCP/.venv/Scripts/python.exe -m pytest -m integration          # 需真实拉起 server
```

## 已知范围收窄

契约 1（API 版本）**无法可靠地静态判定** —— 工具实现调用的引擎 API 其接收者多为局部变量，
AST 不做类型推断即无法确定类型（真实缺陷 `net.deepcopy()` 正是此形态）。
因此契约 1 一律返回 `unknown / structural`，**不猜测**。详见 `contracts/api_version.py`。
```

```bash
cd d:/coding/powerMcp_Pskills
git add gateway/README.md
git commit -m "docs(gateway): 运行说明与已知范围收窄"
```

---

## 完成标准

全部任务完成后，下列命令必须通过：

```bash
cd d:/coding/powerMcp_Pskills/gateway
../PowerMCP/.venv/Scripts/python.exe -m pytest -v -m "not integration"
```

且真实启动后 `GET /contracts/t0` 返回的报告满足：

1. `summary.primary` ∈ `{satisfied, degraded, violated, unknown, incident}`
2. 契约 5 有 `degraded` 条目，evidence 列出 `load_network` 的多个 server
3. 契约 1 为 `unknown / structural`，detail 里写明无法静态判定的原因
4. ★ **契约 2 的 `violated` 条数应为 0 或极少。** 首版规则误报 73 条（pypsa 独占 36）；
   修正后按实测应降到个位数。若仍出现大批 `violated`，说明章节作用域或 schema 排除失效 ——
   **这是本轮修订的主要验收点**。
5. ★ **失败路径的验收不得依赖"哪个 server 会失败"**（那是环境相关的，实测 9 个 server 当前全部可拉起）。
   改为验收**失败时的行为**，用注入方式构造 —— 见下方代码。

若真实环境下确有 server 拉不起来，再额外人工核对一次这条路径即可。

**失败路径的验收测试（加入 `gateway/tests/test_engine.py`）：**

```python
import powermcp_gateway.inventory as inv_mod
from powermcp_gateway.config import GatewayConfig
from powermcp_gateway.contracts.engine import evaluate_t0


async def test_failed_server_yields_actionable_hint(monkeypatch):
    # ⚠️ 必须传真实 config：契约 2 要用 cfg.powermcp_root 定位 README。
    #    传 None 会让它抛异常并被 evaluate_t0 降级成 subject="*" 的 incident，
    #    下面 c2 的断言就落空了。
    cfg = GatewayConfig.discover()

    async def boom(cfg_, server, timeout_s=None):
        raise ExceptionGroup("unhandled errors in a TaskGroup", [
            RuntimeError("ANDES: required package 'andes' is not installed. "
                         "Install it with: pip install powermcp[andes]"),
        ])

    monkeypatch.setattr(inv_mod, "fetch_server_tools", boom)
    inv = await inv_mod.build_inventory(cfg, ["andes"])
    report = await evaluate_t0(inv, cfg)

    c8 = [f for f in report.findings if f.contract == 8 and f.subject == "andes"]
    assert c8, "未拉起的 server 没有产生契约 8 finding"
    assert "pip install powermcp[andes]" in c8[0].detail     # a) 可执行修复路径
    assert c8[0].state == "unknown"
    assert c8[0].reason == "structural"                      # b) 有修复路径 → 不是事故

    c2 = [f for f in report.findings if f.contract == 2 and f.subject == "andes"]
    assert c2, "该 server 在契约 2 里被静默跳过了"            # c)
```

---

## 后续计划（不在本计划范围）

- **子项目 3**：契约引擎 T2（契约 3 参数 / 4 状态映射）+ NDJSON 审计 + SSE 双通道
- **子项目 4**：进程监管（心跳 / 退避重启 / 熔断 / 引擎状态端点）
- **子项目 1**：设计系统落地（tokens → CSS 变量 / Tailwind / 5 个签名组件 / Zod 边界）
- **子项目 5**：前端视图（聊天面板 + 契约面板），消费本计划的 `/contracts/t0` 与后续的 SSE

---

## 执行记录（2026-09-24 回填）

### 状态

| 项 | 结果 |
|---|---|
| Task 完成度 | **10 / 10**；Step **64 / 64** |
| 交付文件 | 25 个（`gateway/` 24 + `.gitignore`），全部已纳入 git |
| 单元测试 | **76 passed**（`pytest -m "not integration"`） |
| 集成测试 | **1 passed**（真实拉起 pandapower，8 工具） |
| 提交 | 17 个（`1baa8a7` … 见 `git log`） |
| `PowerMCP/` 改动 | **0 行**（*zero source mutation* 保持） |

### 完成标准 5/5（含全部 9 个 server 的实测）

| # | 标准 | 实测 |
|---|---|---|
| ① | `summary.primary` ∈ 五值集合 | ✅ `incident` |
| ② | 契约 5 有 degraded，evidence 列出 `load_network` 多 server | ✅ `['pandapower','pypsa','surge']` |
| ③ | 契约 1 全为 `unknown/structural` 且写明原因 | ✅ 8 条 |
| ④ | 契约 2 的 `violated` 为 0 或极少 | ✅ **0** |
| ⑤ | 失败路径按注入方式验收（不依赖环境） | ✅ 见 `test_engine.py::test_failed_server_yields_actionable_hint` |

真实快照：已挂载 **8/9**、工具 **117**、`summary = incident / structural 11 / incident 1`；
契约 2 → 5 satisfied + 2 degraded + 2 structural；契约 5 → 11 条重名（全部 schema 不同）。

### 与「原计划预测」的偏差（环境相关，非实现缺陷）

原计划预测 `hope` / `genx` 因缺 Julia 拉不起来。**实测相反**：二者均可正常拉起（20 / 7 工具）。
真正拉不起来的是 **`andes` / `egret` / `opendss`**（缺 pip extra）。按最小依赖安装后
（`andes` · `gridx-egret` + `pyomo` · `py_dss_toolkit`，34 个包纯新增、零版本升降），
`andes` / `egret` 挂载成功，**仅 `opendss` 仍失败** —— 依赖已满足、协议层正常
（裸探针 1.86s 正确响应），但经 mcp SDK 握手超时，属**独立缺陷**，
已另立 [opendss 缺陷立项](2026-09-24-opendss-sdk-mount-defect.md)。

### 与「本计划规格」的偏差（已回改为已交付实现）

| 位置 | 原规格 | 已交付实现 |
|---|---|---|
| Task 1 | `describe_exception(exc) -> (summary, causes)` | `_describe_error(exc) -> str`（+ `_is_timeout` / `_timeout_error`） |
| Task 1 | `ServerFailure.causes` | 未采纳（`error` 已含摊平后的文本） |
| Task 5 | 数据驱动章节作用域 + schema 属性名排除 | **结构化提取 v2**（实测误报 0 vs 另一方案 13/47，对比见 Task 5 ★ 节） |
| Task 2/5 | 契约 2 迭代 `servers()` | 迭代 **`all_servers()`**（缺陷 B） |

已交付的 `inventory.py` / `doc_impl.py` / `engine.py` 及其测试的**完整代码已同步进本计划对应 Step**，
可直接对照。契约 2 的 v2 口径**已在真实数据上验证误报为 0**。

### 回填时同步的文档缺陷（4 处）

1. Task 0 测试断言写死 POSIX 分隔符 `powermcp/registry.py` → 改 `r"powermcp[\\/]registry\.py"`（Windows 必然失败）
2. Task 2 预期「8 passed」→「9 passed」（测试函数实为 9 个）
3. Task 3 桩 `_Stub.contract = 9` 越出 1–8，与同文件 `test_invalid_contract_number_rejected` 冲突 → 改用 **8**
4. File Structure 漏登记 `gateway/tests/test_contract_registry.py`

### 遗留

- **opendss 无法经 mcp SDK 挂载**（唯一真阻塞，影响计划 Goal 的"拉起 9 个"）—— 见立项文档
- `docs/` 与 `design/`、`tools/` 已纳入 git；`docs/_pdfwork/`（7.3MB 可再生中间产物）按约定排除
