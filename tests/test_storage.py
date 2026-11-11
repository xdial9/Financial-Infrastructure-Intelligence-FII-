"""Offline tests for the versioned SQLite evidence store."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from fii.storage.database import (
    PersistenceError,
    assert_integrity,
    backup_database,
    check_integrity,
    connect_database,
    initialize_database,
    migrate_database,
    transaction,
)


def _id() -> str:
    return str(uuid4())


def _seed_run(connection: sqlite3.Connection) -> dict[str, str]:
    values = {
        "engagement_id": _id(),
        "run_id": _id(),
        "source_id": "synthetic_fixture",
        "source_execution_id": _id(),
        "now": "2026-01-01T00:00:00Z",
    }
    with transaction(connection):
        connection.execute(
            """
            INSERT INTO engagement (
                engagement_id, slug, display_name, config_path, scope_json,
                created_at, updated_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                values["engagement_id"],
                "synthetic-" + values["engagement_id"][:8],
                "Synthetic engagement",
                "config/effective.yaml",
                '{"seed_domains":["example.invalid"]}',
                values["now"],
                values["now"],
            ),
        )
        connection.execute(
            """
            INSERT INTO run (
                run_id, engagement_id, started_at, status, config_digest,
                software_version, scope_digest
            ) VALUES (?, ?, ?, 'running', ?, ?, ?)
            """,
            (
                values["run_id"],
                values["engagement_id"],
                values["now"],
                "a" * 64,
                "0.1.0",
                "b" * 64,
            ),
        )
        connection.execute(
            """
            INSERT INTO source_definition (
                source_id, name, adapter_version, source_class, default_enabled
            ) VALUES (?, ?, ?, 'public_dataset', 1)
            """,
            (values["source_id"], "Synthetic fixture", "1.0.0"),
        )
        connection.execute(
            """
            INSERT INTO source_execution (
                source_execution_id, run_id, source_id, attempt_number, status,
                started_at, records_received, records_accepted
            ) VALUES (?, ?, ?, 1, 'success', ?, 1, 1)
            """,
            (
                values["source_execution_id"],
                values["run_id"],
                values["source_id"],
                values["now"],
            ),
        )
    return values


def _insert_observation(
    connection: sqlite3.Connection,
    values: dict[str, str],
    *,
    observation_id: str | None = None,
    deduplication_key: str = "domain:example.invalid",
) -> str:
    observation_id = observation_id or _id()
    connection.execute(
        """
        INSERT INTO observation (
            observation_id, run_id, source_execution_id, observation_type,
            observed_value, collected_at, verification_state, deduplication_key
        ) VALUES (?, ?, ?, 'domain_seen', 'example.invalid', ?, 'observed', ?)
        """,
        (
            observation_id,
            values["run_id"],
            values["source_execution_id"],
            values["now"],
            deduplication_key,
        ),
    )
    return observation_id


def test_empty_database_creation_and_versioned_idempotent_migrations(tmp_path: Path) -> None:
    database = tmp_path / "database" / "fii.sqlite3"
    database.parent.mkdir()

    assert initialize_database(database) == 1
    connection = connect_database(database)
    try:
        first = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations"
        ).fetchall()
        assert len(first) == 1
        assert first[0]["version"] == 1
        assert first[0]["name"] == "initial"

        assert migrate_database(connection) == 1
        second = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations"
        ).fetchall()
        assert [tuple(row) for row in first] == [tuple(row) for row in second]

        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "engagement",
            "run",
            "stage_attempt",
            "source_definition",
            "source_execution",
            "observation",
            "observation_source_link",
            "entity",
            "entity_identifier",
            "relationship",
            "relationship_evidence",
            "finding",
            "finding_evidence",
        } <= tables
    finally:
        connection.close()


def test_every_connection_enables_foreign_keys(tmp_path: Path) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)

    first = connect_database(database)
    second = connect_database(database)
    try:
        assert first.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert second.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        first.close()
        second.close()


def test_foreign_key_enforcement_rejects_orphan_run(tmp_path: Path) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        with pytest.raises(PersistenceError):
            with transaction(connection):
                connection.execute(
                    """
                    INSERT INTO run (
                        run_id, engagement_id, started_at, status, config_digest,
                        software_version, scope_digest
                    ) VALUES (?, ?, ?, 'running', ?, ?, ?)
                    """,
                    (_id(), _id(), "2026-01-01T00:00:00Z", "a" * 64, "0.1.0", "b" * 64),
                )
    finally:
        connection.close()


def test_constraints_protect_deduplication_and_entity_identity(tmp_path: Path) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        values = _seed_run(connection)
        with transaction(connection):
            _insert_observation(connection, values)
        with pytest.raises(PersistenceError):
            with transaction(connection):
                _insert_observation(connection, values)

        now = values["now"]
        with transaction(connection):
            connection.execute(
                """
                INSERT INTO entity (
                    entity_id, entity_type, canonical_key, display_name, created_at, updated_at
                ) VALUES (?, 'domain', 'example.invalid', 'example.invalid', ?, ?)
                """,
                (_id(), now, now),
            )
        with pytest.raises(PersistenceError):
            with transaction(connection):
                connection.execute(
                    """
                    INSERT INTO entity (
                        entity_id, entity_type, canonical_key, display_name, created_at, updated_at
                    ) VALUES (?, 'domain', 'example.invalid', 'Duplicate', ?, ?)
                    """,
                    (_id(), now, now),
                )
    finally:
        connection.close()


def test_observation_links_primary_and_additional_source_provenance(tmp_path: Path) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        values = _seed_run(connection)
        with transaction(connection):
            observation_id = _insert_observation(connection, values)
            connection.execute(
                """
                INSERT INTO source_definition (
                    source_id, name, adapter_version, source_class
                ) VALUES ('synthetic_second', 'Second fixture', '1.0.0', 'public_dataset')
                """
            )
            second_execution = _id()
            connection.execute(
                """
                INSERT INTO source_execution (
                    source_execution_id, run_id, source_id, attempt_number, status
                ) VALUES (?, ?, 'synthetic_second', 1, 'success')
                """,
                (second_execution, values["run_id"]),
            )
            connection.execute(
                """
                INSERT INTO observation_source_link (
                    observation_id, source_execution_id, run_id, provenance_role
                ) VALUES (?, ?, ?, 'corroborating')
                """,
                (observation_id, second_execution, values["run_id"]),
            )

        links = connection.execute(
            """
            SELECT source_execution_id, provenance_role
            FROM observation_source_link WHERE observation_id = ?
            ORDER BY provenance_role
            """,
            (observation_id,),
        ).fetchall()
        assert {(row["source_execution_id"], row["provenance_role"]) for row in links} == {
            (values["source_execution_id"], "primary"),
            (second_execution, "corroborating"),
        }
    finally:
        connection.close()


def test_relationship_and_finding_evidence_constraints(tmp_path: Path) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        values = _seed_run(connection)
        now = values["now"]
        entity_a, entity_b = _id(), _id()
        with transaction(connection):
            connection.execute(
                """
                INSERT INTO entity (
                    entity_id, entity_type, canonical_key, display_name, created_at, updated_at
                ) VALUES (?, 'organization', 'synthetic-a', 'Synthetic A', ?, ?)
                """,
                (entity_a, now, now),
            )
            connection.execute(
                """
                INSERT INTO entity (
                    entity_id, entity_type, canonical_key, display_name, created_at, updated_at
                ) VALUES (?, 'organization', 'synthetic-b', 'Synthetic B', ?, ?)
                """,
                (entity_b, now, now),
            )
            observation_id = _insert_observation(connection, values)
            relationship_id = _id()
            connection.execute(
                """
                INSERT INTO relationship (
                    relationship_id, subject_entity_id, predicate, object_entity_id,
                    verification_state, rationale
                ) VALUES (?, ?, 'references', ?, 'observed', 'Synthetic fixture evidence')
                """,
                (relationship_id, entity_a, entity_b),
            )

        finding_id = _id()
        with transaction(connection):
            connection.execute(
                """
                INSERT INTO finding (
                    finding_id, run_id, finding_type, title, description,
                    verification_state, rationale, created_at, updated_at
                ) VALUES (?, ?, 'research_lead', 'Synthetic finding',
                          'A fixture-backed relationship.', 'candidate', ?, ?, ?)
                """,
                (finding_id, values["run_id"], "Synthetic rationale", now, now),
            )

        with pytest.raises(PersistenceError):
            with transaction(connection):
                connection.execute(
                    """
                    INSERT INTO finding_evidence (
                        finding_evidence_id, finding_id, run_id, relationship_id, evidence_role
                    ) VALUES (?, ?, ?, ?, 'supports')
                    """,
                    (_id(), finding_id, values["run_id"], relationship_id),
                )

        with transaction(connection):
            connection.execute(
                """
                INSERT INTO relationship_evidence (
                    relationship_id, observation_id, evidence_role
                ) VALUES (?, ?, 'supports')
                """,
                (relationship_id, observation_id),
            )
            connection.execute(
                """
                INSERT INTO finding_evidence (
                    finding_evidence_id, finding_id, run_id, relationship_id, evidence_role
                ) VALUES (?, ?, ?, ?, 'supports')
                """,
                (_id(), finding_id, values["run_id"], relationship_id),
            )

        with pytest.raises(PersistenceError):
            with transaction(connection):
                connection.execute(
                    """
                    INSERT INTO finding_evidence (
                        finding_evidence_id, finding_id, run_id, evidence_role
                    ) VALUES (?, ?, ?, 'supports')
                    """,
                    (_id(), finding_id, values["run_id"]),
                )

        with pytest.raises(PersistenceError):
            with transaction(connection):
                connection.execute(
                    """
                    INSERT INTO relationship (
                        relationship_id, subject_entity_id, predicate, object_entity_id,
                        verification_state
                    ) VALUES (?, ?, 'self_link', ?, 'inferred')
                    """,
                    (_id(), entity_a, entity_a),
                )
    finally:
        connection.close()


def test_transaction_rolls_back_application_exception(tmp_path: Path) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        with pytest.raises(RuntimeError, match="abort fixture"):
            with transaction(connection):
                connection.execute(
                    """
                    INSERT INTO engagement (
                        engagement_id, slug, display_name, config_path, scope_json,
                        created_at, updated_at, status
                    ) VALUES (?, 'rollback-fixture', 'Rollback', 'config.yaml', '{}', ?, ?, 'active')
                    """,
                    (_id(), "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
                )
                raise RuntimeError("abort fixture")

        assert connection.execute(
            "SELECT 1 FROM engagement WHERE slug = 'rollback-fixture'"
        ).fetchone() is None
    finally:
        connection.close()


def test_integrity_check_and_backup_restore(tmp_path: Path) -> None:
    database = tmp_path / "fii.sqlite3"
    backup = tmp_path / "backups" / "fii-backup.sqlite3"
    backup.parent.mkdir()
    initialize_database(database)

    connection = connect_database(database)
    try:
        values = _seed_run(connection)
        with transaction(connection):
            _insert_observation(connection, values)
        assert assert_integrity(connection).ok
    finally:
        connection.close()

    assert backup_database(database, backup) == backup
    restored = connect_database(backup)
    try:
        assert check_integrity(restored).ok
        assert restored.execute("SELECT COUNT(*) FROM observation").fetchone()[0] == 1
        assert restored.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
    finally:
        restored.close()

    with pytest.raises(PersistenceError, match="already exists"):
        backup_database(database, backup)


def test_persistence_failures_are_not_silently_accepted(tmp_path: Path) -> None:
    with pytest.raises(PersistenceError, match="Unable to open"):
        connect_database(tmp_path / "missing-parent" / "fii.sqlite3")

    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        with pytest.raises(PersistenceError, match="transaction failed"):
            with transaction(connection):
                connection.execute(
                    """
                    INSERT INTO engagement (
                        engagement_id, slug, display_name, config_path, scope_json,
                        created_at, updated_at, status
                    ) VALUES (?, 'invalid-status', 'Invalid', 'config.yaml', '{}', ?, ?, 'unknown')
                    """,
                    (_id(), "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
                )
        assert connection.execute(
            "SELECT 1 FROM engagement WHERE slug = 'invalid-status'"
        ).fetchone() is None
    finally:
        connection.close()


def test_newer_database_schema_is_not_downgraded(tmp_path: Path) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        with transaction(connection):
            connection.execute(
                """
                INSERT INTO schema_migrations (version, name, checksum, applied_at)
                VALUES (99, 'future', ?, '2026-01-01T00:00:00Z')
                """,
                ("f" * 64,),
            )
        with pytest.raises(PersistenceError, match="newer than this FII release"):
            migrate_database(connection)
    finally:
        connection.close()
