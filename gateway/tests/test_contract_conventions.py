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
