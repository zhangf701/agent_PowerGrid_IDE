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
