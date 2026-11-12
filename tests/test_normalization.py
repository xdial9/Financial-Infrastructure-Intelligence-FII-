"""Offline tests for canonical observations, provenance and entity resolution."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from fii.normalization import (
    EntityIdentifier,
    EntitySeed,
    SourceObservationEnvelope,
    deduplicate_observations,
    normalize_identifier,
    persist_canonical_observations,
    register_entity_registry,
    resolve_entity,
)
from fii.normalization.observations import NormalizationError
from fii.sources.contracts import Observation
from fii.storage.database import connect_database, initialize_database, transaction


def _sha(character: str) -> str:
    return character * 64


def _seed_database(path: Path):
    initialize_database(path)
    connection = connect_database(path)
    run_id = str(uuid4())
    execution_ids = {
        source_id: str(uuid4()) for source_id in ("source_a", "source_b", "source_c")
    }
    now = "2026-11-11T12:00:00Z"
    with transaction(connection):
        connection.execute(
            """
            INSERT INTO engagement (
                engagement_id, slug, display_name, config_path, scope_json,
                created_at, updated_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
            """,
            (
                str(uuid4()),
                f"normalization-{run_id[:8]}",
                "Synthetic normalization test",
                "config/effective.yaml",
                '{"seed_domains":["example.invalid"]}',
                now,
                now,
            ),
        )
        engagement_id = connection.execute(
            "SELECT engagement_id FROM engagement WHERE slug = ?",
            (f"normalization-{run_id[:8]}",),
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO run (
                run_id, engagement_id, started_at, status, config_digest,
                software_version, scope_digest
            ) VALUES (?, ?, ?, 'running', ?, '0.1.0', ?)
            """,
            (run_id, engagement_id, now, _sha("a"), _sha("b")),
        )
        for source_id, execution_id in execution_ids.items():
            connection.execute(
                """
                INSERT INTO source_definition (
                    source_id, name, adapter_version, source_class
                ) VALUES (?, ?, '1.0.0', 'public_dataset')
                """,
                (source_id, source_id),
            )
            connection.execute(
                """
                INSERT INTO source_execution (
                    source_execution_id, run_id, source_id, attempt_number,
                    status, started_at, records_received, records_accepted
                ) VALUES (?, ?, ?, 1, 'success', ?, 1, 1)
                """,
                (execution_id, run_id, source_id, now),
            )
    return connection, run_id, execution_ids


def _insert_observation(
    connection,
    *,
    run_id: str,
    source_execution_id: str,
    observation_type: str = "legal_entity_identifier",
    observed_value: str = "5493001KJTIIGC8Y1R12",
    raw_sha256: str = _sha("c"),
    attributes: dict | None = None,
) -> str:
    observation_id = str(uuid4())
    with transaction(connection):
        connection.execute(
            """
            INSERT INTO observation (
                observation_id, run_id, source_execution_id, observation_type,
                observed_value, collected_at, raw_sha256, verification_state,
                attributes_json
            ) VALUES (?, ?, ?, ?, ?, '2026-11-11T12:00:00Z', ?, 'observed', ?)
            """,
            (
                observation_id,
                run_id,
                source_execution_id,
                observation_type,
                observed_value,
                raw_sha256,
                json.dumps(attributes or {}, sort_keys=True),
            ),
        )
    return observation_id


def _observation(
    value: str,
    raw_sha256: str,
    *,
    observation_type: str = "rdap_domain",
    attributes: dict | None = None,
    observed_at: str | None = None,
) -> Observation:
    return Observation(
        observation_type=observation_type,
        observed_value=value,
        collected_at="2026-11-11T12:00:00Z",
        source_url="https://registry.example.test/record",
        raw_sha256=raw_sha256,
        verification_state="observed",
        observed_at=observed_at,
        attributes=attributes or {},
    )


def test_identifier_registry_normalizes_by_type_and_prevents_cross_type_use() -> None:
    assert normalize_identifier("lei", "5493001KJTIIGC8Y1R12").identifier_value == (
        "5493001KJTIIGC8Y1R12"
    )
    assert normalize_identifier("sec_cik", "320193").identifier_value == "0000320193"
    assert normalize_identifier(
        "companies_house_number", "01234567"
    ).identifier_value == "01234567"
    assert normalize_identifier("domain", "WWW.Example.Invalid.").identifier_value == (
        "www.example.invalid"
    )
    assert normalize_identifier("ip_address", "2001:0db8::1").identifier_value == (
        "2001:db8::1"
    )
    assert normalize_identifier("asn", "AS15169").identifier_value == "AS15169"

    with pytest.raises(ValueError, match="belongs to entity type"):
        normalize_identifier("domain", "example.invalid", entity_type="organization")
    with pytest.raises(ValueError, match="20 uppercase"):
        normalize_identifier("lei", "not-an-lei")
    with pytest.raises(ValueError, match="Unregistered identifier type"):
        normalize_identifier("unregistered", "value")


def test_registry_is_installed_idempotently(tmp_path: Path) -> None:
    connection, _, _ = _seed_database(tmp_path / "fii.sqlite3")
    try:
        register_entity_registry(connection)
        register_entity_registry(connection)
        entity_types = connection.execute(
            "SELECT COUNT(*) FROM entity_type_registry"
        ).fetchone()[0]
        identifier_types = connection.execute(
            "SELECT COUNT(*) FROM identifier_type_registry"
        ).fetchone()[0]
        assert entity_types == 10
        assert identifier_types == 11
    finally:
        connection.close()


def test_case_and_idna_variants_deduplicate_but_keep_each_source_reference() -> None:
    run_id = str(uuid4())
    source_a, source_b = str(uuid4()), str(uuid4())
    inputs = (
        SourceObservationEnvelope(
            run_id,
            source_a,
            _observation(
                "WWW.Example.Invalid.",
                _sha("a"),
                attributes={"provider": "registry-a", "query_value": "example"},
            ),
            "raw/source-a/rdap.json",
        ),
        SourceObservationEnvelope(
            run_id,
            source_b,
            _observation(
                "www.example.invalid",
                _sha("b"),
                attributes={"provider": "registry-b", "query_value": "www.example.invalid"},
            ),
            "raw/source-b/rdap.json",
        ),
    )

    result = deduplicate_observations(inputs)

    assert result.input_count == 2
    assert result.unique_count == 1
    assert result.duplicates_collapsed == 1
    fact = result.observations[0]
    assert fact.observed_value == "www.example.invalid"
    assert fact.canonicalization_version == "observation-v1"
    assert len(fact.provenance) == 2
    assert {item.raw_sha256 for item in fact.provenance} == {_sha("a"), _sha("b")}
    assert {item.provenance_role for item in fact.provenance} == {"primary", "context"}


def test_nameserver_facts_are_scoped_to_the_parent_domain() -> None:
    run_id = str(uuid4())
    inputs = (
        SourceObservationEnvelope(
            run_id,
            str(uuid4()),
            _observation(
                "NS1.provider.invalid",
                _sha("a"),
                observation_type="rdap_nameserver",
                attributes={"domain": "bank-one.invalid"},
            ),
        ),
        SourceObservationEnvelope(
            run_id,
            str(uuid4()),
            _observation(
                "ns1.provider.invalid",
                _sha("b"),
                observation_type="rdap_nameserver",
                attributes={"domain": "bank-two.invalid"},
            ),
        ),
    )

    result = deduplicate_observations(inputs)

    assert result.unique_count == 2


def test_same_legal_name_for_two_leis_does_not_deduplicate() -> None:
    run_id = str(uuid4())
    inputs = (
        SourceObservationEnvelope(
            run_id,
            str(uuid4()),
            _observation(
                "Example Financial Ltd",
                _sha("a"),
                observation_type="lei_legal_name",
                attributes={"lei": "5493001KJTIIGC8Y1R12", "provider": "GLEIF"},
            ),
        ),
        SourceObservationEnvelope(
            run_id,
            str(uuid4()),
            _observation(
                "Example Financial Ltd",
                _sha("b"),
                observation_type="lei_legal_name",
                attributes={"lei": "213800D1EI4B9WTWWD28", "provider": "GLEIF"},
            ),
        ),
    )

    result = deduplicate_observations(inputs)

    assert result.unique_count == 2


def test_provenance_paths_and_semantic_scope_are_validated() -> None:
    run_id = str(uuid4())
    with pytest.raises(NormalizationError, match="safe, normalized relative"):
        SourceObservationEnvelope(
            run_id,
            str(uuid4()),
            _observation("example.invalid", _sha("a")),
            "../outside/raw.json",
        )
    with pytest.raises(NormalizationError, match="embedded credentials"):
        deduplicate_observations(
            [
                SourceObservationEnvelope(
                    run_id,
                    str(uuid4()),
                    _observation(
                        "https://user:pass@example.invalid/path",
                        _sha("a"),
                        observation_type="url",
                    ),
                )
            ]
        )


def test_persistence_merges_duplicate_facts_and_retains_both_raw_sources(
    tmp_path: Path,
) -> None:
    connection, run_id, executions = _seed_database(tmp_path / "fii.sqlite3")
    try:
        result = deduplicate_observations(
            [
                SourceObservationEnvelope(
                    run_id,
                    executions["source_a"],
                    _observation("Example.Invalid.", _sha("a")),
                    "raw/source-a/domain.json",
                ),
                SourceObservationEnvelope(
                    run_id,
                    executions["source_b"],
                    _observation("example.invalid", _sha("b")),
                    "raw/source-b/domain.json",
                ),
            ]
        )
        persisted = persist_canonical_observations(connection, result.observations)

        assert persisted.inserted_observations == 1
        assert persisted.reused_observations == 0
        assert persisted.inserted_source_links == 1
        assert persisted.inserted_provenance_records == 2

        row = connection.execute(
            "SELECT observation_id, verification_state FROM observation WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        assert row["verification_state"] == "observed"
        source_links = connection.execute(
            """
            SELECT provenance_role FROM observation_source_link
            WHERE observation_id = ? ORDER BY provenance_role
            """,
            (row["observation_id"],),
        ).fetchall()
        assert [item["provenance_role"] for item in source_links] == [
            "context",
            "primary",
        ]
        provenance = connection.execute(
            """
            SELECT source_execution_id, raw_sha256, raw_evidence_path, provenance_role
            FROM observation_provenance WHERE observation_id = ?
            ORDER BY raw_sha256
            """,
            (row["observation_id"],),
        ).fetchall()
        assert len(provenance) == 2
        assert {item["raw_sha256"] for item in provenance} == {_sha("a"), _sha("b")}
        assert {item["provenance_role"] for item in provenance} == {"primary", "context"}

        repeated = persist_canonical_observations(connection, result.observations)
        assert repeated.inserted_observations == 0
        assert repeated.reused_observations == 1
        assert repeated.inserted_source_links == 0
        assert repeated.inserted_provenance_records == 0
    finally:
        connection.close()


def test_conflicting_values_remain_separate_canonical_observations(
    tmp_path: Path,
) -> None:
    connection, run_id, executions = _seed_database(tmp_path / "fii.sqlite3")
    try:
        result = deduplicate_observations(
            [
                SourceObservationEnvelope(
                    run_id,
                    executions["source_a"],
                    _observation(
                        "active",
                        _sha("a"),
                        observation_type="rdap_status",
                        attributes={"domain": "example.invalid"},
                    ),
                ),
                SourceObservationEnvelope(
                    run_id,
                    executions["source_b"],
                    _observation(
                        "inactive",
                        _sha("b"),
                        observation_type="rdap_status",
                        attributes={"domain": "example.invalid"},
                    ),
                ),
            ]
        )
        assert result.unique_count == 2
        persist_canonical_observations(connection, result.observations)
        count = connection.execute(
            "SELECT COUNT(*) FROM observation WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
        assert count == 2
    finally:
        connection.close()


def test_exact_lei_identifiers_resolve_two_observations_to_one_entity(
    tmp_path: Path,
) -> None:
    connection, run_id, executions = _seed_database(tmp_path / "fii.sqlite3")
    try:
        observation_a = _insert_observation(
            connection,
            run_id=run_id,
            source_execution_id=executions["source_a"],
        )
        first = resolve_entity(
            connection,
            EntitySeed(
                run_id=run_id,
                source_observation_id=observation_a,
                entity_type="organization",
                display_name="Example Financial Ltd",
                jurisdiction="GB",
                identifiers=(EntityIdentifier("lei", "5493001KJTIIGC8Y1R12"),),
            ),
        )
        assert first.outcome == "created"
        assert first.match_method == "new_exact_lei"

        observation_b = _insert_observation(
            connection,
            run_id=run_id,
            source_execution_id=executions["source_b"],
            raw_sha256=_sha("d"),
        )
        second = resolve_entity(
            connection,
            EntitySeed(
                run_id=run_id,
                source_observation_id=observation_b,
                entity_type="organization",
                display_name="EXAMPLE FINANCIAL LTD",
                jurisdiction="GB",
                identifiers=(EntityIdentifier("lei", "5493001KJTIIGC8Y1R12"),),
            ),
        )
        assert second.outcome == "matched"
        assert second.entity_id == first.entity_id
        assert second.matched_entity_id == first.entity_id

        assigned = connection.execute(
            """
            SELECT DISTINCT subject_entity_id FROM observation
            WHERE observation_id IN (?, ?)
            """,
            (observation_a, observation_b),
        ).fetchall()
        assert {item["subject_entity_id"] for item in assigned} == {first.entity_id}
        assert connection.execute(
            "SELECT COUNT(*) FROM entity WHERE entity_type = 'organization'"
        ).fetchone()[0] == 1

        repeated = resolve_entity(
            connection,
            EntitySeed(
                run_id=run_id,
                source_observation_id=observation_b,
                entity_type="organization",
                display_name="EXAMPLE FINANCIAL LTD",
                jurisdiction="GB",
                identifiers=(EntityIdentifier("lei", "5493001KJTIIGC8Y1R12"),),
            ),
        )
        assert repeated.decision_id == second.decision_id
    finally:
        connection.close()


def test_name_similarity_creates_a_review_candidate_but_never_merges(
    tmp_path: Path,
) -> None:
    connection, run_id, executions = _seed_database(tmp_path / "fii.sqlite3")
    try:
        first_observation = _insert_observation(
            connection,
            run_id=run_id,
            source_execution_id=executions["source_a"],
        )
        first = resolve_entity(
            connection,
            EntitySeed(
                run_id=run_id,
                source_observation_id=first_observation,
                entity_type="organization",
                display_name="North Shore Financial",
                jurisdiction="GB",
                identifiers=(EntityIdentifier("lei", "5493001KJTIIGC8Y1R12"),),
            ),
        )

        second_observation = _insert_observation(
            connection,
            run_id=run_id,
            source_execution_id=executions["source_b"],
            raw_sha256=_sha("d"),
        )
        second = resolve_entity(
            connection,
            EntitySeed(
                run_id=run_id,
                source_observation_id=second_observation,
                entity_type="organization",
                display_name="North Shore Financial Group",
                jurisdiction="GB",
            ),
        )

        assert second.outcome == "candidate"
        assert second.entity_id != first.entity_id
        assert first.entity_id in {item.entity_id for item in second.candidates}
        assert "No merge" in second.rationale
        assigned = connection.execute(
            "SELECT subject_entity_id FROM observation WHERE observation_id = ?",
            (second_observation,),
        ).fetchone()[0]
        assert assigned == second.entity_id
        assert connection.execute(
            "SELECT COUNT(*) FROM entity WHERE entity_type = 'organization'"
        ).fetchone()[0] == 2
        decision = connection.execute(
            """
            SELECT outcome, rationale FROM entity_resolution_decision
            WHERE decision_id = ?
            """,
            (second.decision_id,),
        ).fetchone()
        assert decision["outcome"] == "candidate"
        assert "No merge" in decision["rationale"]
    finally:
        connection.close()


def test_exact_name_in_different_jurisdictions_remains_a_review_candidate(
    tmp_path: Path,
) -> None:
    connection, run_id, executions = _seed_database(tmp_path / "fii.sqlite3")
    try:
        first_observation = _insert_observation(
            connection,
            run_id=run_id,
            source_execution_id=executions["source_a"],
        )
        first = resolve_entity(
            connection,
            EntitySeed(
                run_id=run_id,
                source_observation_id=first_observation,
                entity_type="organization",
                display_name="Continental Payments Ltd",
                jurisdiction="GB",
                identifiers=(EntityIdentifier("lei", "5493001KJTIIGC8Y1R12"),),
            ),
        )
        second_observation = _insert_observation(
            connection,
            run_id=run_id,
            source_execution_id=executions["source_b"],
            raw_sha256=_sha("d"),
        )
        second = resolve_entity(
            connection,
            EntitySeed(
                run_id=run_id,
                source_observation_id=second_observation,
                entity_type="organization",
                display_name="Continental Payments Ltd",
                jurisdiction="US",
            ),
        )
        assert second.outcome == "candidate"
        assert second.entity_id != first.entity_id
        assert len(second.candidates) == 1
        assert "Jurisdictions differ (US vs GB)" in second.candidates[0].rationale
        assert connection.execute(
            "SELECT COUNT(*) FROM entity WHERE entity_type = 'organization'"
        ).fetchone()[0] == 2
    finally:
        connection.close()


def test_conflicting_strong_identifiers_do_not_merge_entities(
    tmp_path: Path,
) -> None:
    connection, run_id, executions = _seed_database(tmp_path / "fii.sqlite3")
    try:
        first_observation = _insert_observation(
            connection,
            run_id=run_id,
            source_execution_id=executions["source_a"],
        )
        first = resolve_entity(
            connection,
            EntitySeed(
                run_id=run_id,
                source_observation_id=first_observation,
                entity_type="organization",
                display_name="First Financial Ltd",
                identifiers=(EntityIdentifier("lei", "5493001KJTIIGC8Y1R12"),),
            ),
        )
        second_observation = _insert_observation(
            connection,
            run_id=run_id,
            source_execution_id=executions["source_b"],
            raw_sha256=_sha("d"),
        )
        second = resolve_entity(
            connection,
            EntitySeed(
                run_id=run_id,
                source_observation_id=second_observation,
                entity_type="organization",
                display_name="Second Financial Ltd",
                identifiers=(EntityIdentifier("lei", "213800D1EI4B9WTWWD28"),),
            ),
        )

        conflicting_observation = _insert_observation(
            connection,
            run_id=run_id,
            source_execution_id=executions["source_c"],
            raw_sha256=_sha("e"),
        )
        conflict = resolve_entity(
            connection,
            EntitySeed(
                run_id=run_id,
                source_observation_id=conflicting_observation,
                entity_type="organization",
                display_name="Conflicting Registry Data Ltd",
                identifiers=(
                    EntityIdentifier("lei", "5493001KJTIIGC8Y1R12"),
                    EntityIdentifier("lei", "213800D1EI4B9WTWWD28"),
                ),
            ),
        )
        assert conflict.outcome == "conflict"
        assert conflict.entity_id is None
        assert {item.entity_id for item in conflict.candidates} == {
            first.entity_id,
            second.entity_id,
        }
        assert connection.execute(
            "SELECT subject_entity_id FROM observation WHERE observation_id = ?",
            (conflicting_observation,),
        ).fetchone()[0] is None
        assert connection.execute(
            "SELECT COUNT(*) FROM entity WHERE entity_type = 'organization'"
        ).fetchone()[0] == 2
    finally:
        connection.close()


def test_identifier_registry_keeps_domains_separate_from_organizations(
    tmp_path: Path,
) -> None:
    connection, run_id, executions = _seed_database(tmp_path / "fii.sqlite3")
    try:
        observation_id = _insert_observation(
            connection,
            run_id=run_id,
            source_execution_id=executions["source_a"],
            observation_type="rdap_domain",
            observed_value="example.invalid",
        )
        result = resolve_entity(
            connection,
            EntitySeed(
                run_id=run_id,
                source_observation_id=observation_id,
                entity_type="domain",
                display_name="example.invalid",
                identifiers=(EntityIdentifier("domain", "EXAMPLE.INVALID."),),
            ),
        )
        assert result.outcome == "created"
        entity = connection.execute(
            "SELECT entity_type FROM entity WHERE entity_id = ?",
            (result.entity_id,),
        ).fetchone()
        assert entity["entity_type"] == "domain"
        with pytest.raises(ValueError, match="belongs to entity type"):
            normalize_identifier("domain", "example.invalid", entity_type="organization")
    finally:
        connection.close()
