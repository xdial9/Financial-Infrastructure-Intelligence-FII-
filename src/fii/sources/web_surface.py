"""Offline analysis of saved, public-facing HTML and JavaScript surfaces.

This adapter never fetches script assets, executes JavaScript, opens a browser,
or contacts the site represented by the fixtures.
"""

from __future__ import annotations

import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from fii.sources.http import fetch_public_resource
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

_ALLOWED_SUFFIXES = {".html", ".htm", ".js"}
_MAX_FILES = 100
_FETCH_RE = re.compile(
    r"""\bfetch\s*\(\s*(['"\x60])(?P<url>[^'"\x60]{1,2048})\1"""
    r"""(?:\s*,\s*\{(?P<options>[^}]{0,1000})\})?""",
    re.IGNORECASE,
)
_AXIOS_RE = re.compile(
    r"""\baxios\.(?P<method>get|post|put|patch|delete|head|options)"""
    r"""\s*\(\s*(['"\x60])(?P<url>[^'"\x60]{1,2048})\2""",
    re.IGNORECASE,
)
_XHR_RE = re.compile(
    r"""\.open\(\s*(['"])(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\1"""
    r"""\s*,\s*(['"])(?P<url>[^'"]{1,2048})\3""",
    re.IGNORECASE,
)
_LITERAL_ROUTE_RE = re.compile(
    r"""(['"\x60])(?P<url>(?:https?://[^'"\x60\s]{1,2048}|"""
    r"""/(?:api|graphql|oauth|auth|connect|v[0-9]+)(?:/[^'"\x60\s]{0,512})?))\1""",
    re.IGNORECASE,
)
_SOURCE_MAP_RE = re.compile(r"sourceMappingURL\s*=\s*([^\s*]+)", re.IGNORECASE)
_API_DOC_RE = re.compile(
    r"""(?:openapi|swagger|redoc|api[-_/]?docs|developer[-_/]?portal|"""
    r"""graphql[-_/]?playground)(?:[^\s'"\x60<>]*)""",
    re.IGNORECASE,
)
_AUTH_MARKERS = (
    ("oauth2", re.compile(r"\boauth2?\b", re.IGNORECASE)),
    ("openid_connect", re.compile(r"\bopenid(?:\s+connect)?\b|\boidc\b", re.IGNORECASE)),
    (
        "pkce",
        re.compile(
            r"\bpkce\b|\bcode_challenge(?:_method)?\b|\bcode_verifier\b",
            re.IGNORECASE,
        ),
    ),
    ("saml", re.compile(r"\bsaml(?:2)?\b", re.IGNORECASE)),
    (
        "authorization_endpoint",
        re.compile(r"\bauthorization_endpoint\b|/authorize(?:\b|/)", re.IGNORECASE),
    ),
    ("token_endpoint", re.compile(r"\btoken_endpoint\b|/oauth/token(?:\b|/)", re.IGNORECASE)),
    ("userinfo_endpoint", re.compile(r"\buserinfo_endpoint\b|/userinfo(?:\b|/)", re.IGNORECASE)),
    ("jwks_uri", re.compile(r"\bjwks_uri\b|/\.well-known/jwks\.json", re.IGNORECASE)),
    ("session_route", re.compile(r"/(?:api/)?session(?:\b|/)", re.IGNORECASE)),
    ("auth0", re.compile(r"\bauth0\b", re.IGNORECASE)),
    ("okta", re.compile(r"\bokta\b", re.IGNORECASE)),
    ("aws_cognito", re.compile(r"\b(?:aws\s+)?cognito\b", re.IGNORECASE)),
    ("firebase_auth", re.compile(r"\bfirebase\s+auth\b", re.IGNORECASE)),
    ("clerk", re.compile(r"\bclerk(?:\.dev)?\b", re.IGNORECASE)),
    ("workos", re.compile(r"\bworkos\b", re.IGNORECASE)),
)
_INTEGRATION_MARKERS = (
    ("Plaid", re.compile(r"\bplaid(?:\s+link)?\b", re.IGNORECASE)),
    ("Stripe", re.compile(r"\bstripe\b", re.IGNORECASE)),
    ("MX Technologies", re.compile(r"\bmx\s+technologies\b|\bmx\.com\b", re.IGNORECASE)),
    ("Finicity", re.compile(r"\bfinicity\b", re.IGNORECASE)),
    ("Yodlee", re.compile(r"\byodlee\b", re.IGNORECASE)),
    ("Akoya", re.compile(r"\bakoya\b", re.IGNORECASE)),
    ("TrueLayer", re.compile(r"\btruelayer\b", re.IGNORECASE)),
    ("Flinks", re.compile(r"\bflinks\b", re.IGNORECASE)),
    ("Alloy", re.compile(r"\balloy\b", re.IGNORECASE)),
    ("Persona", re.compile(r"\bpersona\b", re.IGNORECASE)),
    ("Socure", re.compile(r"\bsocure\b", re.IGNORECASE)),
)


class _MarkupSignals(HTMLParser):
    """Extract only browser-visible asset and documentation references."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.script_sources: list[dict[str, str | None]] = []
        self.inline_scripts: list[str] = []
        self.documentation_links: list[str] = []
        self._inside_inline_script = False
        self._current_script: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag.lower() == "script":
            source = values.get("src")
            if source:
                self.script_sources.append(
                    {
                        "src": source,
                        "integrity": values.get("integrity"),
                        "type": values.get("type"),
                    }
                )
            else:
                self._inside_inline_script = True
                self._current_script = []
        href = values.get("href")
        if href and _API_DOC_RE.search(href):
            self.documentation_links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._inside_inline_script:
            self.inline_scripts.append("".join(self._current_script))
            self._current_script = []
            self._inside_inline_script = False

    def handle_data(self, data: str) -> None:
        if self._inside_inline_script:
            self._current_script.append(data)


class WebSurfaceFixtureCollector:
    """Catalog static website/API/auth signals from saved HTML and JS fixtures."""

    definition = SourceDefinition(
        source_id="web_surface",
        name="Public website JavaScript and API surface fixture",
        adapter_version="1.0.0",
        source_class="targeted_public_web",
        description=(
            "Statically analyzes supplied HTML and JavaScript snapshots. "
            "It records routes, asset references, source maps, API documentation "
            "markers, authentication architecture hints and vendor references. "
            "It never fetches or executes the referenced code."
        ),
        requires_credentials=False,
        default_enabled=False,
        integration_kind="builtin",
        supported_observation_types=(
            "javascript_asset",
            "api_endpoint",
            "api_documentation_reference",
            "source_map_reference",
            "auth_structure",
            "integration_reference",
        ),
    )

    def collect(self, context: CollectionContext) -> CollectionResult:
        if context.fixture_path is None:
            raise SourceCollectionError(
                "fixture_required",
                "Website-surface analysis requires a local fixture directory.",
            )

        root = Path(context.fixture_path).expanduser()
        if root.is_symlink() or not root.is_dir():
            raise SourceCollectionError(
                "fixture_directory_unavailable",
                "The website-surface fixture must be a regular directory.",
            )

        try:
            root_resolved = root.resolve(strict=True)
            files = [
                path
                for path in sorted(root.rglob("*"))
                if not path.is_symlink()
                and path.is_file()
                and path.suffix.lower() in _ALLOWED_SUFFIXES
            ]
        except OSError as exc:
            raise SourceCollectionError(
                "fixture_enumeration_failed",
                "The website-surface fixture directory could not be enumerated.",
            ) from exc

        if len(files) > _MAX_FILES:
            raise SourceCollectionError(
                "fixture_file_limit",
                f"Website-surface fixtures are limited to {_MAX_FILES} files.",
            )

        total_bytes = 0
        accepted_files = 0
        observations: list[Observation] = []
        raw_evidence = []
        diagnostics: list[SourceDiagnostic] = []
        seen: set[tuple[str, str, str]] = set()
        collected_at = context.collected_at or utc_now()

        for path in files:
            try:
                relative = path.resolve(strict=True).relative_to(root_resolved).as_posix()
                original_bytes = path.read_bytes()
            except (OSError, ValueError):
                diagnostics.append(
                    SourceDiagnostic(
                        "fixture_file_unreadable",
                        (
                            "A website-surface fixture file was skipped because it was "
                            "unreadable or outside its root."
                        ),
                    )
                )
                continue

            total_bytes += len(original_bytes)
            if total_bytes > context.max_fixture_bytes:
                raise SourceCollectionError(
                    "fixture_too_large",
                    "Website-surface fixtures exceed the configured total size limit.",
                )

            evidence = write_raw_evidence(
                context,
                source_id=self.definition.source_id,
                original_name=path.name,
                content=original_bytes,
                media_type=_media_type(path.suffix.lower()),
                redact_text=True,
            )
            raw_evidence.append(evidence)
            try:
                text = (Path(context.raw_directory) / evidence.relative_path).read_text(
                    encoding="utf-8"
                )
            except (OSError, UnicodeDecodeError):
                diagnostics.append(
                    SourceDiagnostic(
                        "fixture_not_text",
                        (
                            f"Fixture {relative} was preserved but could not be analyzed "
                            "as UTF-8 text."
                        ),
                    )
                )
                continue

            accepted_files += 1

            if evidence.redactions_applied:
                diagnostics.append(
                    SourceDiagnostic(
                        "sensitive_values_redacted",
                        (
                            f"{evidence.redactions_applied} likely credential value(s) "
                            f"were redacted in {relative}."
                        ),
                        "info",
                    )
                )

            analysis_units = [text]
            if path.suffix.lower() in {".html", ".htm"}:
                parser = _MarkupSignals()
                try:
                    parser.feed(text)
                    parser.close()
                except Exception:
                    diagnostics.append(
                        SourceDiagnostic(
                            "html_parse_partial",
                            f"Some markup signals could not be parsed in {relative}.",
                        )
                    )

                for item in parser.script_sources:
                    source_ref = _safe_reference(item["src"] or "")
                    if source_ref:
                        self._append(
                            observations,
                            seen,
                            Observation(
                                observation_type="javascript_asset",
                                observed_value=source_ref,
                                collected_at=collected_at,
                                source_url=context.source_url,
                                raw_sha256=evidence.sha256,
                                attributes={
                                    "evidence_file": relative,
                                    "integrity": item["integrity"],
                                    "script_type": item["type"],
                                    "fetched": False,
                                },
                            ),
                        )
                for href in parser.documentation_links:
                    self._append_doc_observation(
                        observations, seen, context, evidence.sha256, relative, href, collected_at
                    )
                analysis_units = [text, *parser.inline_scripts]

            for unit in analysis_units:
                self._analyze_text(
                    unit,
                    context=context,
                    evidence_sha256=evidence.sha256,
                    evidence_file=relative,
                    collected_at=collected_at,
                    observations=observations,
                    seen=seen,
                )

        status = "partial" if any(item.severity == "warning" for item in diagnostics) else "success"
        return CollectionResult(
            source_id=self.definition.source_id,
            status=status,
            started_at=collected_at,
            finished_at=utc_now(),
            records_received=len(files),
            records_accepted=accepted_files,
            raw_evidence=tuple(raw_evidence),
            observations=tuple(observations),
            diagnostics=tuple(diagnostics),
        )

    @staticmethod
    def _append(
        observations: list[Observation],
        seen: set[tuple[str, str, str]],
        observation: Observation,
    ) -> None:
        key = (
            observation.observation_type,
            observation.observed_value,
            str(observation.attributes.get("evidence_file", "")),
        )
        if key not in seen:
            seen.add(key)
            observations.append(observation)

    def _append_doc_observation(
        self,
        observations: list[Observation],
        seen: set[tuple[str, str, str]],
        context: CollectionContext,
        raw_sha256: str,
        evidence_file: str,
        reference: str,
        collected_at: str,
    ) -> None:
        cleaned = _safe_reference(reference)
        if not cleaned:
            return
        self._append(
            observations,
            seen,
            Observation(
                observation_type="api_documentation_reference",
                observed_value=cleaned,
                collected_at=collected_at,
                source_url=context.source_url,
                raw_sha256=raw_sha256,
                attributes={"evidence_file": evidence_file, "detection": "html_link"},
            ),
        )

    def _analyze_text(
        self,
        text: str,
        *,
        context: CollectionContext,
        evidence_sha256: str,
        evidence_file: str,
        collected_at: str,
        observations: list[Observation],
        seen: set[tuple[str, str, str]],
    ) -> None:
        endpoints: dict[tuple[str, str], str] = {}

        for match in _XHR_RE.finditer(text):
            method = match.group("method").upper()
            cleaned = _safe_reference(match.group("url"))
            if cleaned:
                endpoints[(method, cleaned)] = "xhr_open"

        for match in _AXIOS_RE.finditer(text):
            method = match.group("method").upper()
            cleaned = _safe_reference(match.group("url"))
            if cleaned:
                endpoints[(method, cleaned)] = "axios_method"

        for match in _FETCH_RE.finditer(text):
            cleaned = _safe_reference(match.group("url"))
            if not cleaned:
                continue
            options = match.group("options") or ""
            method_match = re.search(
                r"""\bmethod\s*:\s*(['"])(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\1""",
                options,
                re.IGNORECASE,
            )
            method = method_match.group(2).upper() if method_match else "UNKNOWN"
            endpoints[(method, cleaned)] = "fetch"

        for match in _LITERAL_ROUTE_RE.finditer(text):
            cleaned = _safe_reference(match.group("url"))
            if cleaned and not any(path == cleaned for _, path in endpoints):
                endpoints[("UNKNOWN", cleaned)] = "static_route_literal"

        for (method, endpoint), detection in sorted(endpoints.items()):
            self._append(
                observations,
                seen,
                Observation(
                    observation_type="api_endpoint",
                    observed_value=f"{method} {endpoint}",
                    collected_at=collected_at,
                    source_url=context.source_url,
                    raw_sha256=evidence_sha256,
                    attributes={
                        "method": method,
                        "path": endpoint,
                        "detection": detection,
                        "evidence_file": evidence_file,
                        "execution_tested": False,
                    },
                ),
            )

        for match in _SOURCE_MAP_RE.finditer(text):
            reference = _safe_reference(match.group(1).strip().rstrip("*/"))
            if reference:
                self._append(
                    observations,
                    seen,
                    Observation(
                        observation_type="source_map_reference",
                        observed_value=reference,
                        collected_at=collected_at,
                        source_url=context.source_url,
                        raw_sha256=evidence_sha256,
                        attributes={"evidence_file": evidence_file, "fetched": False},
                    ),
                )

        for match in _API_DOC_RE.finditer(text):
            reference = _safe_reference(match.group(0))
            if reference:
                self._append_doc_observation(
                    observations,
                    seen,
                    context,
                    evidence_sha256,
                    evidence_file,
                    reference,
                    collected_at,
                )

        for marker, pattern in _AUTH_MARKERS:
            if pattern.search(text):
                self._append(
                    observations,
                    seen,
                    Observation(
                        observation_type="auth_structure",
                        observed_value=marker,
                        collected_at=collected_at,
                        source_url=context.source_url,
                        raw_sha256=evidence_sha256,
                        attributes={
                            "evidence_file": evidence_file,
                            "signal_type": "static_marker",
                            "flow_validated": False,
                        },
                    ),
                )

        for provider, pattern in _INTEGRATION_MARKERS:
            if pattern.search(text):
                self._append(
                    observations,
                    seen,
                    Observation(
                        observation_type="integration_reference",
                        observed_value=provider,
                        collected_at=collected_at,
                        source_url=context.source_url,
                        raw_sha256=evidence_sha256,
                        attributes={
                            "evidence_file": evidence_file,
                            "signal_type": "static_reference",
                            "relationship_established": False,
                        },
                    ),
                )


class PublicWebsiteSnapshotCollector:
    """Fetch one approved public HTML page and its bounded script references.

    Requests are anonymous GETs over HTTPS, redirects are refused, and only
    hosts inside the explicit engagement domain scope are eligible for fetching.
    JavaScript is retained and parsed as text only; it is never executed.
    """

    definition = SourceDefinition(
        source_id="website_public",
        name="Approved public website HTML and JavaScript snapshot",
        adapter_version="1.0.0",
        source_class="targeted_public_web",
        description=(
            "Manually approved single-page HTTPS retrieval plus bounded, "
            "same-scope JavaScript asset retrieval. No login or state changes."
        ),
        requires_credentials=False,
        default_enabled=False,
        integration_kind="builtin",
        supported_observation_types=(
            "javascript_asset",
            "api_endpoint",
            "api_documentation_reference",
            "source_map_reference",
            "auth_structure",
            "integration_reference",
        ),
    )

    def collect(self, context: CollectionContext) -> CollectionResult:
        if not context.source_url:
            raise SourceCollectionError(
                "source_url_required",
                "Public website collection requires one explicit source URL.",
            )
        approved_domains = {
            normalize_domain(domain) for domain in context.approved_domains
        }
        if not approved_domains:
            raise SourceCollectionError(
                "empty_scope",
                "Public website collection requires approved seed domains.",
            )
        page_url = _approved_https_url(context.source_url, approved_domains)
        if page_url is None:
            raise SourceCollectionError(
                "url_out_of_scope",
                "The source URL must be HTTPS, contain no query or credentials, "
                "and belong to an approved domain.",
            )

        page = fetch_public_resource(
            page_url,
            context,
            accept="text/html,application/xhtml+xml",
        )
        if page.content_type not in {"text/html", "application/xhtml+xml"}:
            raise SourceCollectionError(
                "unexpected_page_content_type",
                "The approved page did not return an HTML content type.",
            )
        if len(page.body) > context.max_fixture_bytes:
            raise SourceCollectionError(
                "collection_too_large",
                "The page exceeds the configured total collection size limit.",
            )

        collected_at = context.collected_at or utc_now()
        raw_evidence = []
        observations: list[Observation] = []
        diagnostics: list[SourceDiagnostic] = []
        seen: set[tuple[str, str, str]] = set()
        analyzer = WebSurfaceFixtureCollector()

        page_evidence = write_raw_evidence(
            context,
            source_id=self.definition.source_id,
            original_name="index.html",
            content=page.body,
            media_type="text/html",
            redact_text=True,
        )
        raw_evidence.append(page_evidence)
        total_bytes = len(page.body)

        try:
            page_text = (
                Path(context.raw_directory) / page_evidence.relative_path
            ).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise SourceCollectionError(
                "page_not_utf8",
                "The approved HTML page could not be decoded as UTF-8 after redaction.",
            ) from exc

        parser = _MarkupSignals()
        try:
            parser.feed(page_text)
            parser.close()
        except Exception:
            diagnostics.append(
                SourceDiagnostic(
                    "html_parse_partial",
                    "Some HTML markup signals could not be parsed.",
                )
            )

        for item in parser.documentation_links:
            analyzer._append_doc_observation(
                observations,
                seen,
                context,
                page_evidence.sha256,
                "index.html",
                item,
                collected_at,
            )

        analyzer._analyze_text(
            page_text,
            context=context,
            evidence_sha256=page_evidence.sha256,
            evidence_file="index.html",
            collected_at=collected_at,
            observations=observations,
            seen=seen,
        )
        for inline_script in parser.inline_scripts:
            analyzer._analyze_text(
                inline_script,
                context=context,
                evidence_sha256=page_evidence.sha256,
                evidence_file="index.html",
                collected_at=collected_at,
                observations=observations,
                seen=seen,
            )

        records_received = 1
        records_accepted = 1
        fetched_assets = 0
        seen_asset_urls: set[str] = set()

        for item in parser.script_sources:
            source_ref = _safe_reference(item["src"] or "")
            if not source_ref:
                continue
            absolute_url = urljoin(page.final_url, source_ref)
            normalized_url = _approved_https_url(absolute_url, approved_domains)
            asset_url = _safe_reference(absolute_url) or source_ref

            if normalized_url is None:
                analyzer._append(
                    observations,
                    seen,
                    Observation(
                        observation_type="javascript_asset",
                        observed_value=asset_url,
                        collected_at=collected_at,
                        source_url=page.final_url,
                        raw_sha256=page_evidence.sha256,
                        attributes={
                            "evidence_file": "index.html",
                            "integrity": item["integrity"],
                            "script_type": item["type"],
                            "fetched": False,
                            "skip_reason": "outside_approved_https_scope",
                        },
                    ),
                )
                continue

            if normalized_url in seen_asset_urls:
                continue
            seen_asset_urls.add(normalized_url)

            if fetched_assets >= context.max_linked_assets:
                diagnostics.append(
                    SourceDiagnostic(
                        "asset_limit_reached",
                        "The configured JavaScript asset limit was reached.",
                    )
                )
                analyzer._append(
                    observations,
                    seen,
                    Observation(
                        observation_type="javascript_asset",
                        observed_value=asset_url,
                        collected_at=collected_at,
                        source_url=page.final_url,
                        raw_sha256=page_evidence.sha256,
                        attributes={
                            "evidence_file": "index.html",
                            "fetched": False,
                            "skip_reason": "asset_limit_reached",
                        },
                    ),
                )
                continue

            if context.minimum_request_interval_seconds:
                time.sleep(context.minimum_request_interval_seconds)

            try:
                script = fetch_public_resource(
                    normalized_url,
                    context,
                    accept="application/javascript,text/javascript,*/*;q=0.1",
                )
            except SourceCollectionError as exc:
                diagnostics.append(
                    SourceDiagnostic(
                        exc.code,
                        f"A referenced script asset was not fetched: {exc.message}",
                    )
                )
                analyzer._append(
                    observations,
                    seen,
                    Observation(
                        observation_type="javascript_asset",
                        observed_value=asset_url,
                        collected_at=collected_at,
                        source_url=page.final_url,
                        raw_sha256=page_evidence.sha256,
                        attributes={
                            "evidence_file": "index.html",
                            "fetched": False,
                            "skip_reason": exc.code,
                        },
                    ),
                )
                continue

            records_received += 1
            if script.content_type not in {
                "application/javascript",
                "text/javascript",
                "application/x-javascript",
            } and not urlsplit(normalized_url).path.lower().endswith((".js", ".mjs")):
                diagnostics.append(
                    SourceDiagnostic(
                        "unexpected_script_content_type",
                        "A referenced script did not return a JavaScript content type.",
                    )
                )
                continue
            total_bytes += len(script.body)
            if total_bytes > context.max_fixture_bytes:
                diagnostics.append(
                    SourceDiagnostic(
                        "collection_size_limit_reached",
                        "Additional JavaScript assets were skipped at the total size limit.",
                    )
                )
                break
            try:
                script.body.decode("utf-8")
            except UnicodeDecodeError:
                diagnostics.append(
                    SourceDiagnostic(
                        "script_not_utf8",
                        "A referenced JavaScript asset was skipped because it was not UTF-8.",
                    )
                )
                continue

            evidence = write_raw_evidence(
                context,
                source_id=self.definition.source_id,
                original_name=Path(urlsplit(normalized_url).path).name or "asset.js",
                content=script.body,
                media_type="application/javascript",
                redact_text=True,
            )
            raw_evidence.append(evidence)
            fetched_assets += 1
            records_accepted += 1
            analyzer._append(
                observations,
                seen,
                Observation(
                    observation_type="javascript_asset",
                    observed_value=asset_url,
                    collected_at=collected_at,
                    source_url=page.final_url,
                    raw_sha256=evidence.sha256,
                    attributes={
                        "evidence_file": evidence.relative_path,
                        "integrity": item["integrity"],
                        "script_type": item["type"],
                        "fetched": True,
                    },
                ),
            )
            try:
                script_text = (
                    Path(context.raw_directory) / evidence.relative_path
                ).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise EvidenceWriteError(
                    "Retained JavaScript evidence could not be read for analysis."
                ) from exc
            analyzer._analyze_text(
                script_text,
                context=context,
                evidence_sha256=evidence.sha256,
                evidence_file=evidence.relative_path,
                collected_at=collected_at,
                observations=observations,
                seen=seen,
            )

        status = (
            "partial"
            if any(item.severity == "warning" for item in diagnostics)
            else "success"
        )
        return CollectionResult(
            source_id=self.definition.source_id,
            status=status,
            started_at=collected_at,
            finished_at=utc_now(),
            records_received=records_received,
            records_accepted=records_accepted,
            raw_evidence=tuple(raw_evidence),
            observations=tuple(observations),
            diagnostics=tuple(diagnostics),
        )


def _approved_https_url(value: str, approved_domains: set[str]) -> str | None:
    """Return a normalized URL only when it is HTTPS and in approved scope."""
    try:
        parts = urlsplit(value)
        if (
            parts.scheme.lower() != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.port not in {None, 443}
        ):
            return None
        hostname = normalize_domain(parts.hostname)
    except (ValueError, TypeError):
        return None
    if not any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in approved_domains
    ):
        return None
    path = parts.path or "/"
    return urlunsplit(("https", hostname, path, "", ""))


def _media_type(suffix: str) -> str:
    return "text/html" if suffix in {".html", ".htm"} else "application/javascript"


def _safe_reference(value: str) -> str | None:
    """Keep route/host/query-key intelligence without retaining query secrets."""
    candidate = value.strip()
    if not candidate or len(candidate) > 2048:
        return None
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    if parts.scheme and parts.scheme.lower() not in {"http", "https"}:
        return None
    if parts.scheme and not parts.netloc:
        return None
    safe_query: list[tuple[str, str]] = []
    for key, query_value in parse_qsl(parts.query, keep_blank_values=True):
        if re.search(
            r"(?:token|secret|password|api[_-]?key|signature|authorization|^code$|^auth$)",
            key,
            re.IGNORECASE,
        ):
            safe_query.append((key, "[REDACTED]"))
        else:
            safe_query.append((key, query_value))
    safe_netloc = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit(
        (
            parts.scheme.lower(),
            safe_netloc,
            parts.path,
            urlencode(safe_query),
            "",
        )
    )
