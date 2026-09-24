from types import SimpleNamespace

import pytest

from powermcp_gateway.inventory import ServerFailure, ToolInventory, ToolRecord


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
