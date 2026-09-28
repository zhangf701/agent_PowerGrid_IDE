"""实验提交前的确定性资源估算。"""
from __future__ import annotations

from .models import ResourceEstimate


def estimate_resources(cells: int | object, steps_per_cell: int | None = None, *,
                       duration_per_step_s: float = 4.0,
                       artifact_bytes_per_cell: int = 4096,
                       warning_threshold: int = 100,
                       reject_threshold: int | None = None) -> ResourceEstimate:
    if not isinstance(cells, int):
        proposal = cells
        from .validator import _factor_values, _steps
        count = len(proposal.design.cases)
        for factor in proposal.design.factors:
            count *= len(_factor_values(factor))
        cells = count
        steps_per_cell = len(_steps(proposal)) if steps_per_cell is None else steps_per_cell
    if steps_per_cell is None:
        raise ValueError("steps_per_cell 必填")
    if cells < 0 or steps_per_cell < 0:
        raise ValueError("cells 和 steps_per_cell 不能为负数")
    total_steps = cells * steps_per_cell
    duration = float(total_steps) * float(duration_per_step_s)
    artifact_size = cells * int(artifact_bytes_per_cell)
    warning: str | None = None
    if reject_threshold is not None and cells > reject_threshold:
        warning = f"experiment exceeds rejection threshold ({reject_threshold} cells)"
    elif cells > 1000:
        warning = "very large experiment"
    elif cells >= warning_threshold:
        warning = "large experiment"
    return ResourceEstimate(cells, steps_per_cell, total_steps, duration, artifact_size, warning)


def estimate_proposal(proposal, **kwargs):
    from .validator import _steps, _factor_values
    count = len(proposal.design.cases)
    for factor in proposal.design.factors:
        count *= len(_factor_values(factor))
    return estimate_resources(count, len(_steps(proposal)), **kwargs)
