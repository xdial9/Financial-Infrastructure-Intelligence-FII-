"""Synthetic offline tests for relationship correlation and analyst review."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from fii.relationships.correlation import (
    RelationshipError,
    RelationshipEvidence,
    RelationshipProposal,
    list_relationship_review_queue,
    propose_relationship,
    review_relationship,
)
from fii.storage.database import (
    PersistenceError,
    connect_database,
    initialize_database,
    transaction,
)


def _id() -> str:
    return str(uuid4())


def _seed(connection: sqlite3.Connection) -> dict[str, str]:
    values = {
        "engagement": _id(),
        "run": _id(),
        "domain": _id(),
        "hostname": _id(),
        "vendor": _id(),
        "source_a": _id(),
        "source_b": _id(),
        "execution_a": _id(),
        "execution_b": _id(),
        "observation_a": _id(),
        "observation_b": _id(),
        "observation_vendor": _id(),
        "now": "2026-01-01T00:00:00Z",
    }
    with transaction(connection):
        connection.execute(
            """
            INSERT INTO engagement (
                engagement_id, slug, display_name, config_path, scope_json,
                created_at, updated_at, status
            ) VALUES (?, ?, 'Synthetic FII', 'config.yaml', '{}', ?, ?, 'active')
            """,
            (values["engagement"], "synthetic-" + values["engagement"][:8],
             values["now"], values["now"]),
        )
        connection.execute(
            """
            INSERT INTO run (
                run_id, engagement_id, started_at, status, config_digest,
                software_version, scope_digest
            ) VALUES (?, ?, ?, 'running', ?, '0.1.0', ?)
            """,
            (values["run"], values["engagement"], values["now"], "a" * 64, "b" * 64),
        )
        for source_id, execution_id, observation_id, source_name in (
            ("fixture_rdap_a", values["execution_a"], values["observation_a"], "Fixture A"),
            ("fixture_rdap_b", values["execution_b"], values["observation_b"], "Fixture B"),
        ):
            connection.execute(
                """
                INSERT INTO source_definition (
                    source_id, name, adapter_version, source_class
                ) VALUES (?, ?, '1.0.0', 'public_dataset')
                """,
                (source_id, source_name),
            )
            connection.execute(
                """
                INSERT INTO source_execution (
                    source_execution_id, run_id, source_id, attempt_number, status,
                    started_at, records_received, records_accepted
                ) VALUES (?, ?, ?, 1, 'success', ?, 1, 1)
                """,
                (execution_id, values["run"], source_id, values["now"]),
            )
        connection.execute(
            """
            INSERT INTO entity (
                entity_id, entity_type, canonical_key, display_name, created_at, updated_at
            ) VALUES (?, 'domain', 'example.invalid', 'example.invalid', ?, ?)
            """,
            (values["domain"], values["now"], values["now"]),
        )
        connection.execute(
            """
            INSERT INTO entity (
                entity_id, entity_type, canonical_key, display_name, created_at, updated_at
            ) VALUES (?, 'hostname', 'ns1.example.invalid', 'ns1.example.invalid', ?, ?)
            """,
            (values["hostname"], values["now"], values["now"]),
        )
        connection.execute(
            """
            INSERT INTO entity (
                entity_id, entity_type, canonical_key, display_name, created_at, updated_at
            ) VALUES (?, 'vendor', 'plaid', 'Plaid', ?, ?)
            """,
            (values["vendor"], values["now"], values["now"]),
        )
        for execution_id, observation_id in (
            (values["execution_a"], values["observation_a"]),
            (values["execution_b"], values["observation_b"]),
        ):
            connection.execute(
                """
                INSERT INTO observation (
                    observation_id, run_id, source_execution_id, subject_entity_id,
                    observation_type, observed_value, collected_at, verification_state,
                    attributes_json
                ) VALUES (?, ?, ?, ?, 'rdap_nameserver', ?, ?,
                          'observed', '{"domain":"example.invalid"}')
                """,
                (observation_id, values["run"], execution_id, values["domain"],
                "ns1.example.invalid",
                 values["now"]),
            )
        connection.execute(
            """
            INSERT INTO observation (
                observation_id, run_id, source_execution_id, subject_entity_id,
                observation_type, observed_value, collected_at, verification_state,
                attributes_json
            ) VALUES (?, ?, ?, ?, 'integration_reference', 'Plaid', ?,
                      'observed', '{"signal_type":"static_reference"}')
            """,
            (
                values["observation_vendor"], values["run"], values["execution_a"],
                values["domain"], values["now"],
            ),
        )
    return values


def _proposal(
    values: dict[str, str], evidence: tuple[RelationshipEvidence, ...]
) -> RelationshipProposal:
    return RelationshipProposal(
        run_id=values["run"],
        rule_id="domain_has_nameserver",
        subject_entity_id=values["domain"],
        object_entity_id=values["hostname"],
        evidence=evidence,
    )


def test_typed_rule_creates_idempotent_evidence_linked_relationship(tmp_path: Path) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        values = _seed(connection)
        proposal = _proposal(values, (RelationshipEvidence(values["observation_a"]),))
        first = propose_relationship(connection, proposal)
        second = propose_relationship(connection, proposal)
        assert first.inserted is True
        assert second.inserted is False
        assert first.relationship_id == second.relationship_id
        assert first.predicate == "has_nameserver"
        assert first.verification_state == "observed"
        assert first.confidence == 0.9
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_evidence WHERE relationship_id = ?",
            (first.relationship_id,),
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_independent_source_definitions_are_required_for_corroboration(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        values = _seed(connection)
        result = propose_relationship(
            connection,
            _proposal(
                values,
                (
                    RelationshipEvidence(values["observation_a"]),
                    RelationshipEvidence(values["observation_b"]),
                ),
            ),
        )
        assert result.verification_state == "corroborated"
        assert result.supporting_source_count == 2
        assert result.confidence == 0.99
    finally:
        connection.close()


def test_contradicting_evidence_is_retained_and_prevents_corroboration(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        values = _seed(connection)
        with transaction(connection):
            connection.execute(
                "UPDATE observation SET observed_value = 'ns2.example.invalid' "
                "WHERE observation_id = ?",
                (values["observation_b"],),
            )
        result = propose_relationship(
            connection,
            _proposal(
                values,
                (
                    RelationshipEvidence(values["observation_a"], "supports"),
                    RelationshipEvidence(values["observation_b"], "contradicts"),
                ),
            ),
        )
        assert result.verification_state == "unverified"
        assert result.contradicting_observation_count == 1
        roles = {
            row["evidence_role"]
            for row in connection.execute(
                "SELECT evidence_role FROM relationship_evidence WHERE relationship_id = ?",
                (result.relationship_id,),
            )
        }
        assert roles == {"supports", "contradicts"}
    finally:
        connection.close()


def test_rule_rejects_wrong_entity_types_and_unanchored_or_wrong_run_evidence(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        values = _seed(connection)
        with pytest.raises(RelationshipError, match="Subject entity type"):
            propose_relationship(
                connection,
                RelationshipProposal(
                    run_id=values["run"],
                    rule_id="domain_has_nameserver",
                    subject_entity_id=values["hostname"],
                    object_entity_id=values["domain"],
                    evidence=(RelationshipEvidence(values["observation_a"]),),
                ),
            )
        with pytest.raises(RelationshipError, match="requires 'integration_reference'"):
            propose_relationship(
                connection,
                RelationshipProposal(
                    run_id=values["run"],
                    rule_id="website_references_vendor",
                    subject_entity_id=values["domain"],
                    object_entity_id=values["vendor"],
                    evidence=(RelationshipEvidence(values["observation_a"]),),
                ),
            )
    finally:
        connection.close()


def test_analyst_review_is_append_only_and_does_not_upgrade_confidence(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        values = _seed(connection)
        relationship = propose_relationship(
            connection,
            _proposal(values, (RelationshipEvidence(values["observation_a"]),)),
        )
        reviewed = review_relationship(
            connection,
            relationship_id=relationship.relationship_id,
            disposition="accepted",
            reviewer_label="analyst-fixture",
            rationale="Reviewed synthetic RDAP fixture evidence.",
            reviewed_at="2026-01-02T00:00:00Z",
        )
        assert reviewed.verification_state == "observed"
        assert connection.execute(
            "SELECT verification_state FROM relationship WHERE relationship_id = ?",
            (relationship.relationship_id,),
        ).fetchone()[0] == "observed"
        assert list_relationship_review_queue(connection) == ()

        with pytest.raises(PersistenceError):
            with transaction(connection):
                connection.execute(
                    "UPDATE relationship_review SET rationale = 'rewritten' WHERE review_id = ?",
                    (reviewed.review_id,),
                )
    finally:
        connection.close()


def test_rejection_changes_state_but_preserves_review_history(tmp_path: Path) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        values = _seed(connection)
        relationship = propose_relationship(
            connection,
            _proposal(values, (RelationshipEvidence(values["observation_a"]),)),
        )
        reviewed = review_relationship(
            connection,
            relationship_id=relationship.relationship_id,
            disposition="rejected",
            reviewer_label="analyst-fixture",
            rationale="Synthetic analyst rejects the proposed assertion.",
            reviewed_at="2026-01-03T00:00:00Z",
        )
        assert reviewed.verification_state == "rejected"
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_review WHERE relationship_id = ?",
            (relationship.relationship_id,),
        ).fetchone()[0] == 1
        assert list_relationship_review_queue(connection) == ()
    finally:
        connection.close()


def test_invalid_review_and_missing_evidence_fail_closed(tmp_path: Path) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        values = _seed(connection)
        with pytest.raises(RelationshipError, match="at least one evidence"):
            propose_relationship(
                connection,
                _proposal(values, ()),
            )
        with pytest.raises(RelationshipError, match="rationale"):
            review_relationship(
                connection,
                relationship_id=_id(),
                disposition="accepted",
                reviewer_label="analyst",
                rationale=" ",
            )
    finally:
        connection.close()



def test_vendor_static_reference_is_not_promoted_to_active_integration(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        values = _seed(connection)
        result = propose_relationship(
            connection,
            RelationshipProposal(
                run_id=values["run"],
                rule_id="website_references_vendor",
                subject_entity_id=values["domain"],
                object_entity_id=values["vendor"],
                evidence=(RelationshipEvidence(values["observation_vendor"]),),
            ),
        )
        assert result.predicate == "references_vendor"
        assert result.verification_state == "observed"
        assert "does not establish an active integration" in result.rationale
    finally:
        connection.close()


def test_two_attempts_of_one_source_do_not_count_as_corroboration(
    tmp_path: Path,
) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        values = _seed(connection)
        execution = _id()
        observation = _id()
        with transaction(connection):
            connection.execute(
                """
                INSERT INTO source_execution (
                    source_execution_id, run_id, source_id, attempt_number, status,
                    started_at, records_received, records_accepted
                ) VALUES (?, ?, 'fixture_rdap_a', 2, 'success', ?, 1, 1)
                """,
                (execution, values["run"], values["now"]),
            )
            connection.execute(
                """
                INSERT INTO observation (
                    observation_id, run_id, source_execution_id, subject_entity_id,
                    observation_type, observed_value, collected_at, verification_state,
                    attributes_json
                ) VALUES (?, ?, ?, ?, 'rdap_nameserver', 'ns1.example.invalid', ?,
                          'observed', '{"domain":"example.invalid"}')
                """,
                (observation, values["run"], execution, values["domain"], values["now"]),
            )
        result = propose_relationship(
            connection,
            _proposal(
                values,
                (
                    RelationshipEvidence(values["observation_a"]),
                    RelationshipEvidence(observation),
                ),
            ),
        )
        assert result.supporting_observation_count == 2
        assert result.supporting_source_count == 1
        assert result.verification_state == "observed"
    finally:
        connection.close()


def test_evidence_from_another_run_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "fii.sqlite3"
    initialize_database(database)
    connection = connect_database(database)
    try:
        values = _seed(connection)
        other_run = _id()
        with transaction(connection):
            connection.execute(
                """
                INSERT INTO run (
                    run_id, engagement_id, started_at, status, config_digest,
                    software_version, scope_digest
                ) VALUES (?, ?, ?, 'running', ?, '0.1.0', ?)
                """,
                (other_run, values["engagement"], values["now"], "c" * 64, "d" * 64),
            )
        proposal = RelationshipProposal(
            run_id=other_run,
            rule_id="domain_has_nameserver",
            subject_entity_id=values["domain"],
            object_entity_id=values["hostname"],
            evidence=(RelationshipEvidence(values["observation_a"]),),
        )
        with pytest.raises(RelationshipError, match="supplied run"):
            propose_relationship(connection, proposal)
    finally:
        connection.close()
