import ast
import textwrap

from powermcp_gateway.contracts.status_mapping import (
    StatusMappingEvaluator,
    analyse_tool_fn,
)


def _fn(src: str) -> ast.FunctionDef:
    tree = ast.parse(textwrap.dedent(src))
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "tool")


def test_detects_engine_read():
    fn = _fn('''
    def tool():
        return {"status": "success", "converged": net.converged}
    ''')
    hard, reads = analyse_tool_fn(fn)
    assert hard is True
    assert "net.converged" in reads


def test_detects_no_read():
    fn = _fn('''
    def tool():
        net.pf()
        return {"status": "success"}
    ''')
    hard, reads = analyse_tool_fn(fn)
    assert hard is True
    assert reads == ()


def test_error_only_branch_is_not_flagged_as_success():
    fn = _fn('''
    def tool():
        try:
            net.pf()
        except Exception as e:
            return {"status": "error", "message": str(e)}
    ''')
    hard, _ = analyse_tool_fn(fn)
    assert hard is False        # 只报 error 不算"报告成功"


def test_conditional_status_counts_as_read():
    fn = _fn('''
    def tool():
        success = run()
        return {"status": "completed" if success else "failed"}
    ''')
    hard, reads = analyse_tool_fn(fn)
    assert hard is False, "条件表达式的状态不是**硬编码**成功（它有条件地报成功）"
    assert reads, "条件表达式的状态应被视为读取（值不是字面量常量）"


# —— 端到端：真实仓库上的对照 ——

def test_pypsa_run_power_flow_is_flagged(tmp_path):
    """★ 实测形态：PyPSA 的 run_power_flow 报 success 却不读 converged。"""
    d = tmp_path / "PyPSA"
    d.mkdir()
    (d / "pypsa_mcp.py").write_text(textwrap.dedent('''
        @mcp.tool()
        def run_power_flow(network_name: str) -> dict:
            network = Network(network_name)
            network.pf()
            return {"status": "success", "buses": {}}
    '''), encoding="utf-8")

    class Cfg:
        powermcp_root = tmp_path

    ev = StatusMappingEvaluator(source_dirs={"pypsa": "PyPSA"})
    findings = ev.evaluate(inv=None, cfg=Cfg())   # type: ignore[arg-type]

    risky = [f for f in findings if f.state == "degraded"]
    assert risky, f"未检出，实际 {[(f.subject, f.state) for f in findings]}"
    assert risky[0].subject == "pypsa"                       # finding 按 server 聚合
    assert risky[0].evidence["risky_tools"] == ["run_power_flow"]


def test_pandapower_design_is_not_flagged(tmp_path):
    """★ 对照组：status 硬编码 success 但 converged 读自引擎 —— 这是**正确设计**，不得误报。"""
    d = tmp_path / "pandapower"
    d.mkdir()
    (d / "panda_mcp.py").write_text(textwrap.dedent('''
        @mcp.tool()
        def run_power_flow(net: str) -> dict:
            pp.runpp(net)
            return {"status": "success", "converged": net.converged}
    '''), encoding="utf-8")

    class Cfg:
        powermcp_root = tmp_path

    ev = StatusMappingEvaluator(source_dirs={"pandapower": "pandapower"})
    findings = ev.evaluate(inv=None, cfg=Cfg())   # type: ignore[arg-type]
    assert [f.state for f in findings] == ["satisfied"]


def test_functional_registration_is_recognised(tmp_path):
    """★ 实测形态：OpenDSS 用 mcp.tool()(fn) 注册，不是装饰器。

    只认装饰器会让 OpenDSS 的 55 个工具全部漏检（见模块 docstring）。
    """
    d = tmp_path / "OpenDSS"
    d.mkdir()
    (d / "opendss_mcp.py").write_text(textwrap.dedent('''
        def solve_snapshot() -> dict:
            dss_tools.simulation.solve_snapshot()
            return {"status": "success"}

        def register_simulation_tools(mcp) -> None:
            mcp.tool()(solve_snapshot)
    '''), encoding="utf-8")

    class Cfg:
        powermcp_root = tmp_path

    ev = StatusMappingEvaluator(source_dirs={"opendss": "OpenDSS"})
    findings = ev.evaluate(inv=None, cfg=Cfg())   # type: ignore[arg-type]

    assert [f.state for f in findings] == ["degraded"], (
        f"函数式注册的 solve_snapshot 未被识别：{[(f.subject, f.state) for f in findings]}"
    )
    assert findings[0].evidence["risky_tools"] == ["solve_snapshot"]
    assert findings[0].evidence["tools_recognised"] == 1


def test_zero_checked_is_structural_unknown(tmp_path):
    """★ checked == 0 不得报 satisfied —— 那是假绿灯（UI 规范 P5 禁止静默 fail-open）。"""
    d = tmp_path / "GenX"
    d.mkdir()
    (d / "genx_mcp.py").write_text(textwrap.dedent('''
        @mcp.tool()
        def dispatch() -> dict:
            return {"status": "success"}
    '''), encoding="utf-8")

    class Cfg:
        powermcp_root = tmp_path

    ev = StatusMappingEvaluator(source_dirs={"genx": "GenX"})
    findings = ev.evaluate(inv=None, cfg=Cfg())   # type: ignore[arg-type]

    assert [f.state for f in findings] == ["unknown"]
    assert findings[0].reason == "structural"
    assert findings[0].evidence["tools_recognised"] == 1
    assert findings[0].evidence["solve_tools_checked"] == 0
