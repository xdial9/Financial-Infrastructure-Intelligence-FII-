"""Canonical observation and entity normalization for FII."""

from fii.normalization.entities import (
    EntityIdentifier,
    EntityResolutionCandidate,
    EntityResolutionError,
    EntityResolutionResult,
    EntitySeed,
    register_entity_registry,
    resolve_entity,
)
from fii.normalization.identifiers import (
    ENTITY_TYPE_DEFINITIONS,
    IDENTIFIER_TYPE_DEFINITIONS,
    REGISTRY_VERSION,
    NormalizedIdentifier,
    normalize_identifier,
    normalize_name,
)
from fii.normalization.observations import (
    CANONICALIZATION_VERSION,
    CanonicalObservation,
    DeduplicationResult,
    NormalizationError,
    SourceObservationEnvelope,
    deduplicate_observations,
    normalize_observation,
)
from fii.normalization.persistence import (
    DeduplicationPersistenceResult,
    persist_canonical_observations,
)

__all__ = [
    "CANONICALIZATION_VERSION",
    "ENTITY_TYPE_DEFINITIONS",
    "IDENTIFIER_TYPE_DEFINITIONS",
    "REGISTRY_VERSION",
    "CanonicalObservation",
    "DeduplicationPersistenceResult",
    "DeduplicationResult",
    "EntityIdentifier",
    "EntityResolutionCandidate",
    "EntityResolutionError",
    "EntityResolutionResult",
    "EntitySeed",
    "NormalizationError",
    "NormalizedIdentifier",
    "SourceObservationEnvelope",
    "deduplicate_observations",
    "normalize_identifier",
    "normalize_name",
    "normalize_observation",
    "persist_canonical_observations",
    "register_entity_registry",
    "resolve_entity",
]
