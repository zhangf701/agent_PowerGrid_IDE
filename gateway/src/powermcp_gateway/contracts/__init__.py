from .model import (
    CONTRACT_NAMES,
    ContractFinding,
    ContractState,
    KnownState,
    ReportSummary,
    UnknownReason,
    summarize,
)

__all__ = [
    "CONTRACT_NAMES",
    "ContractFinding",
    "ContractState",
    "KnownState",
    "ReportSummary",
    "UnknownReason",
    "summarize",
]

from .namespacing import NamespacingEvaluator
from .registry import REGISTRY

REGISTRY.register(NamespacingEvaluator())

__all__ += ["REGISTRY", "NamespacingEvaluator"]

from .doc_impl import DocImplEvaluator

REGISTRY.register(DocImplEvaluator())
__all__ += ["DocImplEvaluator"]

from .conventions import DimensionsEvaluator, IdentifiersEvaluator, load_conventions

REGISTRY.register(IdentifiersEvaluator())
REGISTRY.register(DimensionsEvaluator())
__all__ += ["DimensionsEvaluator", "IdentifiersEvaluator", "load_conventions"]

from .api_version import ApiVersionEvaluator

REGISTRY.register(ApiVersionEvaluator())
__all__ += ["ApiVersionEvaluator"]
