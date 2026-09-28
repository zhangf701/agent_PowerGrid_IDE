from __future__ import annotations

import json

import pytest

from powermcp_gateway.experiment_v2 import (
    ExperimentProposal, Hypothesis, Observation, ProposalStore, ResearchQuestion,
    ObservationStore, compile_proposal, estimate_resources, validate_proposal,
)
from powermcp_gateway.experiment_v2.analysis import analyze
from powermcp_gateway.experiment_v2.compiler import commit_proposal
from powermcp_gateway.experiment_v2.validator import ProposalValidationError


def proposal(**changes):
    value = {
        "proposal_id": "p1", "title": "scan",
        "research_question": {"id": "rq1", "statement": "question"},
        "hypothesis": {"id": "h1", "statement": "hypothesis"},
        "design": {"cases": [{"case_id": "c1"}], "factors": [{"name": "scale", "type": "number", "values": [1.0, 1.1]}]},
        "execution": {"steps": [{"server": "surge", "tool": "load_network", "args_template": {"file_path": "{case_path}", "scale": "{scale}"}}]},
        "observables": {"metrics": ["loading"]}, "analysis": {"methods": ["summary"]},
    }
    value.update(changes)
    return ExperimentProposal.from_dict(value)


def test_models_are_frozen_and_round_trip():
    question = ResearchQuestion("rq", "q", {"cases": ["c1"]})
    assert question.to_dict()["scope"] == {"cases": ["c1"]}
    with pytest.raises((TypeError, AttributeError)):
        question.scope["x"] = 1


def test_validator_rejects_empty_steps_and_unknown_placeholder():
    report = validate_proposal(proposal(execution={"steps": [{"server": "surge", "tool": "t", "args_template": {"x": "{missing}"}}]}))
    assert not report.valid
    assert any("missing" in error for error in report.errors)
    report = validate_proposal(proposal(execution={"steps": []}))
    assert not report.valid


def test_compile_is_deterministic_and_freezes_case_identity():
    first = compile_proposal(proposal(), case_inputs={"c1": {"case_sha256": "sha", "case_path": "/cases/c1"}})
    second = compile_proposal(proposal(), case_inputs={"c1": {"case_sha256": "sha", "case_path": "/cases/c1"}})
    assert first.to_dict() == second.to_dict()
    assert len(first.cells) == 2
    assert all(cell.cell_id and cell.case_sha256 == "sha" and cell.case_path == "/cases/c1" for cell in first.cells)
    assert first.cells[0].steps[0]["args"]["scale"] == 1.0


def test_compile_rejects_unfixed_case_identity():
    with pytest.raises(ProposalValidationError):
        compile_proposal(proposal())


def test_resource_estimate():
    estimate = estimate_resources(3, 2, duration_per_step_s=1.5)
    assert estimate.total_steps == 6
    assert estimate.estimated_duration_s == 9


def test_proposal_store_round_trip(tmp_path):
    store = ProposalStore(tmp_path)
    store.create(proposal())
    assert store.get("p1").title == "scan"
    assert [p.proposal_id for p in store.list()] == ["p1"]
    with pytest.raises(Exception):
        store.create(proposal())


def test_observation_jsonl_and_query(tmp_path):
    store = ObservationStore(tmp_path)
    store.append(Observation("o1", "cell-1", {"case_id": "c1", "scale": 1}, {"status": "completed"}, {"loading": 99}))
    store.append(Observation("o2", "cell-2", {"case_id": "c1", "scale": 2}, {"status": "not_converged"}, {"loading": 120}))
    assert len(store.all()) == 2
    assert [o.observation_id for o in store.query(status="completed")] == ["o1"]
    assert len(store.path.read_text(encoding="utf-8").splitlines()) == 2


def test_analysis_has_structured_deterministic_sections():
    observations = [
        Observation("o1", "cell-1", {"case_id": "c1", "scale": 1}, {"status": "completed"}, {"loading": 99}),
        Observation("o2", "cell-2", {"case_id": "c1", "scale": 2}, {"status": "not_converged"}, {"loading": 120}),
    ]
    result = analyze(observations)
    assert set(result) >= {"summary", "extreme_cases", "boundary_cases", "factor_comparisons", "failure_summary"}
    assert result["summary"]["not_converged"] == 1
    assert result["extreme_cases"][0]["value"] == 120
    assert result["boundary_cases"]
    assert result == analyze(tuple(reversed(observations)))


def test_commit_writes_immutable_definition(tmp_path):
    inputs = {"c1": {"case_sha256": "sha", "case_path": "/cases/c1"}}
    experiment, reused = commit_proposal(proposal(), root=tmp_path, case_inputs=inputs)
    assert reused is False
    assert (tmp_path / experiment.eid / "definition.json").exists()
    data = json.loads((tmp_path / experiment.eid / "definition.json").read_text(encoding="utf-8"))
    assert data["cells"][0]["cell_id"] == experiment.cells[0].cell_id
    again, reused_again = commit_proposal(proposal(), root=tmp_path, case_inputs=inputs)
    assert reused_again is True
    assert again.eid == experiment.eid


def test_different_wording_creates_independent_experiment(tmp_path):
    """★ 回归（2026-09-28 张老师裁决）：**每个提案 = 一个独立实验配置**。

    同一执行定义（算例/因子/步骤相同）+ 不同标题/研究措辞 → **两个独立实验**
    （不同 eid、各自目录、各自 Observation Store）—— 可独立运行、导出、分析。
    （旧口径「eid 只由执行定义派生 → 措辞不同也折叠成同一实验」已按裁决废弃：
      用户视角里提案就是实验，全部折叠到一个实验上 = 「提案不独立、无法正确分析」。）

    历史包袱注：F-V2-4 修的是「同执行定义下任何新提案 commit 必然 400」的死路 ——
    那个问题现在以更彻底的方式消失：不同提案根本不会再撞同一个 eid。
    """
    inputs = {"c1": {"case_sha256": "sha", "case_path": "/cases/c1"}}
    first, reused_first = commit_proposal(proposal(), root=tmp_path, case_inputs=inputs)
    assert reused_first is False

    other = proposal(
        proposal_id="p2",
        title="完全不同的标题",
        research_question={"id": "rq9", "statement": "另一个研究问题？"},
        hypothesis={"id": "h9", "statement": "另一个假设。"},
    )
    second, reused = commit_proposal(other, root=tmp_path, case_inputs=inputs)
    assert reused is False
    assert second.eid != first.eid, "不同提案必须是不同实验（即使执行定义相同）"
    assert second.title == other.title, "新实验携带本提案自己的标题（不覆盖、也不被覆盖）"
    assert (tmp_path / second.eid / "definition.json").is_file()
    assert (tmp_path / first.eid / "definition.json").is_file(), "原实验不受影响"


def test_tampered_definition_is_rejected(tmp_path):
    """同 eid 但**执行内容被篡改** → 必须拒绝（不可变性的最后一道闸）。

    正常路径下 eid 由执行定义派生，改了算例/因子/步骤会得到**新 eid**（互不冲突）；
    本测试模拟 `definition.json` 被手工编辑，验证"同 eid ⇒ 同执行定义"这一不变式真的被守住。
    """
    inputs = {"c1": {"case_sha256": "sha", "case_path": "/cases/c1"}}
    first, _ = commit_proposal(proposal(), root=tmp_path, case_inputs=inputs)
    definition = tmp_path / first.eid / "definition.json"
    data = json.loads(definition.read_text(encoding="utf-8"))
    data["execution"]["steps"] = [{"server": "x", "tool": "y", "args_template": {}}]
    definition.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ProposalValidationError, match="执行定义冲突"):
        commit_proposal(proposal(), root=tmp_path, case_inputs=inputs)
