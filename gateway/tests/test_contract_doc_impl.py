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


def test_extract_picks_backticked_snake_case():
    md = """
    ## Tools
    - `run_power_flow` — runs a power flow
    - `load_network` — loads a network
    Use `pip install pandapower` to get started.
    """
    got = extract_declared_tool_names(md)
    assert "run_power_flow" in got
    assert "load_network" in got
    assert "pip" not in got          # 太短
    assert "pandapower" not in got   # 无下划线且非工具名形态


def test_declared_but_missing_is_violated(tmp_path):
    server_dir = tmp_path / "FakeServer"
    server_dir.mkdir()
    (server_dir / "README.md").write_text(
        "Tools: `does_not_exist`, `also_missing`.", encoding="utf-8"
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
    (server_dir / "README.md").write_text("Tools: `documented_tool`.", encoding="utf-8")

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
    (server_dir / "README.md").write_text("Only `the_tool` exists.", encoding="utf-8")

    class Cfg:
        powermcp_root = tmp_path

    ev = DocImplEvaluator(doc_dirs={"fake": "FakeServer"})
    findings = ev.evaluate(
        ToolInventory(tools=(_rec("fake", "the_tool"),), failures=()), cfg=Cfg()  # type: ignore[arg-type]
    )
    assert findings[0].state == "satisfied"
