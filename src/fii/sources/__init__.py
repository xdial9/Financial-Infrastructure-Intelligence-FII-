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
from fii.sources.ct_live import CTLiveCollector
from fii.sources.ct_logs import CTLogsFixtureCollector
from fii.sources.registry import SourceRegistry, get_default_registry
from fii.sources.web_surface import (
    PublicWebsiteSnapshotCollector,
    WebSurfaceFixtureCollector,
)

__all__ = [
    "CTLiveCollector",
    "CTLogsFixtureCollector",
    "CollectionContext",
    "CollectionResult",
    "EvidenceWriteError",
    "Observation",
    "RawEvidenceReference",
    "SourceCollectionError",
    "SourceDefinition",
    "SourceDiagnostic",
    "SourceRegistry",
    "PublicWebsiteSnapshotCollector",
    "WebSurfaceFixtureCollector",
    "get_default_registry",
    "run_collector",
]
