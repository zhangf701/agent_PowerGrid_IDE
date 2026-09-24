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
