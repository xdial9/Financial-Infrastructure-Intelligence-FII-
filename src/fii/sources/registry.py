"""Explicit registry of built-in FII collectors.

The registry is intentionally fixed. Optional provider APIs and external tools
can implement the same contract in later blocks without dynamic code loading.
"""

from __future__ import annotations

from fii.sources.contracts import Collector, SourceDefinition
from fii.sources.ct_logs import CTLogsFixtureCollector
from fii.sources.web_surface import WebSurfaceFixtureCollector


class SourceRegistry:
    """Read-only lookup over explicitly supplied collector instances."""

    def __init__(self, collectors: tuple[Collector, ...]) -> None:
        mapping: dict[str, Collector] = {}
        for collector in collectors:
            source_id = collector.definition.source_id
            if source_id in mapping:
                raise ValueError(f"Duplicate collector source ID: {source_id}")
            mapping[source_id] = collector
        self._collectors = mapping

    def get(self, source_id: str) -> Collector:
        """Return a collector by stable ID."""
        try:
            return self._collectors[source_id]
        except KeyError as exc:
            raise KeyError(f"Unknown FII source ID: {source_id}") from exc

    def definitions(self) -> tuple[SourceDefinition, ...]:
        """Return definitions in deterministic source-ID order."""
        return tuple(
            self._collectors[source_id].definition
            for source_id in sorted(self._collectors)
        )

    def source_ids(self) -> tuple[str, ...]:
        """Return stable IDs in deterministic order."""
        return tuple(sorted(self._collectors))


def get_default_registry() -> SourceRegistry:
    """Build the fixed first-release registry without network or tool side effects."""
    return SourceRegistry((CTLogsFixtureCollector(), WebSurfaceFixtureCollector()))
