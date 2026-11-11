"""Stable, sequential collector contracts shared by built-in and future adapters."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

SourceStatus = Literal["success", "partial", "failed", "skipped"]
DiagnosticSeverity = Literal["info", "warning", "error"]
SourceClass = Literal[
    "public_api",
    "public_dataset",
    "targeted_public_web",
    "customer_supplied",
    "external_tool",
]
IntegrationKind = Literal["builtin", "provider_api", "external_tool"]

_SOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp with a stable textual representation."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class SourceDefinition:
    """Stable metadata for a fixed, versioned collector adapter."""

    source_id: str
    name: str
    adapter_version: str
    source_class: SourceClass
    description: str
    documentation_url: str | None = None
    terms_url: str | None = None
    requires_credentials: bool = False
    default_enabled: bool = False
    integration_kind: IntegrationKind = "builtin"
    supported_observation_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _SOURCE_ID_RE.fullmatch(self.source_id):
            raise ValueError(f"Invalid stable source ID: {self.source_id!r}")
        if not self.name.strip() or not self.adapter_version.strip():
            raise ValueError("Source name and adapter version are required.")
        if self.integration_kind not in {"builtin", "provider_api", "external_tool"}:
            raise ValueError("Unsupported source integration kind.")


@dataclass(frozen=True)
class CollectionContext:
    """Explicit inputs supplied by the runner to one source execution."""

    run_id: str
    raw_directory: Path
    fixture_path: Path | None = None
    approved_domains: tuple[str, ...] = ()
    source_url: str | None = None
    collected_at: str = field(default_factory=utc_now)
    max_fixture_bytes: int = 5 * 1024 * 1024

    def __post_init__(self) -> None:
        try:
            parsed = uuid.UUID(self.run_id)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Collection context requires a UUID run_id.") from exc
        if str(parsed) != self.run_id.lower():
            raise ValueError("Collection run_id must use canonical UUID form.")
        if self.max_fixture_bytes < 1:
            raise ValueError("max_fixture_bytes must be greater than zero.")


@dataclass(frozen=True)
class RawEvidenceReference:
    """Reference to immutable raw or explicitly redacted source bytes."""

    relative_path: str
    sha256: str
    original_sha256: str
    size_bytes: int
    media_type: str
    redactions_applied: int = 0

    def __post_init__(self) -> None:
        if not _SHA256_RE.fullmatch(self.sha256):
            raise ValueError("Raw evidence SHA-256 must be lowercase hexadecimal.")
        if not _SHA256_RE.fullmatch(self.original_sha256):
            raise ValueError("Original evidence SHA-256 must be lowercase hexadecimal.")
        if self.size_bytes < 0 or self.redactions_applied < 0:
            raise ValueError("Evidence size and redaction count cannot be negative.")


@dataclass(frozen=True)
class Observation:
    """An atomic fact emitted by a collector, not an inferred relationship."""

    observation_type: str
    observed_value: str
    collected_at: str
    source_url: str | None
    raw_sha256: str
    verification_state: Literal["observed", "unverified"] = "observed"
    observed_at: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.observation_type.strip() or not self.observed_value.strip():
            raise ValueError("Observation type and value are required.")
        if not _SHA256_RE.fullmatch(self.raw_sha256):
            raise ValueError("Observation must reference a valid raw evidence SHA-256.")


@dataclass(frozen=True)
class SourceDiagnostic:
    """Sanitized, machine-readable source warning or failure detail."""

    code: str
    message: str
    severity: DiagnosticSeverity = "warning"


@dataclass(frozen=True)
class CollectionResult:
    """Structured outcome for one sequential source execution."""

    source_id: str
    status: SourceStatus
    started_at: str
    finished_at: str
    records_received: int = 0
    records_accepted: int = 0
    raw_evidence: tuple[RawEvidenceReference, ...] = ()
    observations: tuple[Observation, ...] = ()
    diagnostics: tuple[SourceDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if self.records_received < 0 or self.records_accepted < 0:
            raise ValueError("Collection counters cannot be negative.")
    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable result without raw payload contents."""
        return {
            "source_id": self.source_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "records_received": self.records_received,
            "records_accepted": self.records_accepted,
            "raw_evidence": [
                {
                    "relative_path": item.relative_path,
                    "sha256": item.sha256,
                    "original_sha256": item.original_sha256,
                    "size_bytes": item.size_bytes,
                    "media_type": item.media_type,
                    "redactions_applied": item.redactions_applied,
                }
                for item in self.raw_evidence
            ],
            "observations": [
                {
                    "observation_type": item.observation_type,
                    "observed_value": item.observed_value,
                    "collected_at": item.collected_at,
                    "source_url": item.source_url,
                    "raw_sha256": item.raw_sha256,
                    "verification_state": item.verification_state,
                    "observed_at": item.observed_at,
                    "attributes": item.attributes,
                }
                for item in self.observations
            ],
            "diagnostics": [
                {
                    "code": item.code,
                    "message": item.message,
                    "severity": item.severity,
                }
                for item in self.diagnostics
            ],
        }


class SourceCollectionError(RuntimeError):
    """Expected source/input failure that should become a failed result."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        raw_evidence: tuple[RawEvidenceReference, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.raw_evidence = raw_evidence


class EvidenceWriteError(RuntimeError):
    """Raw evidence could not be preserved safely; this is fatal to the run."""


class Collector(Protocol):
    """One adapter with a stable definition and one collection operation."""

    @property
    def definition(self) -> SourceDefinition: ...

    def collect(self, context: CollectionContext) -> CollectionResult: ...


def run_collector(
    collector: Collector,
    context: CollectionContext,
    *,
    logger: logging.Logger | None = None,
) -> CollectionResult:
    """Execute one adapter, converting expected source errors into failed results.

    EvidenceWriteError deliberately propagates: inability to preserve evidence
    must fail the enclosing pipeline operation rather than become a success.
    """
    active_logger = logger or logging.getLogger("fii.sources")
    started_at = utc_now()
    try:
        result = collector.collect(context)
    except SourceCollectionError as exc:
        finished_at = utc_now()
        result = CollectionResult(
            source_id=collector.definition.source_id,
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            raw_evidence=exc.raw_evidence,
            diagnostics=(SourceDiagnostic(exc.code, exc.message, "error"),),
        )
    else:
        result = replace(result, started_at=started_at, finished_at=utc_now())

    log_method = active_logger.info if result.status == "success" else active_logger.warning
    diagnostic_codes = ",".join(item.code for item in result.diagnostics) or "-"
    log_method(
        "source_execution source_id=%s status=%s records_received=%d "
        "records_accepted=%d evidence_files=%d diagnostic_codes=%s",
        result.source_id,
        result.status,
        result.records_received,
        result.records_accepted,
        len(result.raw_evidence),
        diagnostic_codes,
    )
    return result
