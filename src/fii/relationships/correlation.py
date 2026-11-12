"""Evidence-backed relationship correlation and append-only analyst review."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fii.storage.database import PersistenceError, transaction

RELATIONSHIP_NAMESPACE = uuid.UUID("0c6e1a7b-51b8-5d1f-9c38-3b1b9c0e8d61")
REVIEW_NAMESPACE = uuid.UUID("0a6fcb6c-fec6-55b1-a41a-09ec7adab82e")


class RelationshipError(ValueError):
    """Raised when a relationship proposal or analyst review is invalid."""


@dataclass(frozen=True)
class RelationshipEvidence:
    """One source observation and its explicit evidentiary role."""

    observation_id: str
    evidence_role: str = "supports"


@dataclass(frozen=True)
class RelationshipProposal:
    """A typed relationship assertion grounded in one or more observations."""

    run_id: str
    rule_id: str
    subject_entity_id: str
    object_entity_id: str
    evidence: tuple[RelationshipEvidence, ...]
    rationale: str | None = None


@dataclass(frozen=True)
class RelationshipResult:
    """Persisted relationship and its deterministic evidence assessment."""

    relationship_id: str
    predicate: str
    verification_state: str
    confidence: float
    rationale: str
    supporting_source_count: int
    supporting_observation_count: int
    contradicting_observation_count: int
    inserted: bool


@dataclass(frozen=True)
class RelationshipReviewResult:
    """Append-only analyst disposition and resulting relationship state."""

    review_id: str
    relationship_id: str
    disposition: str
    verification_state: str
    reviewed_at: str


@dataclass(frozen=True)
class RelationshipQueueItem:
    """Relationship requiring analyst attention."""

    relationship_id: str
    subject_entity_id: str
    subject_name: str
    predicate: str
    object_entity_id: str
    object_name: str
    verification_state: str
    confidence: float | None
    rationale: str | None
    latest_disposition: str | None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_uuid(value: str, label: str) -> uuid.UUID:
    try:
        parsed = uuid.UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise RelationshipError(f"{label} must be a canonical UUID.") from exc
    if str(parsed) != value.lower():
        raise RelationshipError(f"{label} must be a canonical UUID.")
    return parsed


def _load_rule(connection: sqlite3.Connection, rule_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM relationship_rule_registry WHERE rule_id = ?", (rule_id,)
    ).fetchone()
    if row is None:
        raise RelationshipError(f"Unknown relationship rule: {rule_id!r}.")
    return row


def _source_evidence(
    connection: sqlite3.Connection,
    proposal: RelationshipProposal,
    rule: sqlite3.Row,
) -> list[sqlite3.Row]:
    if not proposal.evidence:
        raise RelationshipError("A relationship requires at least one evidence observation.")

    roles: dict[str, str] = {}
    for item in proposal.evidence:
        if item.evidence_role not in {"supports", "contradicts", "context"}:
            raise RelationshipError(f"Unsupported evidence role: {item.evidence_role!r}.")
        _canonical_uuid(item.observation_id, "observation_id")
        previous = roles.get(item.observation_id)
        if previous is not None and previous != item.evidence_role:
            raise RelationshipError(
                "One observation cannot have multiple roles on one relationship."
            )
        roles[item.observation_id] = item.evidence_role
    if "supports" not in roles.values():
        raise RelationshipError("A relationship requires at least one supporting observation.")

    observations: list[sqlite3.Row] = []
    for observation_id in sorted(roles):
        row = connection.execute(
            """
            SELECT o.observation_id, o.run_id, o.observation_type, o.observed_value,
                   o.subject_entity_id, o.attributes_json, se.source_id
            FROM observation AS o
            JOIN source_execution AS se
              ON se.source_execution_id = o.source_execution_id AND se.run_id = o.run_id
            WHERE o.observation_id = ? AND o.run_id = ?
            """,
            (observation_id, proposal.run_id),
        ).fetchone()
        if row is None:
            raise RelationshipError(
                "Every relationship evidence observation must belong to the supplied run."
            )
        if row["observation_type"] != rule["observation_type"]:
            raise RelationshipError(
                f"Rule {rule['rule_id']!r} requires {rule['observation_type']!r} evidence."
            )
        observations.append(row)

    return observations


def propose_relationship(
    connection: sqlite3.Connection,
    proposal: RelationshipProposal,
) -> RelationshipResult:
    """Create an idempotent, evidence-linked relationship using a registered rule.

    Corroboration requires supporting observations from at least two distinct
    source definitions. Contradicting evidence is retained and prevents automatic
    corroboration. A static vendor/API reference is never described as a working
    integration or reachable endpoint.
    """
    _canonical_uuid(proposal.run_id, "run_id")
    _canonical_uuid(proposal.subject_entity_id, "subject_entity_id")
    _canonical_uuid(proposal.object_entity_id, "object_entity_id")
    if proposal.subject_entity_id == proposal.object_entity_id:
        raise RelationshipError("Self-relationships are not permitted.")
    if connection.in_transaction:
        raise PersistenceError("Relationship correlation requires its own transaction.")

    try:
        with transaction(connection, immediate=True):
            rule = _load_rule(connection, proposal.rule_id)
            subject = connection.execute(
                "SELECT entity_type, canonical_key FROM entity WHERE entity_id = ?",
                (proposal.subject_entity_id,),
            ).fetchone()
            object_entity = connection.execute(
                "SELECT entity_type, canonical_key FROM entity WHERE entity_id = ?",
                (proposal.object_entity_id,),
            ).fetchone()
            if subject is None or object_entity is None:
                raise RelationshipError("Both relationship endpoint entities must exist.")
            if subject["entity_type"] not in json.loads(rule["subject_entity_types_json"]):
                raise RelationshipError("Subject entity type is not permitted by this rule.")
            if object_entity["entity_type"] not in json.loads(rule["object_entity_types_json"]):
                raise RelationshipError("Object entity type is not permitted by this rule.")

            observations = _source_evidence(connection, proposal, rule)
            evidence_roles = {item.observation_id: item.evidence_role for item in proposal.evidence}
            for observation in observations:
                role = evidence_roles[observation["observation_id"]]
                if role == "context":
                    continue
                attributes = json.loads(observation["attributes_json"] or "{}")
                endpoint_ids = {
                    observation["subject_entity_id"],
                    attributes.get("subject_entity_id"),
                    attributes.get("object_entity_id"),
                }
                endpoint_ids.discard(None)
                if not endpoint_ids.intersection(
                    {proposal.subject_entity_id, proposal.object_entity_id}
                ):
                    raise RelationshipError(
                        "Evidence must be explicitly anchored to at least one "
                        "relationship endpoint."
                    )

                if rule["rule_id"] == "domain_has_nameserver":
                    parent_domain = attributes.get("domain")
                    value_matches = (
                        observation["observed_value"].casefold()
                        == object_entity["canonical_key"].casefold()
                    )
                    if parent_domain != subject["canonical_key"]:
                        raise RelationshipError(
                            "RDAP nameserver evidence does not match the proposed subject domain."
                        )
                    if role == "supports" and not value_matches:
                        raise RelationshipError(
                            f"Supporting RDAP value {observation['observed_value']!r} does not match "
                            f"hostname key {object_entity['canonical_key']!r}."
                        )
                    if role == "contradicts" and value_matches:
                        raise RelationshipError(
                            "Contradicting evidence cannot repeat the asserted nameserver value."
                        )
                elif rule["rule_id"] in {
                    "website_references_vendor",
                    "website_references_api_endpoint",
                    "website_references_api_documentation",
                }:
                    value_matches = (
                        observation["observed_value"].casefold()
                        == object_entity["canonical_key"].casefold()
                    )
                    if role == "supports" and not value_matches:
                        raise RelationshipError(
                            "Supporting static reference does not match the proposed object."
                        )
                    if role == "contradicts" and value_matches:
                        raise RelationshipError(
                            "Contradicting evidence cannot repeat the asserted reference."
                        )

            support_sources = {
                row["source_id"]
                for row in observations
                if evidence_roles[row["observation_id"]] == "supports"
            }
            support_count = sum(1 for role in evidence_roles.values() if role == "supports")
            contradict_count = sum(
                1 for role in evidence_roles.values() if role == "contradicts"
            )
            confidence = float(rule["base_confidence"])
            state = rule["default_state"]
            if len(support_sources) >= 2 and contradict_count == 0 and state == "observed":
                state = "corroborated"
                confidence = min(0.99, confidence + 0.10)
            elif contradict_count:
                state = "unverified"
                confidence = max(0.0, confidence - 0.20)

            rationale_parts = [
                rule["description"],
                f"Supporting source definitions: {len(support_sources)}.",
                f"Supporting observations: {support_count}.",
                f"Contradicting observations: {contradict_count}.",
            ]
            if len(support_sources) < 2 and state == "observed":
                rationale_parts.append(
                    "Independent corroboration threshold not met; this remains "
                    "observed, not corroborated."
                )
            if contradict_count:
                rationale_parts.append(
                    "Contradicting evidence is retained; the relationship is unverified."
                )
            if proposal.rationale:
                rationale_parts.append(proposal.rationale.strip())
            rationale = " ".join(rationale_parts)

            evidence_identity = "|".join(
                f"{item.observation_id}:{item.evidence_role}"
                for item in sorted(
                    proposal.evidence,
                    key=lambda item: (item.observation_id, item.evidence_role),
                )
            )
            relationship_id = str(
                uuid.uuid5(
                    RELATIONSHIP_NAMESPACE,
                    "|".join(
                        (
                            proposal.run_id,
                            proposal.rule_id,
                            rule["rule_version"],
                            proposal.subject_entity_id,
                            rule["predicate"],
                            proposal.object_entity_id,
                            evidence_identity,
                        )
                    ),
                )
            )
            existing = connection.execute(
                "SELECT * FROM relationship WHERE relationship_id = ?",
                (relationship_id,),
            ).fetchone()
            inserted = existing is None
            if existing is None:
                timestamp = _now()
                connection.execute(
                    """
                    INSERT INTO relationship (
                        relationship_id, subject_entity_id, predicate, object_entity_id,
                        verification_state, confidence, rationale, rule_id, rule_version,
                        first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        relationship_id,
                        proposal.subject_entity_id,
                        rule["predicate"],
                        proposal.object_entity_id,
                        state,
                        confidence,
                        rationale,
                        proposal.rule_id,
                        rule["rule_version"],
                        timestamp,
                        timestamp,
                    ),
                )
                for item in sorted(
                    proposal.evidence,
                    key=lambda item: (item.observation_id, item.evidence_role),
                ):
                    connection.execute(
                        """
                        INSERT INTO relationship_evidence (
                            relationship_id, observation_id, evidence_role
                        ) VALUES (?, ?, ?)
                        """,
                        (relationship_id, item.observation_id, item.evidence_role),
                    )
            else:
                expected = (
                    proposal.subject_entity_id,
                    rule["predicate"],
                    proposal.object_entity_id,
                    proposal.rule_id,
                )
                actual = (
                    existing["subject_entity_id"],
                    existing["predicate"],
                    existing["object_entity_id"],
                    existing["rule_id"],
                )
                if actual != expected:
                    raise PersistenceError("Deterministic relationship ID collision detected.")

            return RelationshipResult(
                relationship_id=relationship_id,
                predicate=rule["predicate"],
                verification_state=state if inserted else existing["verification_state"],
                confidence=confidence if inserted else float(existing["confidence"] or 0.0),
                rationale=rationale if inserted else existing["rationale"],
                supporting_source_count=len(support_sources),
                supporting_observation_count=support_count,
                contradicting_observation_count=contradict_count,
                inserted=inserted,
            )
    except (sqlite3.Error, TypeError, ValueError, KeyError) as exc:
        if isinstance(exc, (RelationshipError, PersistenceError)):
            raise
        raise PersistenceError("Unable to persist the evidence-backed relationship.") from exc


def review_relationship(
    connection: sqlite3.Connection,
    *,
    relationship_id: str,
    disposition: str,
    reviewer_label: str,
    rationale: str,
    reviewed_at: str | None = None,
) -> RelationshipReviewResult:
    """Append an analyst decision; acceptance never upgrades evidence confidence."""
    _canonical_uuid(relationship_id, "relationship_id")
    if disposition not in {"accepted", "rejected", "needs_research"}:
        raise RelationshipError("Disposition must be accepted, rejected or needs_research.")
    if not isinstance(reviewer_label, str) or not reviewer_label.strip():
        raise RelationshipError("Reviewer label is required.")
    if not isinstance(rationale, str) or not rationale.strip():
        raise RelationshipError("Review rationale is required.")
    timestamp = reviewed_at or _now()
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RelationshipError("Review timestamp must be ISO-8601.") from exc
    if connection.in_transaction:
        raise PersistenceError("Relationship review requires its own transaction.")

    review_id = str(
        uuid.uuid5(
            REVIEW_NAMESPACE,
            (
                f"{relationship_id}|{disposition}|{reviewer_label.strip()}|"
                f"{rationale.strip()}|{timestamp}"
            ),
        )
    )
    try:
        with transaction(connection, immediate=True):
            row = connection.execute(
                "SELECT verification_state FROM relationship WHERE relationship_id = ?",
                (relationship_id,),
            ).fetchone()
            if row is None:
                raise RelationshipError("Relationship to review does not exist.")
            prior_state = row["verification_state"]
            resulting_state = "rejected" if disposition == "rejected" else prior_state
            existing = connection.execute(
                "SELECT * FROM relationship_review WHERE review_id = ?", (review_id,)
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO relationship_review (
                        review_id, relationship_id, disposition, reviewer_label, rationale,
                        prior_verification_state, resulting_verification_state, reviewed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        review_id,
                        relationship_id,
                        disposition,
                        reviewer_label.strip(),
                        rationale.strip(),
                        prior_state,
                        resulting_state,
                        timestamp,
                    ),
                )
                if resulting_state != prior_state:
                    connection.execute(
                        "UPDATE relationship SET verification_state = ? WHERE relationship_id = ?",
                        (resulting_state, relationship_id),
                    )
            else:
                resulting_state = existing["resulting_verification_state"]
            return RelationshipReviewResult(
                review_id=review_id,
                relationship_id=relationship_id,
                disposition=disposition,
                verification_state=resulting_state,
                reviewed_at=timestamp,
            )
    except (sqlite3.Error, TypeError, ValueError) as exc:
        if isinstance(exc, (RelationshipError, PersistenceError)):
            raise
        raise PersistenceError("Unable to persist the relationship analyst review.") from exc


def list_relationship_review_queue(
    connection: sqlite3.Connection,
    *,
    limit: int = 100,
) -> tuple[RelationshipQueueItem, ...]:
    """Return relationships without a final analyst disposition."""
    if isinstance(limit, bool) or limit < 1 or limit > 1000:
        raise ValueError("Review queue limit must be between 1 and 1000.")
    try:
        rows = connection.execute(
            """
            SELECT r.relationship_id, r.subject_entity_id, s.display_name AS subject_name,
                   r.predicate, r.object_entity_id, o.display_name AS object_name,
                   r.verification_state, r.confidence, r.rationale,
                   latest.disposition AS latest_disposition
            FROM relationship AS r
            JOIN entity AS s ON s.entity_id = r.subject_entity_id
            JOIN entity AS o ON o.entity_id = r.object_entity_id
            LEFT JOIN (
                SELECT rr.relationship_id, rr.disposition
                FROM relationship_review AS rr
                WHERE rr.review_id = (
                    SELECT rr2.review_id FROM relationship_review AS rr2
                    WHERE rr2.relationship_id = rr.relationship_id
                    ORDER BY rr2.reviewed_at DESC, rr2.review_id DESC LIMIT 1
                )
            ) AS latest ON latest.relationship_id = r.relationship_id
            WHERE latest.disposition IS NULL OR latest.disposition = 'needs_research'
            ORDER BY r.first_seen_at, r.relationship_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    except sqlite3.Error as exc:
        raise PersistenceError("Unable to read the relationship analyst review queue.") from exc
    return tuple(
        RelationshipQueueItem(
            relationship_id=row["relationship_id"],
            subject_entity_id=row["subject_entity_id"],
            subject_name=row["subject_name"],
            predicate=row["predicate"],
            object_entity_id=row["object_entity_id"],
            object_name=row["object_name"],
            verification_state=row["verification_state"],
            confidence=row["confidence"],
            rationale=row["rationale"],
            latest_disposition=row["latest_disposition"],
        )
        for row in rows
    )
