"""把实验提案编译成静态、可复现的 V2 Experiment。"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from powermcp_gateway.experiments import Experiment as V1Experiment
from powermcp_gateway.experiments import Factor as V1Factor
from powermcp_gateway.experiments import Step as V1Step
from powermcp_gateway.experiments import cell_cache_key, expand as expand_v1

from .models import Cell, Design, Experiment, ExperimentProposal, FactorSpec, ResourceEstimate
from .resources import estimate_resources
from .validator import ProposalValidationError, validate_proposal

COMPILER_VERSION = "experiment-v2-1"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _factor_values(factor: FactorSpec) -> tuple[Any, ...]:
    if factor.values:
        return factor.values
    generator = dict(factor.generator)
    kind = generator.get("type", generator.get("kind", ""))
    if kind != "linear_range":
        raise ProposalValidationError(f"因子 {factor.name!r} 使用了不支持的生成器 {kind!r}")
    start, stop = generator.get("start"), generator.get("stop")
    step = generator.get("step", 1)
    if not isinstance(start, (int, float)) or not isinstance(stop, (int, float)) or not isinstance(step, (int, float)) or step == 0:
        raise ProposalValidationError(f"因子 {factor.name!r} 的 linear_range 参数无效")
    values: list[Any] = []
    current = start
    if step > 0:
        while current <= stop:
            values.append(current)
            current += step
    else:
        while current >= stop:
            values.append(current)
            current += step
    return tuple(values)


def _step_dicts(proposal: ExperimentProposal) -> tuple[dict[str, Any], ...]:
    raw = proposal.execution
    if isinstance(raw, (list, tuple)):
        steps = raw
    else:
        steps = raw.get("steps", ()) if isinstance(raw, Mapping) else ()
    result: list[dict[str, Any]] = []
    for item in steps:
        if not isinstance(item, Mapping):
            raise ProposalValidationError("execution.steps 的每一项必须是对象")
        template = item.get("args_template", item.get("args", {}))
        if not isinstance(template, Mapping):
            raise ProposalValidationError("execution.steps[].args_template 必须是对象")
        result.append({"server": str(item.get("server", "")), "tool": str(item.get("tool", "")),
                       "args_template": dict(template)})
    return tuple(result)


def _case_inputs(design: Design, case_inputs: Mapping[str, Any] | None) -> tuple[dict[str, str], dict[str, str]]:
    sha_by_case: dict[str, str] = {}
    path_by_case: dict[str, str] = {}
    supplied = case_inputs or {}
    for case in design.cases:
        extra = supplied.get(case.case_id, {}) if isinstance(supplied, Mapping) else {}
        if isinstance(extra, str):
            extra = {"case_path": extra}
        sha_by_case[case.case_id] = case.case_sha256 or str(extra.get("case_sha256", extra.get("sha256", "")))
        path_by_case[case.case_id] = case.case_path or str(extra.get("case_path", extra.get("path", "")))
    return sha_by_case, path_by_case


def _eid(proposal: ExperimentProposal, steps: tuple[dict[str, Any], ...], design: Design,
         sha_by_case: Mapping[str, str], path_by_case: Mapping[str, str], compiler_version: str) -> str:
    # ★ 实验身份 = 提案身份 + 执行定义（2026-09-28 张老师裁决，修订原 spec §10.2 口径）：
    #   **每个提案是一个独立的实验配置** —— 即使执行定义（算例/因子/步骤）与另一提案完全相同，
    #   也各自得到独立实验，可独立运行、导出结果、独立分析。
    #   同一提案重复 commit → 同一 eid（幂等，复用不重跑）。
    payload = {"proposal_id": proposal.proposal_id,
               "cases": [{"id": c.case_id, "sha256": sha_by_case[c.case_id], "path": path_by_case[c.case_id]} for c in design.cases],
               "factors": [{"name": f.name, "type": f.type, "values": list(_factor_values(f))} for f in design.factors],
               "steps": list(steps), "compiler_version": compiler_version}
    return "exp-" + hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:16]


def compile_proposal(proposal: ExperimentProposal | Mapping[str, Any], *,
                     case_inputs: Mapping[str, Any] | None = None,
                     compiler_version: str = COMPILER_VERSION,
                     eid: str | None = None,
                     max_cells: int = 2000) -> Experiment:
    """纯编译函数：所有 case sha/path、factor 值和 rendered steps 在返回前固定。"""
    if not isinstance(proposal, ExperimentProposal):
        proposal = ExperimentProposal.from_dict(proposal)
    report = validate_proposal(proposal, max_cells=max_cells, require_case_identity=False)
    if not report.valid:
        raise ProposalValidationError("；".join(report.errors))
    design = proposal.design
    steps = _step_dicts(proposal)
    sha_by_case, path_by_case = _case_inputs(design, case_inputs)
    missing = [c.case_id for c in design.cases if not sha_by_case[c.case_id] or not path_by_case[c.case_id]]
    if missing:
        raise ProposalValidationError(f"提交编译必须固定 case_sha256 和 case_path：缺少 {missing}")
    factors = tuple(V1Factor(f.name, _factor_values(f)) for f in design.factors)
    v1 = V1Experiment(id="", label=proposal.title, created_at="", case_ids=tuple(c.case_id for c in design.cases),
                      factors=factors, steps=tuple(V1Step(s["server"], s["tool"], s["args_template"]) for s in steps))
    compiled_eid = eid or _eid(proposal, steps, design, sha_by_case, path_by_case, compiler_version)
    raw_cells = expand_v1(v1, sha_by_case=sha_by_case, path_by_case=path_by_case)
    cells: list[Cell] = []
    for index, raw in enumerate(raw_cells):
        # cache_key 来自现有确定性实现；cell_id 同时携带 index 与执行身份摘要。
        cell_id = f"cell-{index:04d}-{raw.cache_key[:12]}"
        cells.append(Cell(cell_id=cell_id, eid=compiled_eid, bindings=raw.bindings,
                         steps=raw.steps, case_id=raw.case_id, case_sha256=raw.case_sha256,
                         case_path=path_by_case[raw.case_id], cache_key=raw.cache_key))
    resource = estimate_resources(len(cells), len(steps))
    research = {"question": proposal.research_question.to_dict(), "hypothesis": proposal.hypothesis.to_dict()}
    execution = {"steps": [{"server": s["server"], "tool": s["tool"], "args_template": s["args_template"]} for s in steps],
                 "compiled": True, "compiler_version": compiler_version}
    provenance = {"proposal_id": proposal.proposal_id, "source_session_id": proposal.origin.get("session_id") if isinstance(proposal.origin, Mapping) else None,
                  "compiler_version": compiler_version}
    return Experiment(schema_version="2.0", eid=compiled_eid, title=proposal.title, research=research,
                      design=Design(tuple(type(c)(c.case_id, sha_by_case[c.case_id], path_by_case[c.case_id]) for c in design.cases),
                                    tuple(FactorSpec(f.name, f.type, _factor_values(f), f.generator) for f in design.factors)),
                      execution=execution, observables=proposal.observables, analysis=proposal.analysis,
                      provenance=provenance, cells=tuple(cells), resource_estimate=resource.to_dict())


def _execution_identity(exp: Experiment) -> dict[str, Any]:
    """不可变性的比对基准（与 `definition.json` 的执行内容一致）。

    ★ `eid` 已含提案身份（2026-09-28 裁决）：不同提案必然不同 eid，正常路径下
      「同 eid」只可能是同一提案重复 commit（或 `definition.json` 被手工编辑）。
      本函数守住最后一道闸：**同 eid 但执行内容不同 ⇒ 拒绝**（篡改检测），
      而不是像 F-V2-4 之前那样拿整个 definition 比较导致新提案必然 400 死路。
    """
    data = exp.to_dict()
    return {
        "eid": exp.eid,
        "cases": data["design"]["cases"],
        "factors": data["design"]["factors"],
        "execution": data["execution"],
        "cells": [
            {
                "cell_id": cell.cell_id,
                "cache_key": cell.cache_key,
                "case_id": cell.case_id,
                "case_sha256": cell.case_sha256,
                "case_path": cell.case_path,
                "bindings": cell.to_dict()["bindings"],
                "steps": cell.to_dict()["steps"],
            }
            for cell in exp.cells
        ],
    }


def commit_proposal(proposal: ExperimentProposal | Mapping[str, Any], *, root: str | Any,
                    case_inputs: Mapping[str, Any] | None = None,
                    compiler_version: str = COMPILER_VERSION,
                    max_cells: int = 2000) -> tuple[Experiment, bool]:
    """编译并落盘；`definition.json` 存完整 cells，**已存在定义不可被覆盖**。

    Returns:
        `(experiment, reused)` —— `reused=True` 表示**同一提案**重复 commit（同一 eid），
        直接复用已冻结的定义与已有 Observation，不必重跑。
        不同提案（即使执行定义相同）→ 不同 eid → **各自独立的实验**
        （2026-09-28 张老师裁决：每个提案是一个独立的实验配置，可独立运行、导出、分析）。
    """
    from pathlib import Path
    root_path = Path(root)
    if not isinstance(proposal, ExperimentProposal):
        proposal = ExperimentProposal.from_dict(proposal)
    experiment = compile_proposal(proposal, case_inputs=case_inputs, compiler_version=compiler_version, max_cells=max_cells)
    exp_dir = root_path / experiment.eid
    definition = exp_dir / "definition.json"
    if definition.exists():
        existing = Experiment.from_dict(json.loads(definition.read_text(encoding="utf-8")))
        if _execution_identity(existing) != _execution_identity(experiment):
            raise ProposalValidationError(
                f"执行定义冲突：eid={experiment.eid} 已存在，且**执行内容不同**（算例/因子/步骤不一致）—— 拒绝覆盖。"
                "若要改设计，请改动算例、因子或步骤（会得到新的 eid）。"
            )
        return existing, True
    exp_dir.mkdir(parents=True, exist_ok=True)
    proposal_path = exp_dir / "proposal.json"
    manifest_path = exp_dir / "manifest.json"
    definition.write_text(_canonical(experiment.to_dict()), encoding="utf-8")
    proposal_path.write_text(_canonical(proposal.to_dict()), encoding="utf-8")
    manifest = {"schema_version": "2.0", "eid": experiment.eid, "compiler_version": compiler_version,
                "cell_count": len(experiment.cells), "resource_estimate": experiment.resource_estimate,
                "provenance": experiment.provenance}
    manifest_path.write_text(_canonical(manifest), encoding="utf-8")
    return experiment, False


# 便于调用方使用更短名称。
compile_experiment = compile_proposal
