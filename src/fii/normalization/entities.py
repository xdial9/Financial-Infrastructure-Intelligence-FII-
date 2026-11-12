"""Deterministic, evidence-backed entity resolution.

Only exact registered strong identifiers can auto-resolve an entity. Names and
other weak identifiers generate review candidates; they never trigger a merge.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from fii.normalization.identifiers import (
    ENTITY_TYPE_DEFINITIONS,
    IDENTIFIER_TYPE_DEFINITIONS,
    REGISTRY_VERSION,
    NormalizedIdentifier,
    normalize_identifier,
)
from fii.storage.database import PersistenceError, transaction
from fii.sources.contracts import utc_now

ENTITY_NAMESPACE = uuid.UUID("b1a46285-41b9-5b10-a617-30d3a8b1c6e7")
RESOLUTION_RULE_ID = "exact-identifier-and-name-candidate"
RESOLUTION_RULE_VERSION = "1.0.0"
NAME_CANDIDATE_THRESHOLD = 0.78


class EntityResolutionError(ValueError):
    """Raised when an entity seed cannot be resolved safely."""


@dataclass(frozen=True)
class EntityIdentifier:
    """An identifier supplied with an entity seed."""

    identifier_type: str
    value: str


@dataclass(frozen=True)
class EntitySeed:
    """One evidence-anchored proposed entity."""

    run_id: str
    source_observation_id: str
    entity_type: str
    display_name: str
    identifiers: tuple[EntityIdentifier, ...] = ()
    jurisdiction: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EntityResolutionCandidate:
    """An existing entity that may be the same subject, pending review."""

    entity_id: str
    match_method: str
    similarity_score: float
    rationale: str


@dataclass(frozen=True)
class EntityResolutionResult:
    """Explainable entity-resolution outcome."""

    decision_id: str
    outcome: str
    entity_id: str | None
    matched_entity_id: str | None
    match_method: str
    confidence: float | None
    rationale: str
    candidates: tuple[EntityResolutionCandidate, ...]


def _json_object(value: dict[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise EntityResolutionError("Entity attributes must be valid JSON data.") from exc


def _ensure_registries(connection: sqlite3.Connection) -> None:
    for definition in ENTITY_TYPE_DEFINITIONS.values():
        connection.execute(
            """
            INSERT OR IGNORE INTO entity_type_registry (
                entity_type, description, registry_version
            ) VALUES (?, ?, ?)
            """,
            (definition.entity_type, definition.description, REGISTRY_VERSION),
        )
        row = connection.execute(
            """
            SELECT description, registry_version FROM entity_type_registry
            WHERE entity_type = ?
            """,
            (definition.entity_type,),
        ).fetchone()
        if row is None or (
            row["description"] != definition.description
            or row["registry_version"] != REGISTRY_VERSION
        ):
            raise PersistenceError(
                f"Persisted entity type registry differs for {definition.entity_type!r}."
            )

    for definition in IDENTIFIER_TYPE_DEFINITIONS.values():
        connection.execute(
            """
            INSERT OR IGNORE INTO identifier_type_registry (
                identifier_type, entity_type, description, normalization_rule,
                resolution_strength, registry_version
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                definition.identifier_type,
                definition.entity_type,
                definition.description,
                definition.normalization_rule,
                definition.resolution_strength,
                REGISTRY_VERSION,
            ),
        )
        row = connection.execute(
            """
            SELECT entity_type, description, normalization_rule,
                   resolution_strength, registry_version
            FROM identifier_type_registry WHERE identifier_type = ?
            """,
            (definition.identifier_type,),
        ).fetchone()
        expected = (
            definition.entity_type,
            definition.description,
            definition.normalization_rule,
            definition.resolution_strength,
            REGISTRY_VERSION,
        )
        actual = tuple(row) if row is not None else None
        if actual != expected:
            raise PersistenceError(
                f"Persisted identifier registry differs for {definition.identifier_type!r}."
            )


def register_entity_registry(connection: sqlite3.Connection) -> None:
    """Persist the fixed entity and identifier registries idempotently."""
    if connection.in_transaction:
        raise PersistenceError("Registry installation requires its own transaction.")
    try:
        with transaction(connection, immediate=True):
            _ensure_registries(connection)
    except PersistenceError:
        raise
    except sqlite3.Error as exc:
        raise PersistenceError("Unable to register FII entity and identifier types.") from exc


def _normalize_seed(seed: EntitySeed) -> tuple[NormalizedIdentifier, ...]:
    try:
        parsed_run_id = uuid.UUID(seed.run_id)
        parsed_observation_id = uuid.UUID(seed.source_observation_id)
    except (TypeError, ValueError, AttributeError) as exc:
        raise EntityResolutionError(
            "Entity seed requires canonical run and observation UUIDs."
        ) from exc
    if (
        str(parsed_run_id) != seed.run_id.lower()
        or str(parsed_observation_id) != seed.source_observation_id.lower()
    ):
        raise EntityResolutionError("Entity seed UUIDs must use canonical form.")
    if seed.entity_type not in ENTITY_TYPE_DEFINITIONS:
        raise EntityResolutionError(f"Unsupported entity type: {seed.entity_type!r}.")
    if not isinstance(seed.display_name, str) or not seed.display_name.strip():
        raise EntityResolutionError("Entity display name is required.")
    if not isinstance(seed.source_observation_id, str) or not seed.source_observation_id.strip():
        raise EntityResolutionError("Entity resolution requires a source observation ID.")

    inputs = list(seed.identifiers)
    default_weak_type = {
        "organization": "legal_name",
        "vendor": "brand_name",
    }.get(seed.entity_type)
    if default_weak_type and not any(
        item.identifier_type == default_weak_type for item in inputs
    ):
        inputs.append(EntityIdentifier(default_weak_type, seed.display_name))

    normalized: dict[tuple[str, str], NormalizedIdentifier] = {}
    for item in inputs:
        value = normalize_identifier(
            item.identifier_type,
            item.value,
            entity_type=seed.entity_type,
        )
        normalized[(value.identifier_type, value.identifier_value)] = value
    return tuple(normalized[key] for key in sorted(normalized))


def _name_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    union = left_tokens | right_tokens
    token_score = len(left_tokens & right_tokens) / len(union) if union else 0.0
    sequence_score = SequenceMatcher(None, left, right, autojunk=False).ratio()
    return round((0.65 * sequence_score) + (0.35 * token_score), 6)


def _candidate_matches(
    connection: sqlite3.Connection,
    *,
    entity_type: str,
    weak_identifiers: tuple[NormalizedIdentifier, ...],
    jurisdiction: str | None,
    exclude_entity_id: str | None,
) -> tuple[EntityResolutionCandidate, ...]:
    found: dict[str, EntityResolutionCandidate] = {}
    normalized_jurisdiction = jurisdiction.strip().upper() if jurisdiction else None

    for identifier in weak_identifiers:
        rows = connection.execute(
            """
            SELECT e.entity_id, e.display_name, e.attributes_json,
                   ei.identifier_value
            FROM entity_identifier AS ei
            JOIN entity AS e ON e.entity_id = ei.entity_id
            WHERE e.entity_type = ? AND ei.identifier_type = ?
            ORDER BY e.entity_id
            """,
            (entity_type, identifier.identifier_type),
        ).fetchall()
        for row in rows:
            candidate_id = row["entity_id"]
            if candidate_id == exclude_entity_id:
                continue
            candidate_name = row["identifier_value"]
            score = _name_similarity(identifier.identifier_value, candidate_name)
            if score < NAME_CANDIDATE_THRESHOLD:
                continue

            try:
                existing_attributes = json.loads(row["attributes_json"] or "{}")
            except json.JSONDecodeError:
                existing_attributes = {}
            candidate_jurisdiction = (
                existing_attributes.get("jurisdiction")
                if isinstance(existing_attributes, dict)
                else None
            )
            candidate_jurisdiction = (
                candidate_jurisdiction.strip().upper()
                if isinstance(candidate_jurisdiction, str) and candidate_jurisdiction.strip()
                else None
            )
            if normalized_jurisdiction and candidate_jurisdiction:
                if normalized_jurisdiction == candidate_jurisdiction:
                    jurisdiction_note = (
                        f"Jurisdiction {normalized_jurisdiction} agrees; "
                        "this is still a name-only candidate."
                    )
                else:
                    jurisdiction_note = (
                        f"Jurisdictions differ ({normalized_jurisdiction} vs "
                        f"{candidate_jurisdiction}); do not merge."
                    )
            else:
                jurisdiction_note = "At least one jurisdiction is unknown; do not merge."

            exact_name = score == 1.0
            method = "exact_normalized_name_candidate" if exact_name else "similar_name_candidate"
            rationale = (
                f"Name similarity score {score:.3f} for identifier type "
                f"{identifier.identifier_type!r}. {jurisdiction_note}"
            )
            prior = found.get(candidate_id)
            current = EntityResolutionCandidate(
                entity_id=candidate_id,
                match_method=method,
                similarity_score=score,
                rationale=rationale,
            )
            if prior is None or current.similarity_score > prior.similarity_score:
                found[candidate_id] = current

    return tuple(
        sorted(
            found.values(),
            key=lambda item: (-item.similarity_score, item.entity_id),
        )
    )


def _insert_decision(
    connection: sqlite3.Connection,
    *,
    decision_id: str,
    seed: EntitySeed,
    outcome: str,
    proposed_entity_id: str | None,
    matched_entity_id: str | None,
    match_method: str,
    confidence: float | None,
    rationale: str,
    candidates: tuple[EntityResolutionCandidate, ...],
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO entity_resolution_decision (
            decision_id, run_id, source_observation_id, outcome,
            proposed_entity_id, matched_entity_id, match_method, confidence,
            rationale, rule_id, rule_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            decision_id,
            seed.run_id,
            seed.source_observation_id,
            outcome,
            proposed_entity_id,
            matched_entity_id,
            match_method,
            confidence,
            rationale,
            RESOLUTION_RULE_ID,
            RESOLUTION_RULE_VERSION,
            created_at,
        ),
    )
    for candidate in candidates:
        candidate_id = str(
            uuid.uuid5(
                uuid.UUID(decision_id),
                f"{candidate.entity_id}:{candidate.match_method}",
            )
        )
        connection.execute(
            """
            INSERT INTO entity_resolution_candidate (
                candidate_id, decision_id, candidate_entity_id, match_method,
                similarity_score, rationale, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                decision_id,
                candidate.entity_id,
                candidate.match_method,
                candidate.similarity_score,
                candidate.rationale,
                created_at,
            ),
        )


def _load_prior_decision(
    connection: sqlite3.Connection,
    decision_id: str,
) -> EntityResolutionResult | None:
    row = connection.execute(
        """
        SELECT decision_id, outcome, proposed_entity_id, matched_entity_id,
               match_method, confidence, rationale
        FROM entity_resolution_decision WHERE decision_id = ?
        """,
        (decision_id,),
    ).fetchone()
    if row is None:
        return None
    candidates = connection.execute(
        """
        SELECT candidate_entity_id, match_method, similarity_score, rationale
        FROM entity_resolution_candidate WHERE decision_id = ?
        ORDER BY similarity_score DESC, candidate_entity_id
        """,
        (decision_id,),
    ).fetchall()
    return EntityResolutionResult(
        decision_id=row["decision_id"],
        outcome=row["outcome"],
        entity_id=row["matched_entity_id"] or row["proposed_entity_id"],
        matched_entity_id=row["matched_entity_id"],
        match_method=row["match_method"],
        confidence=row["confidence"],
        rationale=row["rationale"],
        candidates=tuple(
            EntityResolutionCandidate(
                entity_id=item["candidate_entity_id"],
                match_method=item["match_method"],
                similarity_score=float(item["similarity_score"]),
                rationale=item["rationale"],
            )
            for item in candidates
        ),
    )


def _ensure_entity(
    connection: sqlite3.Connection,
    *,
    entity_id: str,
    entity_type: str,
    canonical_key: str,
    display_name: str,
    attributes: dict[str, Any],
    timestamp: str,
) -> None:
    existing = connection.execute(
        "SELECT entity_type, canonical_key FROM entity WHERE entity_id = ?",
        (entity_id,),
    ).fetchone()
    if existing is not None:
        if existing["entity_type"] != entity_type or existing["canonical_key"] != canonical_key:
            raise PersistenceError("Deterministic entity ID collides with a different entity.")
        return

    same_key = connection.execute(
        """
        SELECT entity_id FROM entity WHERE entity_type = ? AND canonical_key = ?
        """,
        (entity_type, canonical_key),
    ).fetchone()
    if same_key is not None:
        if same_key["entity_id"] != entity_id:
            raise PersistenceError("Entity canonical key is already assigned to another ID.")
        return

    connection.execute(
        """
        INSERT INTO entity (
            entity_id, entity_type, canonical_key, display_name,
            created_at, updated_at, attributes_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_id,
            entity_type,
            canonical_key,
            display_name.strip(),
            timestamp,
            timestamp,
            _json_object(attributes),
        ),
    )


def _insert_identifiers(
    connection: sqlite3.Connection,
    *,
    entity_id: str,
    identifiers: tuple[NormalizedIdentifier, ...],
    source_observation_id: str,
    timestamp: str,
) -> None:
    for identifier in identifiers:
        existing = connection.execute(
            """
            SELECT identifier_id FROM entity_identifier
            WHERE entity_id = ? AND identifier_type = ? AND identifier_value = ?
            """,
            (entity_id, identifier.identifier_type, identifier.identifier_value),
        ).fetchone()
        if existing is not None:
            connection.execute(
                """
                UPDATE entity_identifier SET last_seen_at = ?
                WHERE identifier_id = ?
                """,
                (timestamp, existing["identifier_id"]),
            )
            continue

        identifier_id = str(
            uuid.uuid5(
                uuid.UUID(entity_id),
                f"{identifier.identifier_type}:{identifier.identifier_value}",
            )
        )
        connection.execute(
            """
            INSERT INTO entity_identifier (
                identifier_id, entity_id, identifier_type, identifier_value,
                source_observation_id, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier_id,
                entity_id,
                identifier.identifier_type,
                identifier.identifier_value,
                source_observation_id,
                timestamp,
                timestamp,
            ),
        )


def _record_conflict(
    connection: sqlite3.Connection,
    *,
    seed: EntitySeed,
    decision_id: str,
    candidates: tuple[EntityResolutionCandidate, ...],
    rationale: str,
    timestamp: str,
) -> EntityResolutionResult:
    _insert_decision(
        connection,
        decision_id=decision_id,
        seed=seed,
        outcome="conflict",
        proposed_entity_id=None,
        matched_entity_id=None,
        match_method="conflicting_strong_identifiers",
        confidence=None,
        rationale=rationale,
        candidates=candidates,
        created_at=timestamp,
    )
    return EntityResolutionResult(
        decision_id=decision_id,
        outcome="conflict",
        entity_id=None,
        matched_entity_id=None,
        match_method="conflicting_strong_identifiers",
        confidence=None,
        rationale=rationale,
        candidates=candidates,
    )


def resolve_entity(
    connection: sqlite3.Connection,
    seed: EntitySeed,
) -> EntityResolutionResult:
    """Resolve by exact strong identifiers; keep name similarity as candidates.

    A legal/brand-name-only seed creates an observation-anchored provisional
    entity. Similar names are linked as pending candidates and never auto-merged.
    """
    normalized_identifiers = _normalize_seed(seed)
    strong = tuple(
        item for item in normalized_identifiers if item.resolution_strength == "strong"
    )
    weak = tuple(
        item for item in normalized_identifiers if item.resolution_strength == "weak"
    )
    decision_id = str(
        uuid.uuid5(
            uuid.UUID(seed.run_id),
            f"entity-resolution:{seed.source_observation_id}:{RESOLUTION_RULE_VERSION}",
        )
    )
    if connection.in_transaction:
        raise PersistenceError("Entity resolution requires its own transaction.")

    try:
        with transaction(connection, immediate=True):
            _ensure_registries(connection)
            existing_decision = _load_prior_decision(connection, decision_id)
            if existing_decision is not None:
                return existing_decision

            observation = connection.execute(
                """
                SELECT subject_entity_id FROM observation
                WHERE observation_id = ? AND run_id = ?
                """,
                (seed.source_observation_id, seed.run_id),
            ).fetchone()
            if observation is None:
                raise EntityResolutionError(
                    "Entity seed source observation does not exist in the supplied run."
                )

            timestamp = utc_now()
            jurisdiction = seed.jurisdiction.strip().upper() if seed.jurisdiction else None
            attributes = dict(seed.attributes)
            if jurisdiction:
                attributes["jurisdiction"] = jurisdiction
            attributes["registry_version"] = REGISTRY_VERSION

            matched_by_identifier: dict[str, set[str]] = {}
            for identifier in strong:
                rows = connection.execute(
                    """
                    SELECT DISTINCT e.entity_id
                    FROM entity_identifier AS ei
                    JOIN entity AS e ON e.entity_id = ei.entity_id
                    WHERE e.entity_type = ?
                      AND ei.identifier_type = ?
                      AND ei.identifier_value = ?
                    ORDER BY e.entity_id
                    """,
                    (seed.entity_type, identifier.identifier_type, identifier.identifier_value),
                ).fetchall()
                matches = {row["entity_id"] for row in rows}
                if matches:
                    matched_by_identifier[
                        f"{identifier.identifier_type}:{identifier.identifier_value}"
                    ] = matches

            matched_ids = (
                set().union(*matched_by_identifier.values())
                if matched_by_identifier
                else set()
            )
            ambiguous_identifier = any(
                len(items) > 1 for items in matched_by_identifier.values()
            )
            if ambiguous_identifier or len(matched_ids) > 1:
                candidates = tuple(
                    EntityResolutionCandidate(
                        entity_id=entity_id,
                        match_method="strong_identifier_collision",
                        similarity_score=1.0,
                        rationale=(
                            "One or more exact identifiers resolve to multiple canonical "
                            "entities or different exact identifiers point to different entities."
                        ),
                    )
                    for entity_id in sorted(matched_ids)
                )
                return _record_conflict(
                    connection,
                    seed=seed,
                    decision_id=decision_id,
                    candidates=candidates,
                    rationale=(
                        "Conflicting exact identifier mappings were found. No entity was "
                        "merged or reassigned; analyst review is required."
                    ),
                    timestamp=timestamp,
                )

            currently_assigned = observation["subject_entity_id"]
            if currently_assigned and strong and not matched_ids:
                assigned_entity = connection.execute(
                    "SELECT entity_type, canonical_key FROM entity WHERE entity_id = ?",
                    (currently_assigned,),
                ).fetchone()
                expected_provisional_key = (
                    f"provisional:{seed.run_id}:{seed.source_observation_id}"
                )
                if (
                    assigned_entity is not None
                    and assigned_entity["entity_type"] == seed.entity_type
                    and assigned_entity["canonical_key"] == expected_provisional_key
                ):
                    matched_ids.add(currently_assigned)
                elif assigned_entity is not None:
                    return _record_conflict(
                        connection,
                        seed=seed,
                        decision_id=decision_id,
                        candidates=(
                            EntityResolutionCandidate(
                                entity_id=currently_assigned,
                                match_method="existing_subject_conflict",
                                similarity_score=1.0,
                                rationale=(
                                    "Existing non-provisional entity assignment was not "
                                    "overwritten by a new identifier."
                                ),
                            ),
                        ),
                        rationale=(
                            "A strong identifier was supplied for an observation already "
                            "assigned to a non-provisional entity. No reassignment was made."
                        ),
                        timestamp=timestamp,
                    )

            if currently_assigned and matched_ids and currently_assigned not in matched_ids:
                candidates = tuple(
                    EntityResolutionCandidate(
                        entity_id=entity_id,
                        match_method="existing_subject_conflict",
                        similarity_score=1.0,
                        rationale=(
                            "An exact identifier conflicts with the observation's "
                            "existing entity assignment."
                        ),
                    )
                    for entity_id in sorted({currently_assigned, *matched_ids})
                )
                return _record_conflict(
                    connection,
                    seed=seed,
                    decision_id=decision_id,
                    candidates=candidates,
                    rationale=(
                        "The observation is already assigned to a different entity than the "
                        "exact identifier match. Existing assignments were preserved."
                    ),
                    timestamp=timestamp,
                )

            if strong:
                if matched_ids:
                    entity_id = next(iter(matched_ids))
                    outcome = "matched"
                    match_method = "exact_strong_identifier"
                    confidence = 1.0
                    rationale = (
                        "One canonical entity matched every supplied strong identifier. "
                        "Weak names were retained as aliases; no name-based merge was used."
                    )
                    matched_entity_id = entity_id
                    proposed_entity_id = None
                else:
                    identity = strong[0]
                    canonical_key = (
                        f"identifier:{identity.identifier_type}:{identity.identifier_value}"
                    )
                    entity_id = str(
                        uuid.uuid5(
                            ENTITY_NAMESPACE,
                            f"{seed.entity_type}:{canonical_key}",
                        )
                    )
                    _ensure_entity(
                        connection,
                        entity_id=entity_id,
                        entity_type=seed.entity_type,
                        canonical_key=canonical_key,
                        display_name=seed.display_name,
                        attributes=attributes,
                        timestamp=timestamp,
                    )
                    outcome = "created"
                    match_method = f"new_exact_{identity.identifier_type}"
                    confidence = 1.0
                    rationale = (
                        f"No existing entity used the exact strong identifier "
                        f"{identity.identifier_type!r}; a canonical entity was created."
                    )
                    name_candidates = _candidate_matches(
                        connection,
                        entity_type=seed.entity_type,
                        weak_identifiers=weak,
                        jurisdiction=jurisdiction,
                        exclude_entity_id=entity_id,
                    )
                    if name_candidates:
                        rationale += (
                            " Similar-name entities were recorded as review candidates; "
                            "the exact identifier remained the only auto-resolution rule."
                        )
                    matched_entity_id = None
                    proposed_entity_id = entity_id

                _insert_identifiers(
                    connection,
                    entity_id=entity_id,
                    identifiers=normalized_identifiers,
                    source_observation_id=seed.source_observation_id,
                    timestamp=timestamp,
                )
                if currently_assigned is None:
                    connection.execute(
                        """
                        UPDATE observation SET subject_entity_id = ?
                        WHERE observation_id = ? AND run_id = ? AND subject_entity_id IS NULL
                        """,
                        (entity_id, seed.source_observation_id, seed.run_id),
                    )
                elif currently_assigned != entity_id:
                    raise PersistenceError("Entity assignment changed during exact resolution.")

                decision_candidates = (
                    name_candidates if outcome == "created" and not matched_ids else ()
                )
                _insert_decision(
                    connection,
                    decision_id=decision_id,
                    seed=seed,
                    outcome=outcome,
                    proposed_entity_id=proposed_entity_id,
                    matched_entity_id=matched_entity_id,
                    match_method=match_method,
                    confidence=confidence,
                    rationale=rationale,
                    candidates=decision_candidates,
                    created_at=timestamp,
                )
                return EntityResolutionResult(
                    decision_id=decision_id,
                    outcome=outcome,
                    entity_id=entity_id,
                    matched_entity_id=matched_entity_id,
                    match_method=match_method,
                    confidence=confidence,
                    rationale=rationale,
                    candidates=decision_candidates,
                )

            provisional_key = f"provisional:{seed.run_id}:{seed.source_observation_id}"
            provisional_id = str(
                uuid.uuid5(
                    ENTITY_NAMESPACE,
                    f"{seed.entity_type}:{provisional_key}",
                )
            )
            if currently_assigned is not None and currently_assigned != provisional_id:
                assigned = connection.execute(
                    "SELECT entity_type, canonical_key FROM entity WHERE entity_id = ?",
                    (currently_assigned,),
                ).fetchone()
                if assigned is None or assigned["entity_type"] != seed.entity_type:
                    return _record_conflict(
                        connection,
                        seed=seed,
                        decision_id=decision_id,
                        candidates=(),
                        rationale=(
                            "The source observation already belongs to an entity of a "
                            "different type. The existing assignment was preserved."
                        ),
                        timestamp=timestamp,
                    )
                provisional_id = currently_assigned
                provisional_key = assigned["canonical_key"]

            _ensure_entity(
                connection,
                entity_id=provisional_id,
                entity_type=seed.entity_type,
                canonical_key=provisional_key,
                display_name=seed.display_name,
                attributes=attributes,
                timestamp=timestamp,
            )
            _insert_identifiers(
                connection,
                entity_id=provisional_id,
                identifiers=normalized_identifiers,
                source_observation_id=seed.source_observation_id,
                timestamp=timestamp,
            )
            if currently_assigned is None:
                connection.execute(
                    """
                    UPDATE observation SET subject_entity_id = ?
                    WHERE observation_id = ? AND run_id = ? AND subject_entity_id IS NULL
                    """,
                    (provisional_id, seed.source_observation_id, seed.run_id),
                )

            candidates = _candidate_matches(
                connection,
                entity_type=seed.entity_type,
                weak_identifiers=weak,
                jurisdiction=jurisdiction,
                exclude_entity_id=provisional_id,
            )
            outcome = "candidate" if candidates else "created"
            match_method = (
                "name_candidate_only"
                if candidates
                else "provisional_no_strong_identifier"
            )
            rationale = (
                "Name similarity produced one or more review candidates. No merge was made."
                if candidates
                else (
                    "No registered strong identifier was supplied and no name candidate "
                    "met the review threshold. A provisional entity was created."
                )
            )
            _insert_decision(
                connection,
                decision_id=decision_id,
                seed=seed,
                outcome=outcome,
                proposed_entity_id=provisional_id,
                matched_entity_id=None,
                match_method=match_method,
                confidence=None,
                rationale=rationale,
                candidates=candidates,
                created_at=timestamp,
            )
            return EntityResolutionResult(
                decision_id=decision_id,
                outcome=outcome,
                entity_id=provisional_id,
                matched_entity_id=None,
                match_method=match_method,
                confidence=None,
                rationale=rationale,
                candidates=candidates,
            )

    except (sqlite3.Error, TypeError) as exc:
        raise PersistenceError("Unable to persist the entity-resolution decision.") from exc
