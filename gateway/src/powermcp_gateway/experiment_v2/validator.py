"""ExperimentProposal 的结构、语义和执行可行性校验。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from powermcp_gateway.experiments import ExperimentError, render_args

from .models import ExperimentProposal, FactorSpec
from .resources import estimate_resources

_FACTOR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BUILTINS = {"case_path", "case_id"}


class ProposalValidationError(ValueError):
    """提案或编译定义不满足 V2 合同。"""


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    resource_estimate: Mapping[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.valid

    def __iter__(self):
        return iter(self.errors)

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "errors": list(self.errors), "warnings": list(self.warnings),
                "resource_estimate": dict(self.resource_estimate)}


def _steps(proposal: ExperimentProposal) -> tuple[Any, ...]:
    execution = proposal.execution
    if isinstance(execution, (list, tuple)):
        return tuple(execution)
    return tuple(execution.get("steps", ()) or ()) if isinstance(execution, Mapping) else ()


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) and not isinstance(value, type(None))


def _factor_values(factor: FactorSpec) -> tuple[Any, ...]:
    if factor.values:
        return factor.values
    generator = dict(factor.generator)
    kind = generator.get("type", generator.get("kind", ""))
    if kind == "linear_range":
        start, stop, step = generator.get("start"), generator.get("stop"), generator.get("step", 1)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (start, stop, step)) or step == 0:
            return ()
        n = int(abs((stop - start) / step)) + 1
        return tuple(start + i * step for i in range(max(0, n)) if (step > 0 and start + i * step <= stop) or (step < 0 and start + i * step >= stop))
    return ()


def validate_proposal(proposal: ExperimentProposal | Mapping[str, Any], *,
                      known_servers: Iterable[str] | None = None,
                      known_tools: Mapping[str, Iterable[str]] | Iterable[str] | None = None,
                      max_cells: int = 2000,
                      resource_limits: Mapping[str, float] | None = None,
                      require_case_identity: bool = False) -> ValidationReport:
    if not isinstance(proposal, ExperimentProposal):
        proposal = ExperimentProposal.from_dict(proposal)
    errors: list[str] = []
    warnings: list[str] = []
    known_server_set = {str(s).lower() for s in known_servers} if known_servers is not None else None
    cases = proposal.design.cases
    factors = proposal.design.factors
    if not proposal.proposal_id.strip():
        errors.append("proposal_id 必须是非空字符串")
    if not proposal.title.strip():
        errors.append("title 必须是非空字符串")
    # 提案可以携带完整对象，也可以携带已登记研究对象的 id 引用。
    if not proposal.research_question.id:
        errors.append("research_question 必须包含 id")
    if not proposal.hypothesis.id:
        errors.append("hypothesis 必须包含 id")
    if not cases:
        errors.append("design.cases 必须是非空数组")
    seen_cases: set[str] = set()
    for case in cases:
        if not case.case_id:
            errors.append("case_id 必须是非空字符串")
        if case.case_id in seen_cases:
            errors.append(f"case_id 重复：{case.case_id}")
        seen_cases.add(case.case_id)
        if require_case_identity and (not case.case_sha256 or not case.case_path):
            errors.append(f"case {case.case_id!r} 缺少固定 case_sha256/case_path")
    seen_factors: set[str] = set()
    cardinality = len(cases)
    for factor in factors:
        if not _FACTOR_RE.match(factor.name) or factor.name in _BUILTINS:
            errors.append(f"因子名无效或覆盖内置占位符：{factor.name!r}")
        if factor.name in seen_factors:
            errors.append(f"因子名重复：{factor.name}")
        seen_factors.add(factor.name)
        values = _factor_values(factor)
        if not values:
            errors.append(f"因子 {factor.name!r} 必须有非空 values 或受支持的 linear_range generator")
        if any(not _is_scalar(v) for v in values):
            errors.append(f"因子 {factor.name!r} 的值只能是 JSON 标量")
        try:
            if len(set(map(repr, values))) != len(values):
                errors.append(f"因子 {factor.name!r} 含重复取值")
        except TypeError:
            errors.append(f"因子 {factor.name!r} 含不可比较取值")
        cardinality *= len(values)
        if factor.generator and not values and dict(factor.generator).get("type", dict(factor.generator).get("kind")) not in {"linear_range"}:
            errors.append(f"因子 {factor.name!r} 使用了不支持的生成器")
    if cardinality == 0:
        errors.append("网格展开为 0 格")
    if cardinality > max_cells:
        errors.append(f"网格展开为 {cardinality} 格，超过上限 {max_cells}")
    steps = _steps(proposal)
    if not steps:
        errors.append("execution.steps 必须是非空数组")
    servers_in_steps: set[str] = set()
    factor_bindings = {f.name: (_factor_values(f)[0] if _factor_values(f) else None) for f in factors}
    for index, step in enumerate(steps):
        if not isinstance(step, Mapping):
            errors.append(f"execution.steps[{index}] 必须是对象")
            continue
        server = str(step.get("server", "")).strip().lower()
        tool = str(step.get("tool", "")).strip()
        if not server:
            errors.append(f"execution.steps[{index}].server 必填")
        else:
            servers_in_steps.add(server)
            if known_server_set is not None and server not in known_server_set:
                errors.append(f"未知 server：{server}")
        if not tool:
            errors.append(f"execution.steps[{index}].tool 必填")
        if known_tools is not None and tool:
            allowed = known_tools.get(server, ()) if isinstance(known_tools, Mapping) else known_tools
            if tool not in set(allowed):
                errors.append(f"未知工具：{server}.{tool}")
        template = step.get("args_template", step.get("args", {}))
        if not isinstance(template, Mapping):
            errors.append(f"execution.steps[{index}].args_template 必须是对象")
            continue
        try:
            render_args(dict(template), factor_bindings, case_path="/fixed/case", case_id="case")
        except ExperimentError as exc:
            errors.append(str(exc))
    if len(servers_in_steps) > 1:
        errors.append("一个实验的 execution.steps 必须使用同一个 server")
    estimate = estimate_resources(cardinality, len(steps))
    limits = resource_limits or {}
    if "cells" in limits and cardinality > limits["cells"]:
        errors.append(f"cell_count {cardinality} 超出资源限制 {limits['cells']}")
    if "estimated_duration_s" in limits and estimate.estimated_duration_s > limits["estimated_duration_s"]:
        errors.append("估算执行时间超出资源限制")
    if cardinality >= 100:
        warnings.append("large experiment：提交前需要显式确认")
    return ValidationReport(not errors, tuple(errors), tuple(warnings), estimate.to_dict())


def validate_or_raise(proposal: ExperimentProposal | Mapping[str, Any], **kwargs: Any) -> ValidationReport:
    report = validate_proposal(proposal, **kwargs)
    if not report.valid:
        raise ProposalValidationError("；".join(report.errors))
    return report


validate = validate_proposal
