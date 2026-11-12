"""Offline tests for RDAP and official-source enrichment adapters."""

from __future__ import annotations

import json
from email.message import Message
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest

from fii.sources import CollectionContext, get_default_registry, run_collector
from fii.sources.gleif import GLEIFCollector
from fii.sources.rdap import RDAPCollector


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sources"


class FakeHTTPResponse:
    def __init__(self, body: bytes, *, url: str, content_type: str = "application/json") -> None:
        self.body = body
        self.url = url
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
        return self.url


class FakeOpener:
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
    fixture_path: Path | None = None,
    approved_domains: tuple[str, ...] = (),
    organization_names: tuple[str, ...] = (),
    legal_entity_identifiers: tuple[str, ...] = (),
    live_collection_approved: bool = False,
) -> CollectionContext:
    return CollectionContext(
        run_id=str(uuid4()),
        raw_directory=tmp_path / "run" / "raw",
        fixture_path=fixture_path,
        approved_domains=approved_domains,
        organization_names=organization_names,
        legal_entity_identifiers=legal_entity_identifiers,
        live_collection_approved=live_collection_approved,
        minimum_request_interval_seconds=0,
    )


def test_default_registry_contains_rdap_and_gleif_sources() -> None:
    registry = get_default_registry()

    assert "rdap_domain" in registry.source_ids()
    assert "gleif_lei" in registry.source_ids()
    assert registry.get("rdap_domain").definition.default_enabled is False
    assert registry.get("gleif_lei").definition.default_enabled is False


def test_rdap_fixture_uses_longest_iana_suffix_and_excludes_contacts(tmp_path: Path) -> None:
    context = make_context(
        tmp_path,
        fixture_path=FIXTURE_ROOT / "rdap_domain.json",
        approved_domains=("bank.example.co.uk",),
    )

    result = run_collector(RDAPCollector(), context)

    assert result.status == "success"
    assert result.records_received == result.records_accepted == 1
    assert len(result.raw_evidence) == 2
    assert any(item.observation_type == "rdap_domain" for item in result.observations)
    assert {
        item.observed_value
        for item in result.observations
        if item.observation_type == "rdap_nameserver"
    } == {"ns1.provider.example", "ns2.provider.example"}
    registrar = next(
        item for item in result.observations if item.observation_type == "rdap_registrar"
    )
    assert registrar.observed_value == "Example Registrar Ltd"
    assert registrar.attributes["iana_registrar_id"] == "9999"
    assert any(
        item.observation_type == "rdap_event" and item.observed_value == "expiration"
        for item in result.observations
    )

    stored = b"".join(
        (context.raw_directory / item.relative_path).read_bytes()
        for item in result.raw_evidence
    )
    assert b"Example Registrar Ltd" in stored
    assert b"Private Person" not in stored
    assert b"private.person@example.test" not in stored
    assert b"registrant" not in stored
    assert "co-uk" in next(
        item.source_url or ""
        for item in result.observations
        if item.observation_type == "rdap_domain"
    )


def test_rdap_requires_one_approved_domain(tmp_path: Path) -> None:
    context = make_context(tmp_path, approved_domains=("one.example", "two.example"))

    result = run_collector(RDAPCollector(), context)

    assert result.status == "failed"
    assert result.diagnostics[0].code == "single_domain_required"


def test_rdap_live_lookup_requires_explicit_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_network(*args, **kwargs):
        raise AssertionError("RDAP must not make a request without explicit approval")

    monkeypatch.setattr("fii.sources.http.build_opener", unexpected_network)
    context = make_context(tmp_path, approved_domains=("example.com",))

    result = run_collector(RDAPCollector(), context)

    assert result.status == "failed"
    assert result.diagnostics[0].code == "live_collection_not_approved"


def test_rdap_live_lookup_uses_iana_then_authoritative_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = {
        "version": "1.0",
        "publication": "2026-11-01T00:00:00Z",
        "services": [[["com"], ["https://rdap.example.test/v1/"]]],
    }
    domain_response = {
        "objectClassName": "domain",
        "ldhName": "example.com",
        "status": ["active"],
        "nameservers": [{"ldhName": "ns1.example.net"}],
    }
    fake = FakeOpener(
        [
            FakeHTTPResponse(
                json.dumps(bootstrap).encode(),
                url="https://data.iana.org/rdap/dns.json",
            ),
            FakeHTTPResponse(
                json.dumps(domain_response).encode(),
                url="https://rdap.example.test/v1/domain/example.com",
                content_type="application/rdap+json",
            ),
        ]
    )
    monkeypatch.setattr("fii.sources.http.build_opener", lambda *args, **kwargs: fake)
    context = make_context(
        tmp_path,
        approved_domains=("example.com",),
        live_collection_approved=True,
    )

    result = run_collector(RDAPCollector(), context)

    assert result.status == "success"
    assert len(fake.requests) == 2
    assert fake.requests[0][0].full_url == "https://data.iana.org/rdap/dns.json"
    assert fake.requests[1][0].full_url == (
        "https://rdap.example.test/v1/domain/example.com"
    )
    assert all(request.get_method() == "GET" for request, _ in fake.requests)
    assert all(request.get_header("Authorization") is None for request, _ in fake.requests)
    assert any(item.observation_type == "rdap_nameserver" for item in result.observations)


def test_rdap_rejects_response_for_another_domain(tmp_path: Path) -> None:
    fixture = {
        "bootstrap": {
            "version": "1.0",
            "services": [[["com"], ["https://rdap.example.test/"]]],
        },
        "domain_response": {"objectClassName": "domain", "ldhName": "other.example"},
    }
    fixture_path = tmp_path / "mismatch.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    context = make_context(
        tmp_path,
        fixture_path=fixture_path,
        approved_domains=("example.com",),
    )

    result = run_collector(RDAPCollector(), context)

    assert result.status == "failed"
    assert result.diagnostics[0].code == "rdap_domain_mismatch"


def test_gleif_name_search_records_candidate_and_relationship_references(
    tmp_path: Path,
) -> None:
    context = make_context(
        tmp_path,
        fixture_path=FIXTURE_ROOT / "gleif_lei.json",
        organization_names=("Example Financial Technologies",),
    )

    result = run_collector(GLEIFCollector(page_size=10), context)

    assert result.status == "success"
    assert result.records_received == result.records_accepted == 2
    lei_observation = next(
        item
        for item in result.observations
        if item.observation_type == "legal_entity_identifier"
    )
    assert lei_observation.observed_value == "5493001KJTIIGC8Y1R12"
    assert lei_observation.attributes["candidate_match"] is True
    assert lei_observation.attributes["entity_status"] == "ACTIVE"
    assert lei_observation.attributes["registration_status"] == "ISSUED"
    parent_ref = next(
        item
        for item in result.observations
        if item.observation_type == "gleif_relationship_reference"
        and item.attributes["relationship_type"] == "direct-parent"
    )
    assert parent_ref.observed_value == "213800D1EI4B9WTWWD28"
    assert "no linked record was fetched" in parent_ref.attributes["evidence_semantics"]

    stored = (context.raw_directory / result.raw_evidence[0].relative_path).read_text(
        encoding="utf-8"
    )
    assert "Private Office Address" not in stored
    assert "London" not in stored
    assert "Example Financial Technologies Ltd" in stored
    assert result.raw_evidence[0].original_sha256 != result.raw_evidence[0].sha256


def test_gleif_handles_missing_optional_fields_without_failing(tmp_path: Path) -> None:
    fixture = {"response": {"data": [{"id": "5493001KJTIIGC8Y1R12", "attributes": {}}]}}
    fixture_path = tmp_path / "minimal-gleif.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    context = make_context(
        tmp_path,
        fixture_path=fixture_path,
        legal_entity_identifiers=("5493001KJTIIGC8Y1R12",),
    )

    result = run_collector(GLEIFCollector(), context)

    assert result.status == "success"
    assert result.records_accepted == 1
    assert [item.observation_type for item in result.observations] == [
        "legal_entity_identifier"
    ]


def test_gleif_live_name_lookup_is_one_approved_encoded_get(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {
        "data": [{
            "id": "5493001KJTIIGC8Y1R12",
            "attributes": {
                "entity": {"legalName": {"name": "Example Financial Technologies Ltd"}}
            },
        }]
    }
    fake = FakeOpener(
        [
            FakeHTTPResponse(
                json.dumps(response).encode(),
                url="https://api.gleif.org/api/v1/lei-records",
                content_type="application/vnd.api+json",
            )
        ]
    )
    monkeypatch.setattr("fii.sources.http.build_opener", lambda *args, **kwargs: fake)
    context = make_context(
        tmp_path,
        organization_names=("Example Financial Technologies",),
        live_collection_approved=True,
    )

    result = run_collector(GLEIFCollector(), context)

    assert result.status == "success"
    assert len(fake.requests) == 1
    request = fake.requests[0][0]
    assert request.get_method() == "GET"
    parsed = urlparse(request.full_url)
    params = parse_qs(parsed.query)
    assert params["filter[entity.legalName]"] == ["Example Financial Technologies"]
    assert params["page[size]"] == ["10"]
    assert request.get_header("Authorization") is None


def test_gleif_requires_one_name_or_lei(tmp_path: Path) -> None:
    context = make_context(tmp_path)

    result = run_collector(GLEIFCollector(), context)

    assert result.status == "failed"
    assert result.diagnostics[0].code == "single_entity_query_required"


def test_gleif_rejects_invalid_lei_and_page_limits(tmp_path: Path) -> None:
    context = make_context(tmp_path, legal_entity_identifiers=("not-an-lei",))

    result = run_collector(GLEIFCollector(), context)

    assert result.status == "failed"
    assert result.diagnostics[0].code == "invalid_lei"
    with pytest.raises(ValueError, match="page size"):
        GLEIFCollector(page_size=51)
