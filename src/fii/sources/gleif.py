"""GLEIF Global LEI Index API enrichment adapter.

Name-search matches remain candidates. An API match does not, by itself, prove
that a record is the same organization as an operator's seed or that it uses a
particular financial product, provider or service.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

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

GLEIF_API_BASE = "https://api.gleif.org/api/v1"
_LEI_RE = re.compile(r"^[A-Z0-9]{20}$")
_GLEIF_ACCEPT = "application/vnd.api+json, application/json"


class GLEIFCollector:
    """Collect one page or one exact LEI record from the GLEIF public API."""

    definition = SourceDefinition(
        source_id="gleif_lei",
        name="GLEIF Global LEI Index",
        adapter_version="1.0.0",
        source_class="public_api",
        description=(
            "Enriches one approved legal-entity name or LEI with GLEIF legal-entity "
            "reference data. Name searches produce candidates, not verified identity matches."
        ),
        documentation_url="https://www.gleif.org/en/lei-data/gleif-api",
        terms_url="https://www.gleif.org/en/meta/lei-data-terms-of-use",
        requires_credentials=False,
        default_enabled=False,
        integration_kind="provider_api",
        supported_observation_types=(
            "legal_entity_identifier",
            "lei_legal_name",
            "lei_entity_status",
            "lei_registration_status",
            "lei_jurisdiction",
            "lei_legal_form",
            "gleif_relationship_reference",
        ),
    )

    def __init__(self, *, page_size: int = 10) -> None:
        if isinstance(page_size, bool) or not 1 <= page_size <= 50:
            raise ValueError("GLEIF page size must be between 1 and 50.")
        self.page_size = page_size

    def collect(self, context: CollectionContext) -> CollectionResult:
        organization_names = tuple(
            name.strip()
            for name in context.organization_names
            if isinstance(name, str) and name.strip()
        )
        legal_entity_identifiers = tuple(
            identifier.strip().upper()
            for identifier in context.legal_entity_identifiers
            if isinstance(identifier, str) and identifier.strip()
        )
        if len(organization_names) + len(legal_entity_identifiers) != 1:
            raise SourceCollectionError(
                "single_entity_query_required",
                "GLEIF collection requires exactly one approved organization name or LEI.",
            )

        if organization_names:
            query = organization_names[0]
            if len(query) > 240 or any(ord(char) < 32 for char in query):
                raise SourceCollectionError(
                    "invalid_entity_query",
                    "The GLEIF organization-name query is too long or contains control characters.",
                )
            request_url = _name_search_url(query, self.page_size)
            match_method = "name_search_candidate"
            query_value = query
        else:
            lei = legal_entity_identifiers[0]
            if not _LEI_RE.fullmatch(lei):
                raise SourceCollectionError(
                    "invalid_lei",
                    (
                        "A legal entity identifier must be exactly 20 uppercase "
                        "alphanumeric characters."
                    ),
                )
            request_url = f"{GLEIF_API_BASE}/lei-records/{lei}"
            match_method = "exact_lei_lookup"
            query_value = lei

        if context.fixture_path is not None:
            response, response_bytes, source_url = _load_fixture(context, request_url)
        else:
            payload = fetch_public_resource(
                request_url,
                context,
                accept=_GLEIF_ACCEPT,
            )
            response = _decode_json(
                payload.body,
                error_code="invalid_gleif_response",
                message="GLEIF did not return valid UTF-8 JSON.",
            )
            response_bytes = payload.body
            source_url = payload.final_url

        records = _records_from_response(response)
        received = len(records)
        sanitized_records: list[dict[str, Any]] = []
        observations: list[Observation] = []
        diagnostics: list[SourceDiagnostic] = []
        collected_at = context.collected_at or utc_now()
        accepted = 0

        for index, record in enumerate(records):
            if not isinstance(record, dict):
                diagnostics.append(
                    SourceDiagnostic(
                        "invalid_gleif_record",
                        f"GLEIF record {index} was skipped because it was not an object.",
                    )
                )
                continue
            lei = _text(record.get("id"))
            attributes = record.get("attributes")
            if not isinstance(attributes, dict):
                attributes = {}
            entity = attributes.get("entity")
            registration = attributes.get("registration")
            if not isinstance(entity, dict):
                entity = {}
            if not isinstance(registration, dict):
                registration = {}

            legal_name = _nested_text(entity, "legalName", "name")
            entity_status = _text(entity.get("status"))
            registration_status = _text(registration.get("status"))
            jurisdiction = _text(entity.get("jurisdiction"))
            legal_form = _nested_text(entity, "legalForm", "id")
            legal_address = entity.get("legalAddress")
            country = (
                _text(legal_address.get("country"))
                if isinstance(legal_address, dict)
                else None
            )
            registration_date = _text(registration.get("initialRegistrationDate"))
            last_update = _text(
                registration.get("lastUpdateDate")
                or registration.get("lastUpdateDateTime")
            )
            managing_lou = _text(registration.get("managingLou") or registration.get("managingLOU"))
            registered_as = _text(entity.get("registeredAs"))
            authority_id = _nested_text(entity, "registrationAuthority", "id")
            relationship_refs = _relationship_references(record.get("relationships"))

            safe_record = {
                "lei": lei,
                "legal_name": legal_name,
                "entity_status": entity_status,
                "registration_status": registration_status,
                "jurisdiction": jurisdiction,
                "legal_form": legal_form,
                "legal_address_country": country,
                "initial_registration_date": registration_date,
                "last_update_date": last_update,
                "managing_lou": managing_lou,
                "registered_as": registered_as,
                "registration_authority_id": authority_id,
                "relationship_references": relationship_refs,
            }
            sanitized_records.append(safe_record)
            if not lei:
                diagnostics.append(
                    SourceDiagnostic(
                        "gleif_record_missing_lei",
                        f"GLEIF record {index} did not contain a record identifier.",
                    )
                )
                continue

            common_attributes = {
                "provider": "GLEIF Global LEI Index",
                "lei": lei,
                "query_value": query_value,
                "match_method": match_method,
                "candidate_match": match_method == "name_search_candidate",
                "registration_last_update": last_update,
                "golden_copy_publication": _golden_copy_publication(response),
            }
            observations.append(
                Observation(
                    observation_type="legal_entity_identifier",
                    observed_value=lei,
                    collected_at=collected_at,
                    source_url=source_url,
                    raw_sha256="0" * 64,
                    observed_at=last_update,
                    attributes={
                        **common_attributes,
                        "legal_name": legal_name,
                        "entity_status": entity_status,
                        "registration_status": registration_status,
                        "jurisdiction": jurisdiction,
                    },
                )
            )
            if legal_name:
                observations.append(
                    Observation(
                        observation_type="lei_legal_name",
                        observed_value=legal_name,
                        collected_at=collected_at,
                        source_url=source_url,
                        raw_sha256="0" * 64,
                        observed_at=last_update,
                        attributes=common_attributes,
                    )
                )
            if entity_status:
                observations.append(
                    Observation(
                        observation_type="lei_entity_status",
                        observed_value=entity_status,
                        collected_at=collected_at,
                        source_url=source_url,
                        raw_sha256="0" * 64,
                        observed_at=last_update,
                        attributes=common_attributes,
                    )
                )
            if registration_status:
                observations.append(
                    Observation(
                        observation_type="lei_registration_status",
                        observed_value=registration_status,
                        collected_at=collected_at,
                        source_url=source_url,
                        raw_sha256="0" * 64,
                        observed_at=last_update,
                        attributes=common_attributes,
                    )
                )
            if jurisdiction:
                observations.append(
                    Observation(
                        observation_type="lei_jurisdiction",
                        observed_value=jurisdiction,
                        collected_at=collected_at,
                        source_url=source_url,
                        raw_sha256="0" * 64,
                        observed_at=last_update,
                        attributes=common_attributes,
                    )
                )
            if legal_form:
                observations.append(
                    Observation(
                        observation_type="lei_legal_form",
                        observed_value=legal_form,
                        collected_at=collected_at,
                        source_url=source_url,
                        raw_sha256="0" * 64,
                        observed_at=last_update,
                        attributes=common_attributes,
                    )
                )
            for relationship in relationship_refs:
                observations.append(
                    Observation(
                        observation_type="gleif_relationship_reference",
                        observed_value=relationship["id"],
                        collected_at=collected_at,
                        source_url=source_url,
                        raw_sha256="0" * 64,
                        observed_at=last_update,
                        attributes={
                            **common_attributes,
                            "relationship_type": relationship["type"],
                            "resource_type": relationship.get("resource_type"),
                            "evidence_semantics": (
                                "Relationship reference reported in the GLEIF response; "
                                "no linked record was fetched or resolved."
                            ),
                        },
                    )
                )
            accepted += 1

        evidence_payload = {
            "provider": "GLEIF Global LEI Index",
            "source_url": source_url,
            "query": {
                "match_method": match_method,
                "value": query_value,
                "page_size": self.page_size if match_method == "name_search_candidate" else 1,
            },
            "golden_copy_publication": _golden_copy_publication(response),
            "pagination": _pagination(response),
            "records": sanitized_records,
            "retention_note": (
                "Only legal-entity identifiers, public legal reference fields and "
                "relationship references are retained; contact/address detail is excluded."
            ),
        }
        evidence = write_raw_evidence(
            context,
            source_id=self.definition.source_id,
            original_name="gleif-lei-records.json",
            content=json.dumps(
                evidence_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            media_type="application/vnd.api+json",
            original_content_sha256=hashlib.sha256(response_bytes).hexdigest(),
        )
        observations = [
            Observation(
                observation_type=item.observation_type,
                observed_value=item.observed_value,
                collected_at=item.collected_at,
                source_url=item.source_url,
                raw_sha256=evidence.sha256,
                verification_state=item.verification_state,
                observed_at=item.observed_at,
                attributes=item.attributes,
            )
            for item in observations
        ]
        if not records:
            diagnostics.append(
                SourceDiagnostic(
                    "gleif_no_matches",
                    "GLEIF returned no LEI records for the supplied query.",
                    "info",
                )
            )
        return CollectionResult(
            source_id=self.definition.source_id,
            status=(
                "partial"
                if any(item.severity == "warning" for item in diagnostics)
                else "success"
            ),
            started_at=collected_at,
            finished_at=utc_now(),
            records_received=received,
            records_accepted=accepted,
            raw_evidence=(evidence,),
            observations=tuple(observations),
            diagnostics=tuple(diagnostics),
        )


def _name_search_url(query: str, page_size: int) -> str:
    params = urlencode(
        {
            "filter[entity.legalName]": query,
            "page[size]": str(page_size),
        }
    )
    return f"{GLEIF_API_BASE}/lei-records?{params}"


def _load_fixture(
    context: CollectionContext,
    request_url: str,
) -> tuple[dict[str, Any], bytes, str]:
    fixture = Path(context.fixture_path)  # type: ignore[arg-type]
    if fixture.is_symlink() or not fixture.is_file():
        raise SourceCollectionError(
            "fixture_unavailable",
            "The configured GLEIF fixture is not a regular file.",
        )
    try:
        fixture_bytes = fixture.read_bytes()
    except OSError as exc:
        raise SourceCollectionError(
            "fixture_read_failed",
            "The configured GLEIF fixture could not be read.",
        ) from exc
    if len(fixture_bytes) > context.max_fixture_bytes:
        raise SourceCollectionError(
            "fixture_too_large",
            "The configured GLEIF fixture exceeds the configured size limit.",
        )
    fixture_data = _decode_json(
        fixture_bytes,
        error_code="invalid_gleif_fixture",
        message="The GLEIF fixture was not valid UTF-8 JSON.",
    )
    response = fixture_data.get("response")
    if not isinstance(response, dict):
        raise SourceCollectionError(
            "invalid_gleif_fixture_shape",
            "The GLEIF fixture must contain a response object.",
        )
    return response, _json_bytes(response), _text(fixture_data.get("source_url")) or request_url


def _decode_json(raw: bytes, *, error_code: str, message: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceCollectionError(error_code, message) from exc
    if not isinstance(value, dict):
        raise SourceCollectionError(error_code, message)
    return value


def _records_from_response(response: dict[str, Any]) -> list[Any]:
    if "errors" in response and "data" not in response:
        raise SourceCollectionError(
            "gleif_api_error",
            "GLEIF returned an API error document instead of an LEI record response.",
        )
    data = response.get("data")
    if data is None:
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data
    raise SourceCollectionError(
        "invalid_gleif_response_shape",
        "GLEIF JSON:API response data must be an object or array.",
    )


def _relationship_references(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return []
    result: list[dict[str, str]] = []
    for relationship_type, relationship in sorted(value.items()):
        if not isinstance(relationship, dict):
            continue
        data = relationship.get("data")
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            identifier = _text(item.get("id"))
            resource_type = _text(item.get("type"))
            if identifier:
                result.append(
                    {
                        "type": str(relationship_type),
                        "id": identifier,
                        **({"resource_type": resource_type} if resource_type else {}),
                    }
                )
    return result


def _nested_text(value: dict[str, Any], parent: str, child: str) -> str | None:
    nested = value.get(parent)
    return _text(nested.get(child)) if isinstance(nested, dict) else None


def _golden_copy_publication(response: dict[str, Any]) -> str | None:
    meta = response.get("meta")
    if not isinstance(meta, dict):
        return None
    golden_copy = meta.get("goldenCopy")
    if not isinstance(golden_copy, dict):
        return None
    return _text(golden_copy.get("publishDate") or golden_copy.get("publicationDate"))


def _pagination(response: dict[str, Any]) -> dict[str, Any]:
    meta = response.get("meta")
    if not isinstance(meta, dict):
        return {}
    pagination = meta.get("pagination")
    if not isinstance(pagination, dict):
        return {}
    allowed = ("total", "currentPage", "perPage", "lastPage")
    return {key: pagination[key] for key in allowed if isinstance(pagination.get(key), (str, int))}


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
