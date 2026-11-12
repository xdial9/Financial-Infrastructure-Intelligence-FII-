"""Transactional persistence for canonical observations and source provenance."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from fii.normalization.observations import CanonicalObservation, ObservationProvenance
from fii.storage.database import PersistenceError, transaction


@dataclass(frozen=True)
class DeduplicationPersistenceResult:
    """Counts for a canonical-observation persistence operation."""

    inserted_observations: int
    reused_observations: int
    inserted_source_links: int
    inserted_provenance_records: int


def _insert_provenance(
    connection: sqlite3.Connection,
    observation_id: str,
    run_id: str,
    provenance: ObservationProvenance,
) -> bool:
    existing = connection.execute(
        """
        SELECT provenance_id FROM observation_provenance
        WHERE observation_id = ? AND source_execution_id = ? AND raw_sha256 = ?
        """,
        (observation_id, provenance.source_execution_id, provenance.raw_sha256),
    ).fetchone()
    if existing is not None:
        return False

    connection.execute(
        """
        INSERT INTO observation_provenance (
            provenance_id, observation_id, source_execution_id, run_id,
            provenance_role, source_url, raw_evidence_path, raw_sha256,
            collected_at, observed_at, attributes_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            provenance.provenance_id,
            observation_id,
            provenance.source_execution_id,
            run_id,
            provenance.provenance_role,
            provenance.source_url,
            provenance.raw_evidence_path,
            provenance.raw_sha256,
            provenance.collected_at,
            provenance.observed_at,
            json.dumps(
                provenance.attributes,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        ),
    )
    return True


def persist_canonical_observations(
    connection: sqlite3.Connection,
    observations: Iterable[CanonicalObservation],
) -> DeduplicationPersistenceResult:
    """Insert canonical facts once and attach every source/evidence contribution.

    Secondary sources are recorded with the context role. This preserves their
    provenance without automatically declaring independent corroboration.
    """
    values = tuple(observations)
    if not values:
        return DeduplicationPersistenceResult(0, 0, 0, 0)
    if connection.in_transaction:
        raise PersistenceError("Canonical observation persistence requires its own transaction.")

    inserted = 0
    reused = 0
    links_added = 0
    provenance_added = 0

    try:
        with transaction(connection, immediate=True):
            seen_keys: set[tuple[str, str]] = set()
            for item in values:
                identity = (item.run_id, item.deduplication_key)
                if identity in seen_keys:
                    raise PersistenceError(
                        "A persistence batch contains duplicate canonical keys."
                    )
                seen_keys.add(identity)

                for source in item.provenance:
                    execution = connection.execute(
                        """
                        SELECT source_execution_id FROM source_execution
                        WHERE source_execution_id = ? AND run_id = ?
                        """,
                        (source.source_execution_id, item.run_id),
                    ).fetchone()
                    if execution is None:
                        raise PersistenceError(
                            "Observation provenance references a source execution "
                            "outside the observation run."
                        )

                existing = connection.execute(
                    """
                    SELECT observation_id, source_execution_id, observation_type, observed_value
                    FROM observation
                    WHERE run_id = ? AND deduplication_key = ?
                    """,
                    (item.run_id, item.deduplication_key),
                ).fetchone()

                if existing is None:
                    connection.execute(
                        """
                        INSERT INTO observation (
                            observation_id, run_id, source_execution_id,
                            observation_type, observed_value, observed_at,
                            collected_at, source_url, raw_evidence_path, raw_sha256,
                            verification_state, attributes_json, deduplication_key,
                            canonicalization_version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item.observation_id,
                            item.run_id,
                            item.source_execution_id,
                            item.observation_type,
                            item.observed_value,
                            item.observed_at,
                            item.collected_at,
                            item.source_url,
                            item.raw_evidence_path,
                            item.raw_sha256,
                            item.verification_state,
                            json.dumps(
                                item.attributes,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                                allow_nan=False,
                            ),
                            item.deduplication_key,
                            item.canonicalization_version,
                        ),
                    )
                    inserted += 1
                else:
                    if (
                        existing["observation_type"] != item.observation_type
                        or existing["observed_value"].casefold() != item.observed_value.casefold()
                    ):
                        raise PersistenceError(
                            "A stored deduplication key points to a different canonical fact."
                        )
                    reused += 1
                    item_observation_id = existing["observation_id"]

                observation_id = (
                    item.observation_id if existing is None else item_observation_id
                )
                primary_source_execution_id = (
                    item.source_execution_id
                    if existing is None
                    else existing["source_execution_id"]
                )

                for source in item.provenance:
                    source_link = connection.execute(
                        """
                        SELECT provenance_role FROM observation_source_link
                        WHERE observation_id = ? AND source_execution_id = ?
                        """,
                        (observation_id, source.source_execution_id),
                    ).fetchone()
                    if source_link is None:
                        connection.execute(
                            """
                            INSERT INTO observation_source_link (
                                observation_id, source_execution_id, run_id, provenance_role
                            ) VALUES (?, ?, ?, 'context')
                            """,
                            (observation_id, source.source_execution_id, item.run_id),
                        )
                        links_added += 1

                    role = (
                        "primary"
                        if source.source_execution_id == primary_source_execution_id
                        and source.raw_sha256 == item.raw_sha256
                        else "context"
                    )
                    provenance_record = ObservationProvenance(
                        provenance_id=str(
                            uuid.uuid5(
                                uuid.UUID(observation_id),
                                f"{source.source_execution_id}:{source.raw_sha256}:"
                                f"{source.source_url or ''}:{source.raw_evidence_path or ''}",
                            )
                        ),
                        source_execution_id=source.source_execution_id,
                        source_url=source.source_url,
                        raw_evidence_path=source.raw_evidence_path,
                        raw_sha256=source.raw_sha256,
                        collected_at=source.collected_at,
                        observed_at=source.observed_at,
                        attributes=source.attributes,
                        provenance_role=role,
                    )
                    if _insert_provenance(
                        connection,
                        observation_id,
                        item.run_id,
                        provenance_record,
                    ):
                        provenance_added += 1

    except PersistenceError:
        raise
    except (sqlite3.Error, TypeError, ValueError) as exc:
        raise PersistenceError(
            "Unable to persist canonical observations and provenance."
        ) from exc

    return DeduplicationPersistenceResult(
        inserted_observations=inserted,
        reused_observations=reused,
        inserted_source_links=links_added,
        inserted_provenance_records=provenance_added,
    )
