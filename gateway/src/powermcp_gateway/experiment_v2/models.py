"""PowerMCP 实验 V2 的不可变领域模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, set):
        return frozenset(_freeze(v) for v in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, frozenset)):
        return [_thaw(v) for v in value]
    return value


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    return tuple(value) if isinstance(value, (list, tuple)) else (value,)


@dataclass(frozen=True)
class ResearchQuestion:
    id: str
    statement: str
    scope: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope", _freeze(self.scope))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ResearchQuestion":
        data = data or {}
        return cls(str(data.get("id", "")), str(data.get("statement", "")), data.get("scope", {}))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "statement": self.statement, "scope": _thaw(self.scope)}


@dataclass(frozen=True)
class Hypothesis:
    id: str
    statement: str
    independent_variables: tuple[str, ...] = ()
    dependent_variables: tuple[str, ...] = ()
    controls: tuple[str, ...] = ()
    expected_direction: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "independent_variables", tuple(self.independent_variables))
        object.__setattr__(self, "dependent_variables", tuple(self.dependent_variables))
        object.__setattr__(self, "controls", tuple(self.controls))
        object.__setattr__(self, "expected_direction", _freeze(self.expected_direction))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "Hypothesis":
        data = data or {}
        return cls(str(data.get("id", "")), str(data.get("statement", "")),
                   tuple(data.get("independent_variables", ()) or ()),
                   tuple(data.get("dependent_variables", ()) or ()),
                   tuple(data.get("controls", ()) or ()), data.get("expected_direction", {}))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "statement": self.statement,
                "independent_variables": list(self.independent_variables),
                "dependent_variables": list(self.dependent_variables),
                "controls": list(self.controls),
                "expected_direction": _thaw(self.expected_direction)}


@dataclass(frozen=True)
class CaseRef:
    case_id: str
    case_sha256: str = ""
    case_path: str = ""

    @classmethod
    def from_value(cls, value: Any) -> "CaseRef":
        if isinstance(value, str):
            return cls(value)
        if isinstance(value, Mapping):
            return cls(str(value.get("case_id", value.get("id", ""))),
                       str(value.get("case_sha256", value.get("sha256", ""))),
                       str(value.get("case_path", value.get("path", value.get("source_path", "")))))
        return cls("")

    def to_dict(self) -> dict[str, str]:
        return {"case_id": self.case_id, "case_sha256": self.case_sha256, "case_path": self.case_path}


@dataclass(frozen=True)
class FactorSpec:
    name: str
    type: str = "string"
    values: tuple[Any, ...] = ()
    generator: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", tuple(self.values))
        object.__setattr__(self, "generator", _freeze(self.generator))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FactorSpec":
        return cls(str(data.get("name", "")), str(data.get("type", data.get("kind", "string"))),
                   tuple(data.get("values", ()) or ()), data.get("generator", {}))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"name": self.name, "type": self.type, "values": _thaw(self.values)}
        if self.generator:
            result["generator"] = _thaw(self.generator)
        return result


@dataclass(frozen=True)
class Design:
    cases: tuple[CaseRef, ...] = ()
    factors: tuple[FactorSpec, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "cases", tuple(c if isinstance(c, CaseRef) else CaseRef.from_value(c) for c in self.cases))
        object.__setattr__(self, "factors", tuple(f if isinstance(f, FactorSpec) else FactorSpec.from_dict(f) for f in self.factors))

    @classmethod
    def from_value(cls, value: Any) -> "Design":
        if isinstance(value, cls):
            return value
        value = value or {}
        return cls(tuple(value.get("cases", ()) or ()), tuple(value.get("factors", ()) or ()))

    def to_dict(self) -> dict[str, Any]:
        return {"cases": [c.to_dict() for c in self.cases], "factors": [f.to_dict() for f in self.factors]}


@dataclass(frozen=True)
class ExperimentProposal:
    proposal_id: str
    title: str
    research_question: ResearchQuestion
    hypothesis: Hypothesis
    design: Design
    execution: Mapping[str, Any] = field(default_factory=dict)
    observables: Mapping[str, Any] | tuple[str, ...] = field(default_factory=dict)
    analysis: Mapping[str, Any] = field(default_factory=dict)
    origin: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "research_question", self.research_question if isinstance(self.research_question, ResearchQuestion) else ResearchQuestion.from_dict(self.research_question))
        object.__setattr__(self, "hypothesis", self.hypothesis if isinstance(self.hypothesis, Hypothesis) else Hypothesis.from_dict(self.hypothesis))
        object.__setattr__(self, "design", Design.from_value(self.design))
        object.__setattr__(self, "execution", _freeze(self.execution))
        object.__setattr__(self, "observables", _freeze(self.observables))
        object.__setattr__(self, "analysis", _freeze(self.analysis))
        object.__setattr__(self, "origin", _freeze(self.origin))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExperimentProposal":
        return cls(str(data.get("proposal_id", "")), str(data.get("title", "")),
                   ResearchQuestion.from_dict(data.get("research_question")),
                   Hypothesis.from_dict(data.get("hypothesis")), Design.from_value(data.get("design")),
                   data.get("execution", {}), data.get("observables", {}), data.get("analysis", {}), data.get("origin", {}))

    def to_dict(self) -> dict[str, Any]:
        return {"proposal_id": self.proposal_id, "title": self.title,
                "research_question": self.research_question.to_dict(),
                "hypothesis": self.hypothesis.to_dict(), "design": self.design.to_dict(),
                "execution": _thaw(self.execution), "observables": _thaw(self.observables),
                "analysis": _thaw(self.analysis), "origin": _thaw(self.origin)}


@dataclass(frozen=True)
class Cell:
    cell_id: str
    eid: str
    bindings: Mapping[str, Any]
    steps: tuple[Mapping[str, Any], ...]
    case_id: str
    case_sha256: str
    case_path: str
    cache_key: str
    status: str = "pending"

    def __post_init__(self) -> None:
        object.__setattr__(self, "bindings", _freeze(self.bindings))
        object.__setattr__(self, "steps", tuple(_freeze(s) for s in self.steps))

    def to_dict(self) -> dict[str, Any]:
        return {"cell_id": self.cell_id, "eid": self.eid, "bindings": _thaw(self.bindings),
                "steps": _thaw(self.steps), "case_id": self.case_id, "case_sha256": self.case_sha256,
                "case_path": self.case_path, "cache_key": self.cache_key, "status": self.status}


@dataclass(frozen=True)
class Experiment:
    schema_version: str
    eid: str
    title: str
    research: Mapping[str, Any]
    design: Design
    execution: Mapping[str, Any]
    observables: Mapping[str, Any] | tuple[str, ...]
    analysis: Mapping[str, Any]
    provenance: Mapping[str, Any]
    cells: tuple[Cell, ...]
    resource_estimate: Mapping[str, Any] = field(default_factory=dict)
    status: str = "registered"

    def __post_init__(self) -> None:
        object.__setattr__(self, "research", _freeze(self.research))
        object.__setattr__(self, "design", Design.from_value(self.design))
        object.__setattr__(self, "execution", _freeze(self.execution))
        object.__setattr__(self, "observables", _freeze(self.observables))
        object.__setattr__(self, "analysis", _freeze(self.analysis))
        object.__setattr__(self, "provenance", _freeze(self.provenance))
        object.__setattr__(self, "cells", tuple(self.cells))
        object.__setattr__(self, "resource_estimate", _freeze(self.resource_estimate))

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "eid": self.eid, "title": self.title,
                "research": _thaw(self.research), "design": self.design.to_dict(),
                "execution": _thaw(self.execution), "observables": _thaw(self.observables),
                "analysis": _thaw(self.analysis), "provenance": _thaw(self.provenance),
                "cells": [c.to_dict() for c in self.cells], "resource_estimate": _thaw(self.resource_estimate),
                "status": self.status}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Experiment":
        return cls(str(data.get("schema_version", "2.0")), str(data.get("eid", "")), str(data.get("title", "")),
                   data.get("research", {}), Design.from_value(data.get("design")), data.get("execution", {}),
                   data.get("observables", {}), data.get("analysis", {}), data.get("provenance", {}),
                   tuple(Cell(**_cell_kwargs(c)) for c in data.get("cells", ()) or ()),
                   data.get("resource_estimate", {}), str(data.get("status", "registered")))


def _cell_kwargs(data: Mapping[str, Any]) -> dict[str, Any]:
    return {"cell_id": str(data.get("cell_id", "")), "eid": str(data.get("eid", "")),
            "bindings": data.get("bindings", {}), "steps": tuple(data.get("steps", ()) or ()),
            "case_id": str(data.get("case_id", "")), "case_sha256": str(data.get("case_sha256", "")),
            "case_path": str(data.get("case_path", "")), "cache_key": str(data.get("cache_key", "")),
            "status": str(data.get("status", "pending"))}


ImmutableExperiment = Experiment


class ExperimentStatus(str, Enum):
    REGISTERED = "registered"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CellStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED_ENVIRONMENT = "failed_environment"
    FAILED_EXECUTION = "failed_execution"
    FAILED_VALIDATION = "failed_validation"
    NOT_CONVERGED = "not_converged"
    CANCELLED = "cancelled"


class ObservationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED_ENVIRONMENT = "failed_environment"
    FAILED_EXECUTION = "failed_execution"
    FAILED_VALIDATION = "failed_validation"
    NOT_CONVERGED = "not_converged"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    type: str
    sha256: str
    mime_type: str | None = None
    cell_id: str | None = None
    created_by: str | None = None
    size_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {"artifact_id": self.artifact_id, "type": self.type, "sha256": self.sha256}
        for key in ("mime_type", "cell_id", "created_by", "size_bytes"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        return result


@dataclass(frozen=True)
class Observation:
    observation_id: str
    cell_id: str
    inputs: Mapping[str, Any]
    execution: Mapping[str, Any]
    metrics: Mapping[str, Any] = field(default_factory=dict)
    diagnostics: Mapping[str, Any] = field(default_factory=dict)
    artifacts: tuple[Mapping[str, Any], ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", _freeze(self.inputs))
        object.__setattr__(self, "execution", _freeze(self.execution))
        object.__setattr__(self, "metrics", _freeze(self.metrics))
        object.__setattr__(self, "diagnostics", _freeze(self.diagnostics))
        object.__setattr__(self, "artifacts", tuple(_freeze(a) for a in self.artifacts))
        object.__setattr__(self, "provenance", _freeze(self.provenance))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Observation":
        return cls(str(data.get("observation_id", "")), str(data.get("cell_id", "")), data.get("inputs", {}),
                   data.get("execution", {}), data.get("metrics", {}), data.get("diagnostics", {}),
                   tuple(data.get("artifacts", ()) or ()), data.get("provenance", {}))

    def to_dict(self) -> dict[str, Any]:
        return {"observation_id": self.observation_id, "cell_id": self.cell_id,
                "inputs": _thaw(self.inputs), "execution": _thaw(self.execution),
                "metrics": _thaw(self.metrics), "diagnostics": _thaw(self.diagnostics),
                "artifacts": _thaw(self.artifacts), "provenance": _thaw(self.provenance)}


@dataclass(frozen=True)
class ResourceEstimate:
    cells: int
    steps_per_cell: int
    total_steps: int
    estimated_duration_s: float
    estimated_artifact_size: int
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"cells": self.cells, "steps_per_cell": self.steps_per_cell, "total_steps": self.total_steps,
                "estimated_duration_s": self.estimated_duration_s,
                "estimated_artifact_size": self.estimated_artifact_size, "warning": self.warning}
