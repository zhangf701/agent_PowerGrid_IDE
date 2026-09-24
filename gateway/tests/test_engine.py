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
