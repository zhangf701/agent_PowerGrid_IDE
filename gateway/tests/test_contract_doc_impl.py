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
