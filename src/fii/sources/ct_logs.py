"""Fixture-backed Certificate Transparency collector."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
from fii.sources.raw_evidence import write_raw_evidence


class CTLogsFixtureCollector:
    """Parse saved CT-provider JSON without making a network request."""

    definition = SourceDefinition(
        source_id="ct_logs",
        name="Certificate Transparency fixture",
        adapter_version="1.0.0",
        source_class="public_api",
        description=(
            "Parses operator-supplied Certificate Transparency JSON fixtures. "
            "No CT provider or institution is contacted."
        ),
        documentation_url="https://www.rfc-editor.org/rfc/rfc9162.html",
        requires_credentials=False,
        default_enabled=False,
        integration_kind="builtin",
        supported_observation_types=("certificate_name",),
    )

    def collect(self, context: CollectionContext) -> CollectionResult:
        if context.fixture_path is None:
            raise SourceCollectionError(
                "fixture_required",
                "CT collection requires a local JSON fixture path.",
            )

        try:
            approved_domains = {
                normalize_domain(domain) for domain in context.approved_domains
            }
        except ValueError as exc:
            raise SourceCollectionError(
                "invalid_scope",
                "CT collection received a malformed approved seed domain.",
            ) from exc
        if not approved_domains:
            raise SourceCollectionError(
                "empty_scope",
                "CT collection requires at least one approved seed domain.",
            )

        fixture = Path(context.fixture_path)
        if fixture.is_symlink() or not fixture.is_file():
            raise SourceCollectionError(
                "fixture_unavailable",
                "The configured CT fixture is not a regular file.",
            )
        try:
            fixture_bytes = fixture.read_bytes()
        except OSError as exc:
            raise SourceCollectionError(
                "fixture_read_failed",
                "The CT fixture could not be read.",
            ) from exc
        if len(fixture_bytes) > context.max_fixture_bytes:
            raise SourceCollectionError(
                "fixture_too_large",
                "The CT fixture exceeds the configured size limit.",
            )

        evidence = write_raw_evidence(
            context,
            source_id=self.definition.source_id,
            original_name=fixture.name,
            content=fixture_bytes,
            media_type="application/json",
        )
        try:
            payload = json.loads(fixture_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceCollectionError(
                "invalid_ct_fixture",
                "The CT fixture is not valid UTF-8 JSON; its raw bytes were preserved.",
                raw_evidence=(evidence,),
            ) from exc

        if isinstance(payload, list):
            records = payload
            source_url = context.source_url
        elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
            records = payload["records"]
            source_url = payload.get("source_url") or context.source_url
        else:
            raise SourceCollectionError(
                "invalid_ct_fixture_shape",
                "The CT fixture must be a JSON array or an object containing a records array.",
                raw_evidence=(evidence,),
            )

        collected_at = context.collected_at or utc_now()
        observations: list[Observation] = []
        diagnostics: list[SourceDiagnostic] = []
        accepted_records = 0

        for index, record in enumerate(records):
            if not isinstance(record, dict):
                diagnostics.append(
                    SourceDiagnostic(
                        "invalid_record",
                        f"CT record {index} was skipped because it was not an object.",
                    )
                )
                continue

            names = _record_names(record)
            if not names:
                diagnostics.append(
                    SourceDiagnostic(
                        "record_without_names",
                        f"CT record {index} did not contain a DNS name.",
                    )
                )
                continue

            certificate_id = _string_value(record.get("id"))
            record_observations_before = len(observations)
            for raw_name in names:
                candidate = raw_name.strip().removeprefix("*.")
                try:
                    domain = normalize_domain(candidate)
                except ValueError:
                    diagnostics.append(
                        SourceDiagnostic(
                            "invalid_dns_name",
                            f"CT record {index} contained a name that could not be normalized.",
                        )
                    )
                    continue

                if not _in_scope(domain, approved_domains):
                    continue

                observations.append(
                    Observation(
                        observation_type="certificate_name",
                        observed_value=domain,
                        collected_at=collected_at,
                        source_url=source_url,
                        raw_sha256=evidence.sha256,
                        attributes={
                            "certificate_id": certificate_id,
                            "common_name": _string_value(record.get("common_name")),
                            "issuer": _string_value(
                                record.get("issuer_name") or record.get("issuer")
                            ),
                            "not_before": _string_value(record.get("not_before")),
                            "not_after": _string_value(record.get("not_after")),
                            "scope_match": True,
                            "relationship_claim": "none",
                        },
                    )
                )

            if len(observations) > record_observations_before:
                accepted_records += 1

        status = "partial" if diagnostics else "success"
        return CollectionResult(
            source_id=self.definition.source_id,
            status=status,
            started_at=collected_at,
            finished_at=utc_now(),
            records_received=len(records),
            records_accepted=accepted_records,
            raw_evidence=(evidence,),
            observations=tuple(observations),
            diagnostics=tuple(diagnostics),
        )


def _record_names(record: dict[str, Any]) -> list[str]:
    values = record.get("dns_names")
    if isinstance(values, list):
        return [item for item in values if isinstance(item, str) and item.strip()]

    name_value = record.get("name_value")
    if isinstance(name_value, str) and name_value.strip():
        return [
            item.strip()
            for item in name_value.replace(",", "\n").splitlines()
            if item.strip()
        ]

    common_name = record.get("common_name")
    if isinstance(common_name, str) and common_name.strip():
        return [common_name.strip()]
    return []


def _string_value(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _in_scope(domain: str, approved_domains: set[str]) -> bool:
    return any(
        domain == approved or domain.endswith(f".{approved}")
        for approved in approved_domains
    )
