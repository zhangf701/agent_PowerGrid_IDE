import pytest

from powermcp_gateway.contracts.model import (
    CONTRACT_NAMES,
    ContractFinding,
    summarize,
)


def _f(contract: int, state: str, reason: str | None = None) -> ContractFinding:
    return ContractFinding(
        contract=contract, state=state, reason=reason,
        subject="test", detail="", evidence={},
    )


def test_unknown_requires_reason():
    with pytest.raises(ValueError, match="reason"):
        ContractFinding(contract=4, state="unknown", reason=None,
                        subject="x", detail="", evidence={})


def test_known_state_must_not_carry_reason():
    with pytest.raises(ValueError, match="reason"):
        ContractFinding(contract=3, state="degraded", reason="structural",
                        subject="x", detail="", evidence={})


def test_contract_names_cover_1_to_8():
    assert set(CONTRACT_NAMES) == set(range(1, 9))
    assert CONTRACT_NAMES[3] == "参数契约"
    assert CONTRACT_NAMES[5] == "命名空间契约"


# —— 以下四例逐字取自《UI 设计规范》§4.3 的双轨汇总表 ——

def test_structural_unknown_does_not_outrank_degraded():
    s = summarize([_f(7, "satisfied"), _f(4, "unknown", "structural"), _f(3, "degraded")])
    assert s.primary == "degraded"
    assert s.structural_unknown == 1
    assert s.incident_unknown == 0


def test_structural_unknown_alone_leaves_primary_satisfied():
    s = summarize([_f(7, "satisfied"), _f(1, "satisfied"), _f(4, "unknown", "structural")])
    assert s.primary == "satisfied"
    assert s.structural_unknown == 1


def test_incident_escalates_over_everything():
    s = summarize([_f(7, "satisfied"), _f(4, "unknown", "structural"), _f(3, "unknown", "incident")])
    assert s.primary == "incident"
    assert s.structural_unknown == 1
    assert s.incident_unknown == 1


def test_empty_is_unknown_not_satisfied():
    s = summarize([])
    assert s.primary == "unknown"
    assert s.structural_unknown == 0
    assert s.incident_unknown == 0


def test_all_structural_unknown_yields_unknown_primary():
    s = summarize([_f(4, "unknown", "structural"), _f(6, "unknown", "structural")])
    assert s.primary == "unknown"
    assert s.structural_unknown == 2


def test_violated_outranks_degraded():
    s = summarize([_f(3, "degraded"), _f(7, "violated")])
    assert s.primary == "violated"
