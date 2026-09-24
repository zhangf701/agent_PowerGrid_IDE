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


def test_global_registry_contains_exactly_the_registered_contracts():
    """★ 钉住**全局** REGISTRY 的契约集合，尤其是「契约 3 不在其中」。

    契约 3 是**事件驱动**的：它由 `proxy.call_tool` 在代理侧校验参数时直接产生
    （见 `contracts/params.py` 尾段说明），**不经 T0 静态求值、刻意不注册进
    REGISTRY**。

    这一约束成立的基石是：`contracts/__init__.py` **只用显式 import + 显式
    `REGISTRY.register(...)`，没有任何 pkgutil / 目录自动扫描**。本测试导入该包
    触发其 `__init__` 的注册后断言契约集合 —— 任何人后续多加一行 import 把契约 3
    意外注册进来，这里就会变红（此前 `test_contract_registry.py` 全用 stub，
    对全局集合零覆盖）。
    """
    import powermcp_gateway.contracts  # noqa: F401 —— 导入即触发 __init__ 的注册
    from powermcp_gateway.contracts.registry import REGISTRY

    contracts = {e.contract for e in REGISTRY.all()}
    assert contracts == {1, 2, 4, 5, 6, 7}
    assert 3 not in contracts, "契约 3 是事件驱动的，刻意不注册进 REGISTRY"
