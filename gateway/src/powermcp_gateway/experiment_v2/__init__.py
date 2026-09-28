"""PowerMCP Agentic Research Experiment V2 内核。"""
from .analysis import analyze, deterministic_analysis
from .compiler import COMPILER_VERSION, commit_proposal, compile_experiment, compile_proposal
from .models import (
    Artifact, CaseRef, Cell, CellStatus, Design, Experiment, ExperimentProposal, ExperimentStatus,
    FactorSpec, Hypothesis, ImmutableExperiment, Observation, ObservationStatus, ResearchQuestion,
    ResourceEstimate,
)
from .resources import estimate_proposal, estimate_resources
from .stores import ObservationJSONLStore, ObservationStore, ProposalStore, StoreError
from .validator import ProposalValidationError, ValidationReport, validate, validate_or_raise, validate_proposal

__all__ = [
    "ResearchQuestion", "Hypothesis", "ExperimentProposal", "Experiment", "ImmutableExperiment",
    "Cell", "Observation", "Artifact", "CaseRef", "FactorSpec", "Design", "ResourceEstimate",
    "ExperimentStatus", "CellStatus", "ObservationStatus",
    "ValidationReport", "ProposalValidationError", "validate_proposal", "validate", "validate_or_raise",
    "compile_proposal", "compile_experiment", "commit_proposal", "COMPILER_VERSION",
    "estimate_resources", "estimate_proposal", "ProposalStore", "ObservationStore", "ObservationJSONLStore",
    "StoreError", "analyze", "deterministic_analysis",
]
