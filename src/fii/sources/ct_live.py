"""Manual, one-page crt.live Certificate Transparency API adapter."""

from __future__ import annotations

import hashlib
import json
from urllib.parse import quote

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

API_BASE = "https://crt.live/api/v1/domain"


class CTLiveCollector:
    """Collect one page of public CT hostname observations for one approved domain."""

    definition = SourceDefinition(
        source_id="ct_live",
        name="crt.live public Certificate Transparency API",
        adapter_version="1.0.0",
        source_class="public_api",
        description=(
            "One manually approved HTTPS GET to crt.live for a single approved "
            "domain. Returns CT-observed hostnames and first-seen dates only."
        ),
        documentation_url="https://crt.live/about",
        requires_credentials=False,
        default_enabled=False,
        integration_kind="provider_api",
        supported_observation_types=("ct_hostname",),
    )

    def __init__(self, *, limit: int = 1000) -> None:
        if isinstance(limit, bool) or not 1 <= limit <= 10000:
            raise ValueError("crt.live page limit must be between 1 and 10000.")
        self.limit = limit

    def collect(self, context: CollectionContext) -> CollectionResult:
        if len(context.approved_domains) != 1:
            raise SourceCollectionError(
                "single_domain_required",
                "crt.live collection requires exactly one approved seed domain per request.",
            )
        try:
            domain = normalize_domain(context.approved_domains[0])
        except ValueError as exc:
            raise SourceCollectionError(
                "invalid_scope",
                "crt.live collection received an invalid approved domain.",
            ) from exc

        url = (
            f"{API_BASE}/{quote(domain, safe='')}"
            f"?sort=recent&limit={self.limit}"
        )
        payload = fetch_public_resource(
            url,
            context,
            accept="application/json",
        )
        source_digest = hashlib.sha256(payload.body).hexdigest()

        try:
            response = json.loads(payload.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceCollectionError(
                "invalid_provider_response",
                "crt.live did not return valid UTF-8 JSON.",
            ) from exc
        if not isinstance(response, dict) or not isinstance(response.get("names"), list):
            raise SourceCollectionError(
                "invalid_provider_response",
                "crt.live JSON did not contain the documented names array.",
            )

        names = response["names"]
        collected_at = context.collected_at or utc_now()
        pending_names: list[tuple[str, str | None]] = []
        retained_names: list[dict[str, str | None]] = []
        diagnostics: list[SourceDiagnostic] = []

        for item in names:
            if isinstance(item, str):
                raw_name = item
                first_seen = None
            elif isinstance(item, dict) and isinstance(item.get("name"), str):
                raw_name = item["name"]
                first_seen = (
                    item.get("first_seen")
                    if isinstance(item.get("first_seen"), str)
                    else None
                )
            else:
                diagnostics.append(
                    SourceDiagnostic(
                        "invalid_provider_record",
                        "A crt.live name record did not match the documented response shape.",
                    )
                )
                continue

            candidate = raw_name.strip().removeprefix("*.")
            try:
                normalized = normalize_domain(candidate)
            except ValueError:
                diagnostics.append(
                    SourceDiagnostic(
                        "invalid_dns_name",
                        "A crt.live result contained a hostname that could not be normalized.",
                    )
                )
                continue
            if not _in_scope(normalized, domain):
                continue

            retained_names.append({"name": normalized, "first_seen": first_seen})
            pending_names.append((normalized, first_seen))

        sanitized_payload = json.dumps(
            {
                "provider": "crt.live",
                "requested_domain": domain,
                "names": retained_names,
                "source_response_sha256": source_digest,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        evidence = write_raw_evidence(
            context,
            source_id=self.definition.source_id,
            original_name="crt-live.json",
            content=sanitized_payload,
            media_type="application/json",
            original_content_sha256=source_digest,
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

        observations = [
            Observation(
                observation_type="ct_hostname",
                observed_value=name,
                collected_at=collected_at,
                source_url=payload.final_url,
                raw_sha256=evidence.sha256,
                observed_at=first_seen,
                attributes={
                    "provider": "crt.live",
                    "apex": response.get("apex"),
                    "first_seen_precision": "day",
                    "evidence_semantics": (
                        "Certificate Transparency hostname observation; "
                        "not proof the host currently exists or resolves."
                    ),
                },
            )
            for name, first_seen in pending_names
        ]

        if response.get("has_more") is True or response.get("total_capped") is True:
            diagnostics.append(
                SourceDiagnostic(
                    "provider_page_incomplete",
                    (
                        "crt.live indicates additional or capped results. "
                        "Only this page was collected; pagination is not automatic."
                    ),
                )
            )

        status = "partial" if any(item.severity == "warning" for item in diagnostics) else "success"
        return CollectionResult(
            source_id=self.definition.source_id,
            status=status,
            started_at=collected_at,
            finished_at=utc_now(),
            records_received=len(names),
            records_accepted=len(observations),
            raw_evidence=(evidence,),
            observations=tuple(observations),
            diagnostics=tuple(diagnostics),
        )


def _in_scope(domain: str, approved_domain: str) -> bool:
    return domain == approved_domain or domain.endswith(f".{approved_domain}")
