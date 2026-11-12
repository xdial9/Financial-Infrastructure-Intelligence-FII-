"""Canonical observation normalization and deterministic deduplication."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import unicodedata
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fii.core.scope import ScopeError, normalize_domain
from fii.sources.contracts import Observation

CANONICALIZATION_VERSION = "observation-v1"
_OBSERVATION_TYPE_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_DOMAIN_OBSERVATION_TYPES = {
    "domain_seen",
    "rdap_domain",
    "rdap_nameserver",
    "hostname_seen",
    "hostname",
}
_IP_OBSERVATION_TYPES = {"ip_address", "ip_seen"}
_SHA256_OBSERVATION_TYPES = {"sha256", "certificate_sha256"}
_VOLATILE_ATTRIBUTE_KEYS = {
    "provider",
    "query_value",
    "match_method",
    "candidate_match",
    "golden_copy_publication",
}


class NormalizationError(ValueError):
    """Raised when a source observation cannot be safely normalized."""


@dataclass(frozen=True)
class SourceObservationEnvelope:
    """One source observation with the execution and evidence that produced it."""

    run_id: str
    source_execution_id: str
    observation: Observation
    raw_evidence_path: str | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.run_id, "run_id")
        _require_uuid(self.source_execution_id, "source_execution_id")
        if self.raw_evidence_path is not None:
            _validate_relative_evidence_path(self.raw_evidence_path)


@dataclass(frozen=True)
class ObservationProvenance:
    """One immutable source/evidence contribution to a canonical fact."""

    provenance_id: str
    source_execution_id: str
    source_url: str | None
    raw_evidence_path: str | None
    raw_sha256: str
    collected_at: str
    observed_at: str | None
    attributes: dict[str, Any]
    provenance_role: str


@dataclass(frozen=True)
class CanonicalObservation:
    """One normalized fact with every contributing source reference retained."""

    observation_id: str
    run_id: str
    source_execution_id: str
    observation_type: str
    observed_value: str
    observed_at: str | None
    collected_at: str
    source_url: str | None
    raw_evidence_path: str | None
    raw_sha256: str
    verification_state: str
    attributes: dict[str, Any]
    deduplication_key: str
    canonicalization_version: str
    provenance: tuple[ObservationProvenance, ...]


@dataclass(frozen=True)
class DeduplicationResult:
    """Canonical facts plus deterministic input and duplicate counters."""

    observations: tuple[CanonicalObservation, ...]
    input_count: int
    unique_count: int

    @property
    def duplicates_collapsed(self) -> int:
        return self.input_count - self.unique_count


def _require_uuid(value: str, label: str) -> uuid.UUID:
    try:
        parsed = uuid.UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise NormalizationError(f"{label} must be a valid UUID.") from exc
    if str(parsed) != value.lower():
        raise NormalizationError(f"{label} must use canonical UUID form.")
    return parsed


def _validate_relative_evidence_path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or str(path) != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in value
    ):
        raise NormalizationError("Evidence paths must be safe, normalized relative POSIX paths.")


def _normalize_timestamp(value: str | None) -> str | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        return parsed.isoformat(timespec="seconds")
    return parsed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise NormalizationError("URL observations must contain an absolute HTTP or HTTPS URL.")
    if parsed.username is not None or parsed.password is not None:
        raise NormalizationError("URL observations cannot contain embedded credentials.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise NormalizationError("URL observation contains an invalid port.") from exc
    host = parsed.hostname.encode("idna").decode("ascii").lower()
    display_host = f"[{host}]" if ":" in host else host
    netloc = display_host if port is None or (parsed.scheme.lower(), port) in {
        ("http", 80), ("https", 443)
    } else f"{display_host}:{port}"
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), netloc, path, parsed.query, ""))


def _normalize_observed_value(observation_type: str, value: str) -> tuple[str, str]:
    raw = unicodedata.normalize("NFC", value)
    display = " ".join(raw.split())
    if not display:
        raise NormalizationError("Observation values cannot be empty.")

    if observation_type in _DOMAIN_OBSERVATION_TYPES:
        try:
            canonical = normalize_domain(display)
        except ScopeError as exc:
            raise NormalizationError("Domain/hostname observation is invalid.") from exc
        return canonical, canonical

    if observation_type in _IP_OBSERVATION_TYPES:
        try:
            canonical = ipaddress.ip_address(display).compressed
        except ValueError as exc:
            raise NormalizationError("IP address observation is invalid.") from exc
        return canonical, canonical

    if observation_type in _SHA256_OBSERVATION_TYPES:
        canonical = display.lower()
        if not re.fullmatch(r"[0-9a-f]{64}", canonical):
            raise NormalizationError("SHA-256 observation must contain 64 hexadecimal characters.")
        return canonical, canonical

    if observation_type.endswith("_url") or observation_type in {"url", "api_url"}:
        canonical = _normalize_url(display)
        return canonical, canonical

    if observation_type == "legal_entity_identifier":
        canonical = display.upper()
        if not re.fullmatch(r"[A-Z0-9]{20}", canonical):
            raise NormalizationError("Legal Entity Identifier observation must be 20 characters.")
        return canonical, canonical

    return display, display.casefold()


def _canonical_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str):
            return unicodedata.normalize("NFC", " ".join(value.split())).casefold()
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise NormalizationError("Observation attributes cannot contain NaN or infinity.")
        return value
    if isinstance(value, list | tuple):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise NormalizationError("Observation attribute keys must be strings.")
        return {
            key: _canonical_json_value(value[key])
            for key in sorted(value)
        }
    raise NormalizationError(
        f"Unsupported observation attribute value type: {type(value).__name__}."
    )


def _semantic_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(attributes, dict):
        raise NormalizationError("Observation attributes must be a mapping.")
    return {
        key: value
        for key, value in sorted(attributes.items())
        if key not in _VOLATILE_ATTRIBUTE_KEYS
    }


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise NormalizationError("Observation attributes are not valid canonical JSON.") from exc


def _build_deduplication_key(
    observation_type: str,
    comparison_value: str,
    observed_at: str | None,
    semantic_attributes: dict[str, Any],
) -> str:
    payload = {
        "canonicalization_version": CANONICALIZATION_VERSION,
        "observation_type": observation_type,
        "observed_value": comparison_value,
        "observed_at": observed_at,
        "attributes": _canonical_json_value(semantic_attributes),
    }
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


def normalize_observation(envelope: SourceObservationEnvelope) -> CanonicalObservation:
    """Normalize one source fact without changing or discarding its evidence."""
    observation = envelope.observation
    observation_type = observation.observation_type.strip().lower()
    if not _OBSERVATION_TYPE_RE.fullmatch(observation_type):
        raise NormalizationError("Observation type must use a stable lowercase identifier.")

    display_value, comparison_value = _normalize_observed_value(
        observation_type,
        observation.observed_value,
    )
    observed_at = _normalize_timestamp(observation.observed_at)
    semantic_attributes = _semantic_attributes(observation.attributes)
    key = _build_deduplication_key(
        observation_type,
        comparison_value,
        observed_at,
        semantic_attributes,
    )
    observation_id = str(
        uuid.uuid5(_require_uuid(envelope.run_id, "run_id"), f"canonical:{key}")
    )
    provenance_id = str(
        uuid.uuid5(
            uuid.UUID(observation_id),
            f"{envelope.source_execution_id}:{observation.raw_sha256}:"
            f"{observation.source_url or ''}:{envelope.raw_evidence_path or ''}",
        )
    )
    provenance = ObservationProvenance(
        provenance_id=provenance_id,
        source_execution_id=envelope.source_execution_id,
        source_url=observation.source_url,
        raw_evidence_path=envelope.raw_evidence_path,
        raw_sha256=observation.raw_sha256,
        collected_at=observation.collected_at,
        observed_at=observed_at,
        attributes=observation.attributes,
        provenance_role="primary",
    )
    return CanonicalObservation(
        observation_id=observation_id,
        run_id=envelope.run_id,
        source_execution_id=envelope.source_execution_id,
        observation_type=observation_type,
        observed_value=display_value,
        observed_at=observed_at,
        collected_at=observation.collected_at,
        source_url=observation.source_url,
        raw_evidence_path=envelope.raw_evidence_path,
        raw_sha256=observation.raw_sha256,
        verification_state=observation.verification_state,
        attributes=semantic_attributes,
        deduplication_key=key,
        canonicalization_version=CANONICALIZATION_VERSION,
        provenance=(provenance,),
    )


def deduplicate_observations(
    envelopes: Iterable[SourceObservationEnvelope],
) -> DeduplicationResult:
    """Group identical facts while preserving a provenance record per source object."""
    normalized = [normalize_observation(item) for item in envelopes]
    groups: dict[str, list[CanonicalObservation]] = defaultdict(list)
    for item in normalized:
        groups[item.deduplication_key].append(item)

    canonical: list[CanonicalObservation] = []
    for key in sorted(groups):
        group = sorted(
            groups[key],
            key=lambda item: (
                item.source_execution_id,
                item.raw_sha256,
                item.source_url or "",
                item.raw_evidence_path or "",
            ),
        )
        first = group[0]
        provenance_by_identity: dict[tuple[str, str], ObservationProvenance] = {}
        for item in group:
            if (
                item.observation_type != first.observation_type
                or item.observed_value.casefold() != first.observed_value.casefold()
            ):
                raise NormalizationError("Deduplication key collision detected.")
            for provenance in item.provenance:
                identity = (provenance.source_execution_id, provenance.raw_sha256)
                previous = provenance_by_identity.get(identity)
                if previous is None:
                    provenance_by_identity[identity] = provenance
        provenance_values = sorted(
            provenance_by_identity.values(),
            key=lambda item: (
                item.source_execution_id,
                item.raw_sha256,
                item.source_url or "",
                item.raw_evidence_path or "",
            ),
        )
        primary_execution_id = provenance_values[0].source_execution_id
        provenance_values = [
            ObservationProvenance(
                provenance_id=item.provenance_id,
                source_execution_id=item.source_execution_id,
                source_url=item.source_url,
                raw_evidence_path=item.raw_evidence_path,
                raw_sha256=item.raw_sha256,
                collected_at=item.collected_at,
                observed_at=item.observed_at,
                attributes=item.attributes,
                provenance_role=(
                    "primary" if item.source_execution_id == primary_execution_id else "context"
                ),
            )
            for item in provenance_values
        ]
        primary = next(
            item for item in provenance_values if item.source_execution_id == primary_execution_id
        )
        collected_at = min(item.collected_at for item in provenance_values)
        canonical.append(
            CanonicalObservation(
                observation_id=first.observation_id,
                run_id=first.run_id,
                source_execution_id=primary.source_execution_id,
                observation_type=first.observation_type,
                observed_value=first.observed_value,
                observed_at=first.observed_at,
                collected_at=collected_at,
                source_url=primary.source_url,
                raw_evidence_path=primary.raw_evidence_path,
                raw_sha256=primary.raw_sha256,
                verification_state=(
                    "unverified"
                    if any(item.verification_state == "unverified" for item in group)
                    else "observed"
                ),
                attributes=first.attributes,
                deduplication_key=key,
                canonicalization_version=CANONICALIZATION_VERSION,
                provenance=tuple(provenance_values),
            )
        )
    return DeduplicationResult(
        observations=tuple(canonical),
        input_count=len(normalized),
        unique_count=len(canonical),
    )
