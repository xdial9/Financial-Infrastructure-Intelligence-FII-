from __future__ import annotations

import json

import pytest

from fii.config import load_config
from fii.deduplicate import deduplicate_observations
from fii.entities import build_entities_and_relationships
from fii.normalize import normalize_records
from fii.scope import host_in_scope, validate_domain, validate_record_scope

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def test_config_loads_synthetic_profile():
    config = load_config(ROOT / "examples" / "synthetic_engagement.json")
    assert config.organization == "Harborline Community Bank (Synthetic)"
    assert config.approved_domains == ("harborline.example",)
    assert config.approved_sources == ("synthetic_fixture",)


def test_scope_accepts_exact_and_subdomain_only():
    domains = ("harborline.example",)
    assert host_in_scope("harborline.example", domains)
    assert host_in_scope("online.harborline.example", domains)
    assert not host_in_scope("harborline.example.evil.invalid", domains)
    assert not host_in_scope("other.example", domains)


def test_scope_rejects_malformed_and_out_of_scope_domain():
    with pytest.raises(ValueError):
        validate_domain("https://harborline.example/path")
    with pytest.raises(ValueError, match="Out-of-scope"):
        validate_record_scope({
            "subject_type": "hostname", "subject_value": "other.invalid",
            "object_type": "vendor", "object_value": "Example Vendor",
        }, ("harborline.example",))


def test_deduplication_preserves_independent_sources_and_dates():
    fixture = json.loads((ROOT / "examples" / "synthetic_records.json").read_text())
    normalized = normalize_records(fixture)
    deduplicated = deduplicate_observations(normalized)
    vendor = next(item for item in deduplicated if item["predicate"] == "uses_vendor")
    assert vendor["evidence_count"] == 2
    assert vendor["independent_source_count"] == 2
    assert vendor["verification_status"] == "corroborated"
    assert {item["observed_at"] for item in vendor["evidence"]} == {
        "2026-11-03T10:15:00Z", "2026-11-04T14:45:00Z"
    }


def test_entities_and_relationships_retain_evidence():
    fixture = json.loads((ROOT / "examples" / "synthetic_records.json").read_text())
    deduplicated = deduplicate_observations(normalize_records(fixture))
    entities, relationships = build_entities_and_relationships(deduplicated)
    assert len(entities) == 4
    assert len(relationships) == 3
    assert all(item["evidence"] for item in relationships)
    assert any(item["verification_status"] == "corroborated" for item in relationships)


def test_collector_rejects_out_of_scope_infrastructure_object(tmp_path):
    from fii.collectors.synthetic import collect

    fixture = tmp_path / "out-of-scope.json"
    fixture.write_text(json.dumps([{
        "record_id": "bad-001",
        "source_id": "synthetic-source",
        "source_name": "Synthetic Source",
        "observed_at": "2026-11-01T00:00:00Z",
        "subject_type": "domain",
        "subject_value": "harborline.example",
        "predicate": "has_hostname",
        "object_type": "hostname",
        "object_value": "other.invalid",
        "source_url": "https://sources.invalid/record",
        "method": "synthetic_fixture",
        "confidence": "high",
        "verification_status": "observed"
    }]))
    with pytest.raises(ValueError, match="Out-of-scope"):
        collect(fixture, ("harborline.example",))


def test_config_rejects_unimplemented_source(tmp_path):
    profile = {
        "engagement_name": "Invalid source test",
        "organization": "Example Org",
        "approved_domains": ["example.test"],
        "approved_sources": ["unscoped_scanner"],
        "authorization_reference": "TEST-ONLY",
    }
    config_path = tmp_path / "invalid.json"
    config_path.write_text(json.dumps(profile))
    with pytest.raises(ValueError, match="only implements synthetic_fixture"):
        load_config(config_path)
