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
