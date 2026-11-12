"""IANA-bootstrapped RDAP domain-registration enrichment.

The adapter records public registration metadata only. Registrant/admin/technical
contact details are deliberately excluded from retained evidence and observations.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from time import sleep

from fii.core.scope import normalize_domain
from fii.sources.contracts import (
    CollectionContext,
    CollectionResult,
    Observation,
    SourceCollectionError,
    SourceDefinition,
    SourceDiagnostic,
    utc_now,
)
from fii.sources.http import fetch_public_resource
from fii.sources.raw_evidence import write_raw_evidence

IANA_RDAP_DNS_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
_RDAP_ACCEPT = "application/rdap+json, application/json"
_REGISTRAR_ROLE = "registrar"


class RDAPCollector:
    """Resolve one approved domain through IANA's RDAP bootstrap registry."""

    definition = SourceDefinition(
        source_id="rdap_domain",
        name="IANA-bootstrapped RDAP domain registration",
        adapter_version="1.0.0",
        source_class="public_api",
        description=(
            "Resolves one approved domain to its authoritative RDAP service using "
            "the IANA DNS bootstrap registry and collects one domain object."
        ),
        documentation_url="https://www.rfc-editor.org/rfc/rfc9224.html",
        terms_url="https://www.iana.org/assignments/rdap-dns/",
        requires_credentials=False,
        default_enabled=False,
        integration_kind="builtin",
        supported_observation_types=(
            "rdap_domain",
            "rdap_status",
            "rdap_event",
            "rdap_nameserver",
            "rdap_registrar",
        ),
    )

    def collect(self, context: CollectionContext) -> CollectionResult:
        if len(context.approved_domains) != 1:
            raise SourceCollectionError(
                "single_domain_required",
                "RDAP collection requires exactly one approved domain per invocation.",
            )
        try:
            domain = normalize_domain(context.approved_domains[0])
        except ValueError as exc:
            raise SourceCollectionError(
                "invalid_scope",
                "RDAP collection received an invalid approved domain.",
            ) from exc

        if context.fixture_path is not None:
            bootstrap, response, base_url, bootstrap_bytes, response_bytes, source_url = (
                _load_fixture(context, domain)
            )
        else:
            bootstrap_payload = fetch_public_resource(
                IANA_RDAP_DNS_BOOTSTRAP_URL,
                context,
                accept="application/json",
            )
            bootstrap_bytes = bootstrap_payload.body
            bootstrap = _decode_object(
                bootstrap_bytes,
                error_code="invalid_rdap_bootstrap",
                message="IANA RDAP bootstrap data was not valid UTF-8 JSON.",
            )
            base_url = _find_rdap_base_url(bootstrap, domain)
            if base_url is None:
                raise SourceCollectionError(
                    "rdap_authority_not_found",
                    "IANA's domain bootstrap registry has no HTTPS RDAP service for this domain.",
                )
            if context.minimum_request_interval_seconds:
                sleep(context.minimum_request_interval_seconds)
            lookup_url = f"{base_url.rstrip('/')}/domain/{quote(domain, safe='')}"
            response_payload = fetch_public_resource(
                lookup_url,
                context,
                accept=_RDAP_ACCEPT,
            )
            response_bytes = response_payload.body
            response = _decode_object(
                response_bytes,
                error_code="invalid_rdap_response",
                message="The authoritative RDAP service did not return valid UTF-8 JSON.",
            )
            source_url = response_payload.final_url

        returned_name = _text(response.get("ldhName")) or domain
        try:
            normalized_returned_name = normalize_domain(returned_name)
        except ValueError as exc:
            raise SourceCollectionError(
                "invalid_rdap_domain_name",
                "The RDAP response did not contain a valid domain name.",
            ) from exc
        if normalized_returned_name != domain:
            raise SourceCollectionError(
                "rdap_domain_mismatch",
                "The RDAP response domain did not match the requested approved domain.",
            )
        object_class = _text(response.get("objectClassName"))
        if object_class and object_class.casefold() != "domain":
            raise SourceCollectionError(
                "rdap_object_type_mismatch",
                "The RDAP response was not a domain object.",
            )

        bootstrap_publication = _text(bootstrap.get("publication"))
        registrar = _registrar_details(response)
        statuses = _string_list(response.get("status"))
        events = _event_records(response.get("events"))
        nameservers = _nameserver_records(response.get("nameservers"))
        has_redaction_markers = _contains_redaction_marker(response)

        sanitized_response = {
            "provider": "RDAP",
            "requested_domain": domain,
            "source_url": source_url,
            "bootstrap": {
                "version": _text(bootstrap.get("version")),
                "publication": bootstrap_publication,
                "matched_base_url": base_url,
            },
            "domain": {
                "object_class_name": object_class,
                "handle": _text(response.get("handle")),
                "ldh_name": normalized_returned_name,
                "unicode_name": _text(response.get("unicodeName")),
                "status": statuses,
                "events": events,
                "nameservers": nameservers,
                "registrar": registrar,
                "redacted_fields_present": has_redaction_markers,
            },
            "retention_note": (
                "Registrant, administrative and technical contact/vCard data are "
                "excluded from the retained payload."
            ),
        }
        bootstrap_evidence = write_raw_evidence(
            context,
            source_id=self.definition.source_id,
            original_name="iana-rdap-dns-bootstrap.json",
            content=bootstrap_bytes,
            media_type="application/json",
        )
        response_evidence = write_raw_evidence(
            context,
            source_id=self.definition.source_id,
            original_name="rdap-domain.json",
            content=json.dumps(
                sanitized_response,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            media_type="application/rdap+json",
            original_content_sha256=hashlib.sha256(response_bytes).hexdigest(),
        )

        collected_at = context.collected_at or utc_now()
        observations: list[Observation] = [
            Observation(
                observation_type="rdap_domain",
                observed_value=domain,
                collected_at=collected_at,
                source_url=source_url,
                raw_sha256=response_evidence.sha256,
                attributes={
                    "rdap_handle": _text(response.get("handle")),
                    "object_class_name": object_class or "domain",
                    "bootstrap_publication": bootstrap_publication,
                    "evidence_semantics": (
                        "Authoritative RDAP domain-registration record; not proof "
                        "of current DNS resolution, website operation or registrant identity."
                    ),
                },
            )
        ]
        observations.extend(
            Observation(
                observation_type="rdap_status",
                observed_value=status,
                collected_at=collected_at,
                source_url=source_url,
                raw_sha256=response_evidence.sha256,
                attributes={"domain": domain, "status_semantics": "registry-reported status"},
            )
            for status in statuses
        )
        observations.extend(
            Observation(
                observation_type="rdap_event",
                observed_value=event["action"],
                collected_at=collected_at,
                source_url=source_url,
                raw_sha256=response_evidence.sha256,
                observed_at=event["date"],
                attributes={"domain": domain},
            )
            for event in events
        )
        observations.extend(
            Observation(
                observation_type="rdap_nameserver",
                observed_value=nameserver,
                collected_at=collected_at,
                source_url=source_url,
                raw_sha256=response_evidence.sha256,
                attributes={
                    "domain": domain,
                    "evidence_semantics": (
                        "Nameserver listed in the domain registration response; "
                        "not a DNS resolution or ownership assertion."
                    ),
                },
            )
            for nameserver in nameservers
        )
        if registrar:
            observations.append(
                Observation(
                    observation_type="rdap_registrar",
                    observed_value=registrar.get("name") or registrar.get("handle") or "unknown",
                    collected_at=collected_at,
                    source_url=source_url,
                    raw_sha256=response_evidence.sha256,
                    attributes={
                        "domain": domain,
                        "iana_registrar_id": registrar.get("iana_registrar_id"),
                        "registrar_handle": registrar.get("handle"),
                        "evidence_semantics": "Registrar identity, not registrant or domain owner.",
                    },
                )
            )

        diagnostics: list[SourceDiagnostic] = []
        if has_redaction_markers:
            diagnostics.append(
                SourceDiagnostic(
                    "rdap_redaction_markers_present",
                    "The registry response contains one or more redaction indicators.",
                    "info",
                )
            )
        if any(entity.get("roles") for entity in _dict_list(response.get("entities"))):
            diagnostics.append(
                SourceDiagnostic(
                    "rdap_contact_entities_excluded",
                    (
                        "RDAP contact entities were not retained; only the registrar "
                        "identity was extracted."
                    ),
                    "info",
                )
            )

        evidence_refs = (bootstrap_evidence, response_evidence)
        return CollectionResult(
            source_id=self.definition.source_id,
            status="success",
            started_at=collected_at,
            finished_at=utc_now(),
            records_received=1,
            records_accepted=1,
            raw_evidence=evidence_refs,
            observations=tuple(observations),
            diagnostics=tuple(diagnostics),
        )


def _load_fixture(
    context: CollectionContext,
    requested_domain: str,
) -> tuple[dict[str, Any], dict[str, Any], str, bytes, bytes, str]:
    fixture = Path(context.fixture_path)  # type: ignore[arg-type]
    if fixture.is_symlink() or not fixture.is_file():
        raise SourceCollectionError(
            "fixture_unavailable",
            "The configured RDAP fixture is not a regular file.",
        )
    try:
        fixture_bytes = fixture.read_bytes()
    except OSError as exc:
        raise SourceCollectionError(
            "fixture_read_failed",
            "The configured RDAP fixture could not be read.",
        ) from exc
    if len(fixture_bytes) > context.max_fixture_bytes:
        raise SourceCollectionError(
            "fixture_too_large",
            "The configured RDAP fixture exceeds the configured size limit.",
        )
    fixture_data = _decode_object(
        fixture_bytes,
        error_code="invalid_rdap_fixture",
        message="The RDAP fixture was not valid UTF-8 JSON.",
    )
    bootstrap = fixture_data.get("bootstrap")
    response = fixture_data.get("domain_response")
    base_url = _text(fixture_data.get("rdap_base_url"))
    if not isinstance(bootstrap, dict) or not isinstance(response, dict):
        raise SourceCollectionError(
            "invalid_rdap_fixture_shape",
            "The RDAP fixture must contain bootstrap and domain_response objects.",
        )
    if base_url is None:
        base_url = _find_rdap_base_url(bootstrap, requested_domain)
    if base_url is None:
        raise SourceCollectionError(
            "rdap_authority_not_found",
            "The RDAP fixture bootstrap has no HTTPS service for the approved domain.",
        )
    _validate_rdap_base_url(base_url)
    lookup_url = f"{base_url.rstrip('/')}/domain/{quote(requested_domain, safe='')}"
    source_url = _text(fixture_data.get("source_url")) or lookup_url
    return (
        bootstrap,
        response,
        base_url,
        _json_bytes(bootstrap),
        _json_bytes(response),
        source_url,
    )


def _decode_object(
    raw: bytes,
    *,
    error_code: str,
    message: str,
) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceCollectionError(error_code, message) from exc
    if not isinstance(value, dict):
        raise SourceCollectionError(error_code, message)
    return value


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _find_rdap_base_url(bootstrap: dict[str, Any], domain: str) -> str | None:
    services = bootstrap.get("services")
    if not isinstance(services, list):
        raise SourceCollectionError(
            "invalid_rdap_bootstrap_shape",
            "IANA RDAP bootstrap data did not contain a services array.",
        )

    matches: list[tuple[int, str]] = []
    labels = domain.lower().split(".")
    for service in services:
        if not isinstance(service, list) or len(service) != 2:
            continue
        entries, urls = service
        if not isinstance(entries, list) or not isinstance(urls, list):
            continue
        for entry in entries:
            if not isinstance(entry, str):
                continue
            candidate = entry.lower().strip(".")
            candidate_labels = candidate.split(".")
            if (
                len(candidate_labels) <= len(labels)
                and labels[-len(candidate_labels):] == candidate_labels
            ):
                for url in urls:
                    if isinstance(url, str):
                        try:
                            _validate_rdap_base_url(url)
                        except ValueError:
                            continue
                        matches.append((len(candidate_labels), url))
    if not matches:
        return None
    longest = max(item[0] for item in matches)
    selected = sorted(url for size, url in matches if size == longest)[0]
    return selected if selected.endswith("/") else f"{selected}/"


def _validate_rdap_base_url(value: str) -> None:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid RDAP service URL port.") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (port is not None and port != 443)
    ):
        raise ValueError("RDAP service URLs must be HTTPS without credentials or custom ports.")


def _registrar_details(response: dict[str, Any]) -> dict[str, str] | None:
    for entity in _dict_list(response.get("entities")):
        roles = _string_list(entity.get("roles"))
        if _REGISTRAR_ROLE not in {role.casefold() for role in roles}:
            continue
        result: dict[str, str] = {}
        handle = _text(entity.get("handle"))
        if handle:
            result["handle"] = handle
        name = _vcard_org_or_fn(entity.get("vcardArray"))
        if name:
            result["name"] = name
        public_ids = entity.get("publicIds")
        if isinstance(public_ids, list):
            for public_id in public_ids:
                if not isinstance(public_id, dict):
                    continue
                if _text(public_id.get("type")) == "IANA Registrar ID":
                    identifier = _text(public_id.get("identifier"))
                    if identifier:
                        result["iana_registrar_id"] = identifier
        return result or None
    return None


def _vcard_org_or_fn(value: Any) -> str | None:
    if not isinstance(value, list) or len(value) != 2 or not isinstance(value[1], list):
        return None
    fields: dict[str, str] = {}
    for item in value[1]:
        if not isinstance(item, list) or len(item) < 4:
            continue
        key = item[0]
        content = item[3]
        if isinstance(key, str) and key.casefold() in {"org", "fn"} and isinstance(content, str):
            fields[key.casefold()] = content.strip()
    return fields.get("org") or fields.get("fn") or None


def _event_records(value: Any) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    if not isinstance(value, list):
        return events
    for item in value:
        if not isinstance(item, dict):
            continue
        action = _text(item.get("eventAction"))
        date = _text(item.get("eventDate"))
        if action and date:
            events.append({"action": action, "date": date})
    return events


def _nameserver_records(value: Any) -> list[str]:
    names: list[str] = []
    if not isinstance(value, list):
        return names
    for item in value:
        if not isinstance(item, dict):
            continue
        raw_name = _text(item.get("ldhName"))
        if not raw_name:
            continue
        try:
            normalized = normalize_domain(raw_name)
        except ValueError:
            continue
        if normalized not in names:
            names.append(normalized)
    return names


def _contains_redaction_marker(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if "redact" in str(key).casefold():
                return True
            if _contains_redaction_marker(item):
                return True
    elif isinstance(value, list):
        return any(_contains_redaction_marker(item) for item in value)
    elif isinstance(value, str):
        return value.strip().casefold() in {"redacted", "[redacted]", "withheld"}
    return False


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
