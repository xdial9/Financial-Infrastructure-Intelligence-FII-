"""Offline tests for FII collector contracts and passive fixture adapters."""

from __future__ import annotations

import hashlib
import json
import logging
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from uuid import uuid4

import pytest

from fii.sources import (
    CTLiveCollector,
    CollectionContext,
    EvidenceWriteError,
    PublicWebsiteSnapshotCollector,
    SourceDefinition,
    SourceRegistry,
    get_default_registry,
    run_collector,
)
from fii.sources.contracts import CollectionResult
from fii.sources.ct_logs import CTLogsFixtureCollector
from fii.sources.web_surface import WebSurfaceFixtureCollector


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sources"


class FakeHTTPResponse:
    """Small context-managed response double; never opens a socket."""

    def __init__(
        self,
        body: bytes,
        *,
        content_type: str,
        final_url: str,
    ) -> None:
        self.body = body
        self.final_url = final_url
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(body))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, limit: int) -> bytes:
        return self.body[:limit]

    def geturl(self) -> str:
        return self.final_url


class FakeHTTPOpener:
    """Return predefined responses and capture requests for assertions."""

    def __init__(self, responses: list[FakeHTTPResponse | Exception]) -> None:
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout: int):
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_context(
    tmp_path: Path,
    *,
    fixture_path: Path | None,
    approved_domains: tuple[str, ...] = ("example.invalid",),
    raw_directory: Path | None = None,
    live_collection_approved: bool = False,
    minimum_request_interval_seconds: float = 1.0,
) -> CollectionContext:
    return CollectionContext(
        run_id=str(uuid4()),
        raw_directory=raw_directory or tmp_path / "run" / "raw",
        fixture_path=fixture_path,
        approved_domains=approved_domains,
        source_url="https://www.example.invalid/",
        live_collection_approved=live_collection_approved,
        minimum_request_interval_seconds=minimum_request_interval_seconds,
    )


def test_collection_result_rejects_accepted_records_above_received() -> None:
    with pytest.raises(ValueError, match="Accepted source records cannot exceed"):
        CollectionResult(
            source_id="ct_logs",
            status="success",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:01Z",
            records_received=1,
            records_accepted=2,
        )


def test_registry_is_fixed_and_definitions_are_deterministic() -> None:
    registry = get_default_registry()

    assert registry.source_ids() == (
        "ct_live",
        "ct_logs",
        "web_surface",
        "website_public",
    )
    definitions = registry.definitions()
    assert [item.source_id for item in definitions] == [
        "ct_live",
        "ct_logs",
        "web_surface",
        "website_public",
    ]
    assert all(item.default_enabled is False for item in definitions)
    assert registry.get("ct_live").definition.integration_kind == "provider_api"
    assert registry.get("ct_logs").definition.source_class == "public_api"
    assert registry.get("web_surface").definition.source_class == "targeted_public_web"
    assert registry.get("website_public").definition.source_class == "targeted_public_web"

    with pytest.raises(KeyError, match="Unknown FII source ID"):
        registry.get("not_registered")


def test_ct_live_requires_explicit_approval_before_network_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_network(*args, **kwargs):
        raise AssertionError("network helper must not be called without approval")

    monkeypatch.setattr("fii.sources.http.build_opener", unexpected_network)
    context = make_context(tmp_path, fixture_path=None)

    result = run_collector(CTLiveCollector(), context)

    assert result.status == "failed"
    assert result.diagnostics[0].code == "live_collection_not_approved"


def test_ct_live_collects_one_page_and_retains_only_in_scope_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_body = json.dumps(
        {
            "apex": "example.invalid",
            "count": 3,
            "total": 3,
            "total_capped": False,
            "names": [
                {"name": "example.invalid", "first_seen": "2026-01-01"},
                {"name": "api.example.invalid", "first_seen": "2026-02-03"},
                {"name": "outside.invalid", "first_seen": "2026-03-04"},
            ],
            "has_more": False,
        }
    ).encode("utf-8")
    opener = FakeHTTPOpener(
        [
            FakeHTTPResponse(
                provider_body,
                content_type="application/json",
                final_url=(
                    "https://crt.live/api/v1/domain/example.invalid"
                    "?sort=recent&limit=1000"
                ),
            )
        ]
    )
    monkeypatch.setattr("fii.sources.http.build_opener", lambda *args: opener)
    context = make_context(
        tmp_path,
        fixture_path=None,
        live_collection_approved=True,
    )

    result = run_collector(CTLiveCollector(), context)

    assert result.status == "success"
    assert result.records_received == 3
    assert result.records_accepted == 2
    assert len(result.observations) == 2
    assert {item.observed_value for item in result.observations} == {
        "example.invalid",
        "api.example.invalid",
    }
    assert all(item.observation_type == "ct_hostname" for item in result.observations)
    assert all(item.raw_sha256 == result.raw_evidence[0].sha256 for item in result.observations)

    request, timeout = opener.requests[0]
    assert request.get_method() == "GET"
    assert request.full_url == (
        "https://crt.live/api/v1/domain/example.invalid?sort=recent&limit=1000"
    )
    assert request.get_header("Authorization") is None
    assert timeout == 20

    evidence = result.raw_evidence[0]
    stored = json.loads((context.raw_directory / evidence.relative_path).read_text())
    assert [item["name"] for item in stored["names"]] == [
        "example.invalid",
        "api.example.invalid",
    ]
    assert evidence.original_sha256 == hashlib.sha256(provider_body).hexdigest()
    assert evidence.sha256 != evidence.original_sha256


def test_ct_live_rate_limit_is_reported_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = Message()
    headers["Retry-After"] = "60"
    error = HTTPError(
        "https://crt.live/api/v1/domain/example.invalid",
        429,
        "Too Many Requests",
        headers,
        None,
    )
    opener = FakeHTTPOpener([error])
    monkeypatch.setattr("fii.sources.http.build_opener", lambda *args: opener)
    context = make_context(
        tmp_path,
        fixture_path=None,
        live_collection_approved=True,
    )

    result = run_collector(CTLiveCollector(), context)

    assert result.status == "failed"
    assert result.diagnostics[0].code == "rate_limited"
    assert "Retry-After: 60" in result.diagnostics[0].message
    assert len(opener.requests) == 1


def test_public_website_snapshot_fetches_only_approved_html_and_scripts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        '<html><head><script src="/assets/app.js"></script>'
        '<script src="https://cdn.external.invalid/vendor.js"></script>'
        '<a href="/api-docs">API</a></head>'
        '<body><script>const protocol = "OIDC";</script></body></html>'
    ).encode("utf-8")
    script = (
        'fetch("/api/v3/accounts", {method: "POST"});'
        'const provider = "Plaid"; const flow = "PKCE";'
    ).encode("utf-8")
    opener = FakeHTTPOpener(
        [
            FakeHTTPResponse(
                html,
                content_type="text/html",
                final_url="https://www.example.invalid/",
            ),
            FakeHTTPResponse(
                script,
                content_type="application/javascript",
                final_url="https://www.example.invalid/assets/app.js",
            ),
        ]
    )
    monkeypatch.setattr("fii.sources.http.build_opener", lambda *args: opener)
    context = make_context(
        tmp_path,
        fixture_path=None,
        live_collection_approved=True,
        minimum_request_interval_seconds=0,
    )

    result = run_collector(PublicWebsiteSnapshotCollector(), context)

    assert result.status == "success"
    assert result.records_received == 2
    assert result.records_accepted == 2
    assert len(opener.requests) == 2
    assert all(request.get_method() == "GET" for request, _ in opener.requests)
    assert all(request.get_header("Authorization") is None for request, _ in opener.requests)
    assert all(request.get_header("Cookie") is None for request, _ in opener.requests)

    endpoints = [
        item for item in result.observations
        if item.observation_type == "api_endpoint"
    ]
    assert ("POST", "/api/v3/accounts") in {
        (item.attributes["method"], item.attributes["path"]) for item in endpoints
    }
    auth_markers = {
        item.observed_value
        for item in result.observations
        if item.observation_type == "auth_structure"
    }
    assert {"openid_connect", "pkce"} <= auth_markers
    integrations = {
        item.observed_value
        for item in result.observations
        if item.observation_type == "integration_reference"
    }
    assert "Plaid" in integrations

    assets = [
        item for item in result.observations
        if item.observation_type == "javascript_asset"
    ]
    assert any(item.attributes["fetched"] is True for item in assets)
    assert any(
        item.attributes.get("skip_reason") == "outside_approved_https_scope"
        for item in assets
    )


def test_public_website_snapshot_requires_manual_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_network(*args, **kwargs):
        raise AssertionError("network helper must not be called without approval")

    monkeypatch.setattr("fii.sources.http.build_opener", unexpected_network)
    context = make_context(tmp_path, fixture_path=None)

    result = run_collector(PublicWebsiteSnapshotCollector(), context)

    assert result.status == "failed"
    assert result.diagnostics[0].code == "live_collection_not_approved"


def test_registry_rejects_duplicate_source_ids() -> None:
    collector = CTLogsFixtureCollector()
    with pytest.raises(ValueError, match="Duplicate collector source ID"):
        SourceRegistry((collector, collector))


def test_source_definition_rejects_invalid_ids() -> None:
    with pytest.raises(ValueError, match="Invalid stable source ID"):
        SourceDefinition(
            source_id="../external",
            name="Invalid",
            adapter_version="1.0.0",
            source_class="public_api",
            description="Synthetic invalid definition.",
        )


def test_ct_fixture_collects_only_approved_domains_and_preserves_raw(
    tmp_path: Path,
) -> None:
    fixture = FIXTURE_ROOT / "ct_logs.json"
    context = make_context(tmp_path, fixture_path=fixture)

    result = run_collector(CTLogsFixtureCollector(), context)

    assert result.status == "success"
    assert result.records_received == 2
    assert result.records_accepted == 2
    values = [item.observed_value for item in result.observations]
    assert values.count("api.example.invalid") == 2
    assert "login.example.invalid" in values
    assert "outside.invalid" not in values
    assert all(item.observation_type == "certificate_name" for item in result.observations)
    assert all(item.attributes["relationship_claim"] == "none" for item in result.observations)

    evidence = result.raw_evidence[0]
    stored = context.raw_directory / evidence.relative_path
    assert stored.is_file()
    assert stored.read_bytes() == fixture.read_bytes()
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == evidence.sha256
    assert result.observations[0].raw_sha256 == evidence.sha256


def test_ct_fixture_requires_explicit_approved_domain_scope(tmp_path: Path) -> None:
    context = make_context(
        tmp_path,
        fixture_path=FIXTURE_ROOT / "ct_logs.json",
        approved_domains=(),
    )

    result = run_collector(CTLogsFixtureCollector(), context)

    assert result.status == "failed"
    assert result.diagnostics[0].code == "empty_scope"
    assert result.records_accepted == 0


def test_ct_invalid_fixture_is_failed_but_raw_bytes_remain_referenced(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "malformed.json"
    fixture.write_text("{not-json", encoding="utf-8")
    context = make_context(tmp_path, fixture_path=fixture)

    result = run_collector(CTLogsFixtureCollector(), context)

    assert result.status == "failed"
    assert result.diagnostics[0].code == "invalid_ct_fixture"
    assert len(result.raw_evidence) == 1
    assert (context.raw_directory / result.raw_evidence[0].relative_path).read_text(
        encoding="utf-8"
    ) == "{not-json"


def test_ct_raw_evidence_is_idempotent_without_overwrite(tmp_path: Path) -> None:
    fixture = FIXTURE_ROOT / "ct_logs.json"
    context = make_context(tmp_path, fixture_path=fixture)
    collector = CTLogsFixtureCollector()

    first = run_collector(collector, context)
    second = run_collector(collector, context)

    assert first.raw_evidence[0].relative_path == second.raw_evidence[0].relative_path
    assert len(list(context.raw_directory.rglob("*.json"))) == 1


def test_web_surface_extracts_api_assets_auth_and_vendor_references(
    tmp_path: Path,
) -> None:
    context = make_context(
        tmp_path,
        fixture_path=FIXTURE_ROOT / "web_surface",
    )

    result = run_collector(WebSurfaceFixtureCollector(), context)

    assert result.status == "success"
    assert result.records_received == 2
    assert result.records_accepted == 2

    endpoints = {
        (item.attributes["method"], item.attributes["path"])
        for item in result.observations
        if item.observation_type == "api_endpoint"
    }
    assert ("POST", "/api/v2/accounts") in endpoints
    assert ("GET", "https://api.example.invalid/v1/institutions") in endpoints
    assert ("GET", "/oauth/authorize") in endpoints

    kinds = {item.observation_type for item in result.observations}
    assert {
        "javascript_asset",
        "api_endpoint",
        "api_documentation_reference",
        "source_map_reference",
        "auth_structure",
        "integration_reference",
    } <= kinds

    auth_markers = {
        item.observed_value
        for item in result.observations
        if item.observation_type == "auth_structure"
    }
    assert {"openid_connect", "authorization_endpoint", "token_endpoint", "pkce"} <= auth_markers

    integrations = {
        item.observed_value
        for item in result.observations
        if item.observation_type == "integration_reference"
    }
    assert {"Plaid", "Stripe"} <= integrations
    assert all(
        item.attributes.get("relationship_established") is False
        for item in result.observations
        if item.observation_type == "integration_reference"
    )
    assert all(
        item.attributes.get("execution_tested") is False
        for item in result.observations
        if item.observation_type == "api_endpoint"
    )

    asset = next(
        item for item in result.observations
        if item.observation_type == "javascript_asset"
    )
    assert asset.observed_value == "/assets/app.js"
    assert asset.attributes["fetched"] is False


def test_web_surface_redacts_likely_credentials_before_raw_storage(
    tmp_path: Path,
) -> None:
    context = make_context(
        tmp_path,
        fixture_path=FIXTURE_ROOT / "web_surface",
    )

    result = run_collector(WebSurfaceFixtureCollector(), context)

    assert any(item.redactions_applied >= 2 for item in result.raw_evidence)
    stored_text = "\n".join(
        (context.raw_directory / item.relative_path).read_text(encoding="utf-8")
        for item in result.raw_evidence
    )
    assert "synthetic-placeholder-not-a-secret" not in stored_text
    assert "synthetic-bearer-placeholder" not in stored_text
    assert "[REDACTED]" in stored_text
    assert any(item.sha256 != item.original_sha256 for item in result.raw_evidence)


def test_web_surface_does_not_fetch_script_or_source_map_references(
    tmp_path: Path,
) -> None:
    context = make_context(
        tmp_path,
        fixture_path=FIXTURE_ROOT / "web_surface",
    )

    result = run_collector(WebSurfaceFixtureCollector(), context)

    assets = [
        item for item in result.observations
        if item.observation_type == "javascript_asset"
    ]
    source_maps = [
        item for item in result.observations
        if item.observation_type == "source_map_reference"
    ]
    assert assets and source_maps
    assert all(item.attributes["fetched"] is False for item in assets + source_maps)


def test_source_failure_is_logged_as_a_failed_result(tmp_path: Path, caplog) -> None:
    missing = tmp_path / "missing.json"
    context = make_context(tmp_path, fixture_path=missing)
    logger = logging.getLogger("fii.sources.test")

    with caplog.at_level(logging.WARNING, logger="fii.sources.test"):
        result = run_collector(CTLogsFixtureCollector(), context, logger=logger)

    assert result.status == "failed"
    assert result.diagnostics[0].code == "fixture_unavailable"
    assert "source_execution source_id=ct_logs status=failed" in caplog.text


def test_evidence_persistence_failure_is_fatal(tmp_path: Path) -> None:
    real_directory = tmp_path / "real-raw"
    real_directory.mkdir()
    symlink_directory = tmp_path / "raw-link"
    symlink_directory.symlink_to(real_directory, target_is_directory=True)
    context = make_context(
        tmp_path,
        fixture_path=FIXTURE_ROOT / "ct_logs.json",
        raw_directory=symlink_directory,
    )

    with pytest.raises(EvidenceWriteError, match="symlinked raw evidence"):
        run_collector(CTLogsFixtureCollector(), context)


def test_collection_result_manifest_is_json_serializable(tmp_path: Path) -> None:
    context = make_context(
        tmp_path,
        fixture_path=FIXTURE_ROOT / "ct_logs.json",
    )

    result = run_collector(CTLogsFixtureCollector(), context)
    serialized = json.dumps(result.to_dict(), sort_keys=True)

    assert '"source_id": "ct_logs"' in serialized
    assert "api.example.invalid" in serialized
    assert "Synthetic Test CA" in serialized
