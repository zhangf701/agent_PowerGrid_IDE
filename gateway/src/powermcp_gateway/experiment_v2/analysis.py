"""不依赖 LLM 的确定性实验分析。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from .models import Experiment, Observation


def _obs(value: Observation | Mapping[str, Any]) -> Observation:
    return value if isinstance(value, Observation) else Observation.from_dict(value)


def _metric_numbers(observation: Observation) -> dict[str, float | int]:
    return {str(k): v for k, v in observation.metrics.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def _status(observation: Observation) -> str:
    return str(observation.execution.get("status", "unknown"))


def summary(observations: Iterable[Observation | Mapping[str, Any]], *, total_cells: int | None = None) -> dict[str, Any]:
    values = [_obs(o) for o in observations]
    by_status: dict[str, int] = {}
    for observation in values:
        key = _status(observation)
        by_status[key] = by_status.get(key, 0) + 1
    result: dict[str, Any] = {"observations": len(values), "by_status": dict(sorted(by_status.items()))}
    result["total_cells"] = total_cells if total_cells is not None else len(values)
    result["completed"] = by_status.get("completed", 0)
    for status in ("failed_environment", "failed_execution", "failed_validation", "not_converged", "cancelled"):
        result[status] = by_status.get(status, 0)
    return result


def extreme_cases(observations: Iterable[Observation | Mapping[str, Any]]) -> list[dict[str, Any]]:
    values = [_obs(o) for o in observations]
    metric_values: dict[str, list[tuple[str, float | int]]] = defaultdict(list)
    for observation in values:
        for name, value in _metric_numbers(observation).items():
            metric_values[name].append((observation.cell_id, value))
    result: list[dict[str, Any]] = []
    for metric in sorted(metric_values):
        entries = metric_values[metric]
        for direction, chosen in (("max", max(entries, key=lambda x: (x[1], x[0]))), ("min", min(entries, key=lambda x: (x[1], x[0])))):
            result.append({"metric": metric, "direction": direction, "cell_id": chosen[0], "value": chosen[1]})
    return result


def boundary_cases(observations: Iterable[Observation | Mapping[str, Any]]) -> list[dict[str, Any]]:
    values = [_obs(o) for o in observations]
    factor_names = sorted({key for observation in values for key, value in observation.inputs.items()
                           if key != "case_id" and isinstance(value, (int, float)) and not isinstance(value, bool)})
    result: list[dict[str, Any]] = []
    for factor in factor_names:
        ordered = sorted((o for o in values if isinstance(o.inputs.get(factor), (int, float)) and not isinstance(o.inputs.get(factor), bool)),
                         key=lambda o: (o.inputs[factor], o.cell_id))
        for before, after in zip(ordered, ordered[1:]):
            before_status, after_status = _status(before), _status(after)
            before_over = any(isinstance(v, (int, float)) and v > 100 for v in before.metrics.values())
            after_over = any(isinstance(v, (int, float)) and v > 100 for v in after.metrics.values())
            if before_status != after_status or before_over != after_over:
                result.append({"factor": factor, "transition": {
                    "from": {factor: before.inputs[factor], "status": before_status, "cell_id": before.cell_id},
                    "to": {factor: after.inputs[factor], "status": after_status, "cell_id": after.cell_id},
                }})
    return result


def factor_comparisons(observations: Iterable[Observation | Mapping[str, Any]]) -> list[dict[str, Any]]:
    values = [_obs(o) for o in observations]
    factors = sorted({key for observation in values for key in observation.inputs if key != "case_id"})
    result: list[dict[str, Any]] = []
    for factor in factors:
        groups: dict[str, list[Observation]] = defaultdict(list)
        raw_values: dict[str, Any] = {}
        for observation in values:
            if factor in observation.inputs:
                key = repr(observation.inputs[factor])
                groups[key].append(observation)
                raw_values[key] = observation.inputs[factor]
        for key in sorted(groups):
            group = groups[key]
            metrics: dict[str, dict[str, Any]] = {}
            names = sorted({name for observation in group for name in _metric_numbers(observation)})
            for name in names:
                nums = [_metric_numbers(o)[name] for o in group if name in _metric_numbers(o)]
                metrics[name] = {"count": len(nums), "min": min(nums), "max": max(nums), "mean": sum(nums) / len(nums)}
            result.append({"factor": factor, "value": raw_values[key], "n": len(group), "metrics": metrics})
    return result


def failure_summary(observations: Iterable[Observation | Mapping[str, Any]]) -> dict[str, Any]:
    values = [_obs(o) for o in observations]
    failures = [o for o in values if _status(o) not in {"completed", "ok"}]
    by_status: dict[str, list[str]] = defaultdict(list)
    for observation in failures:
        by_status[_status(observation)].append(observation.cell_id)
    return {"total_failures": len(failures), "by_status": {k: sorted(v) for k, v in sorted(by_status.items())}}


def representative_cases(observations: Iterable[Observation | Mapping[str, Any]]) -> list[dict[str, Any]]:
    values = sorted((_obs(o) for o in observations), key=lambda o: o.cell_id)
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for observation in values:
        case_id = str(observation.inputs.get("case_id", ""))
        if case_id not in seen:
            seen.add(case_id)
            result.append({"case_id": case_id, "cell_id": observation.cell_id})
    return result


def observed_patterns(observations: Iterable[Observation | Mapping[str, Any]]) -> list[dict[str, Any]]:
    boundaries = boundary_cases(observations)
    patterns = []
    for boundary in boundaries:
        transition = boundary["transition"]
        patterns.append({"type": "threshold_transition", "factor": boundary["factor"],
                         "observed_range": [transition["from"][boundary["factor"]], transition["to"][boundary["factor"]]],
                         "support": {"n_cells": 2, "n_affected": 1}})
    return patterns


def analyze(observations: Iterable[Observation | Mapping[str, Any]], *, experiment: Experiment | None = None) -> dict[str, Any]:
    values = tuple(_obs(o) for o in observations)
    return {"summary": summary(values, total_cells=len(experiment.cells) if experiment else None),
            "extreme_cases": extreme_cases(values), "boundary_cases": boundary_cases(values),
            "representative_cases": representative_cases(values), "observed_patterns": observed_patterns(values),
            "factor_comparisons": factor_comparisons(values), "failure_summary": failure_summary(values)}


deterministic_analysis = analyze
