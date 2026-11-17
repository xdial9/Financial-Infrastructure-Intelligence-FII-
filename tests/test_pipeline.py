"""Offline synthetic end-to-end tests for the FII pipeline."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from fii.core.config import load_config
from fii.core.pipeline import PipelineError, execute_pipeline


def _write_synthetic_configuration(tmp_path: Path, *, live: bool = False) -> Path:
    rdap_path = tmp_path / "rdap.json"
    rdap_path.write_text(
        json.dumps(
            {
                "bootstrap": {
                    "version": "1.0",
                    "publication": "2026-11-01T00:00:00Z",
                    "services": [[["invalid"], ["https://rdap.example.test/"]]],
                },
                "domain_response": {
                    "objectClassName": "domain",
                    "handle": "SYNTHETIC-DOMAIN-1",
                    "ldhName": "example.invalid",
                    "status": ["active"],
                    "events": [],
                    "nameservers": [{"ldhName": "ns1.example.invalid"}],
                    "entities": [],
                },
                "source_url": "https://rdap.example.test/domain/example.invalid",
            }
        ),
        encoding="utf-8",
    )
    ct_path = tmp_path / "ct.json"
    ct_path.write_text(
        json.dumps(
            {
                "source_url": "https://ct.example.invalid/synthetic",
                "records": [
                    {
                        "id": "synthetic-ct-01",
                        "name_value": "api.example.invalid\nlogin.example.invalid",
                        "issuer_name": "Synthetic Test CA",
                        "not_before": "2026-01-01T00:00:00Z",
                        "not_after": "2027-01-01T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    web_path = tmp_path / "web"
    web_path.mkdir()
    (web_path / "index.html").write_text(
        '<html><head><a href="/developer/api-docs">API docs</a></head></html>',
        encoding="utf-8",
    )
    (web_path / "app.js").write_text(
        'fetch("/api/v1/accounts", {method: "GET"}); '
        'const provider = "Plaid"; const auth = "OIDC";',
        encoding="utf-8",
    )

    config_path = tmp_path / "engagement.yaml"
    config_path.write_text(
        f"""workspace: {tmp_path / "workspace"}
engagement:
  name: Synthetic Financial Institution
  slug: synthetic-financial-institution
  organization: Example Financial Group
  authorization_reference: SYNTHETIC-LAB
scope:
  seed_domains: [example.invalid]
  approved_organizations: [Example Financial Group]
  permitted_source_classes: [public_api, targeted_public_web]
collection:
  sequential: true
  live_collection_approved: {str(live).lower()}
sources:
  rdap_domain:
    enabled: true
    fixture: {rdap_path}
    domains: [example.invalid]
  ct_logs:
    enabled: true
    fixture: {ct_path}
  web_surface:
    enabled: true
    fixture: {web_path}
    source_url: https://www.example.invalid/
""",
        encoding="utf-8",
    )
    return config_path


def test_offline_pipeline_persists_evidence_and_correlates_entities(tmp_path: Path) -> None:
    config_path = _write_synthetic_configuration(tmp_path)
    config = load_config(config_path)

    result = execute_pipeline(config, config_path)

    assert result.status == "completed"
    assert result.source_counts == {"success": 3}
    assert result.observation_count >= 8
    assert result.entity_count >= 4
    assert result.relationship_count >= 3
    assert result.finding_count >= 3
    assert result.database_path.is_file()
    assert (result.run_directory / "manifest.json").is_file()
    assert (result.run_directory / "state" / "run.json").is_file()
    assert list((result.run_directory / "evidence").rglob("*"))

    connection = sqlite3.connect(result.database_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM observation_provenance"
        ).fetchone()[0] >= result.observation_count
        assert connection.execute(
            "SELECT COUNT(*) FROM finding_evidence"
        ).fetchone()[0] == result.finding_count
        assert connection.execute(
            "SELECT COUNT(*) FROM relationship_evidence"
        ).fetchone()[0] >= result.relationship_count
        assert connection.execute(
            "SELECT COUNT(*) FROM source_execution WHERE status='success'"
        ).fetchone()[0] == 3
        assert connection.execute(
            "SELECT COUNT(*) FROM run WHERE status='completed'"
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_live_source_fails_closed_before_workspace_creation(tmp_path: Path) -> None:
    config_path = tmp_path / "live.yaml"
    workspace = tmp_path / "must-not-exist"
    config_path.write_text(
        f"""workspace: {workspace}
engagement:
  name: Live Test
  slug: live-test
scope:
  seed_domains: [example.invalid]
  permitted_source_classes: [public_api]
sources:
  ct_live:
    enabled: true
""",
        encoding="utf-8",
    )
    config = load_config(config_path)

    with pytest.raises(PipelineError, match="requires collection.live_collection_approved"):
        execute_pipeline(config, config_path)

    assert not workspace.exists()


def test_fixture_only_source_requires_an_explicit_fixture_before_workspace(tmp_path: Path) -> None:
    config_path = tmp_path / "fixture.yaml"
    workspace = tmp_path / "must-not-exist"
    config_path.write_text(
        f"""workspace: {workspace}
engagement:
  name: Fixture Test
  slug: fixture-test
scope:
  seed_domains: [example.invalid]
  permitted_source_classes: [public_api]
sources:
  ct_logs:
    enabled: true
""",
        encoding="utf-8",
    )
    config = load_config(config_path)

    with pytest.raises(PipelineError, match="fixture-only"):
        execute_pipeline(config, config_path)

    assert not workspace.exists()
