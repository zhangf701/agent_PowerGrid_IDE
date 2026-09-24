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
