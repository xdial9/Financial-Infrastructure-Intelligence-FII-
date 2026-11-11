"""Passive/public-source collector contracts and built-in fixture adapters."""

from fii.sources.contracts import (
    CollectionContext,
    CollectionResult,
    EvidenceWriteError,
    Observation,
    RawEvidenceReference,
    SourceCollectionError,
    SourceDefinition,
    SourceDiagnostic,
    run_collector,
)
from fii.sources.registry import SourceRegistry, get_default_registry

__all__ = [
    "CollectionContext",
    "CollectionResult",
    "EvidenceWriteError",
    "Observation",
    "RawEvidenceReference",
    "SourceCollectionError",
    "SourceDefinition",
    "SourceDiagnostic",
    "SourceRegistry",
    "get_default_registry",
    "run_collector",
]
