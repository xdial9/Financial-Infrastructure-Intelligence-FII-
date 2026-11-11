# Block 06 — Collector contract and first public-source collectors

**Branch:** `build/block-06-collector-contract-passive-sources`  
**Base branch:** `build/block-05-sqlite-evidence-store`  
**Base commit:** `f2d1b6ed1f40c91f978b9cb1121967100295b206`  
**Pull request:** [Draft PR #3](https://github.com/xdial9/Financial-Infrastructure-Intelligence-FII-/pull/3)  
**Verified code head:** `8607e615061278d3c1b3ac31922ff9af85393bf6`

## Implemented scope

### Collector contracts and integration seams
- Added typed `SourceDefinition`, `CollectionContext`, `RawEvidenceReference`, `Observation`, `SourceDiagnostic` and `CollectionResult` records.
- Added stable source IDs, adapter versions, source classes, integration kinds and supported observation types.
- Added a deterministic fixed registry. Current IDs: `ct_live`, `ct_logs`, `web_surface` and `website_public`.
- The registry models built-in, provider-API and external-tool adapters without arbitrary runtime plugin loading.
- Added `run_collector` with structured, sanitized source logging and expected source-error conversion. Evidence-write failures remain fatal and propagate to the caller.
- Added explicit live-collection controls to the context: live collection defaults off; HTTPS requests have bounded timeouts and response sizes; JavaScript asset count and request spacing are configurable with conservative defaults.

### Certificate Transparency
- `CTLogsFixtureCollector` parses supplied JSON fixtures without network access and emits hostname observations only for exact/subdomain matches under approved seed domains.
- `CTLiveCollector` uses one manually approved HTTPS GET to crt.live for exactly one approved seed domain and one provider page. Default page size is 1,000; hard maximum is 10,000. It does not paginate or retry automatically.
- The live adapter retains only in-scope names in its stored evidence payload while preserving both the original provider-response SHA-256 and the retained evidence SHA-256.
- It emits provider hostname and first-seen observations. The provider interface does not supply the full certificate details sometimes found in CT search systems; it should not be represented as providing issuer, serial, validity, key or certificate-chain metadata.
- A provider signal for additional/capped results is surfaced as partial; HTTP 429 and `Retry-After` are surfaced without an automatic retry.
- A CT hostname is evidence that the name appeared in CT data, not proof that a host currently exists, resolves or belongs to the institution.

### Public website HTML, JavaScript, API and authentication intelligence
- `WebSurfaceFixtureCollector` analyzes saved HTML, inline script and JavaScript fixtures as text only. It never executes JavaScript and never fetches references.
- `PublicWebsiteSnapshotCollector` can, after explicit per-run approval, retrieve one approved HTTPS HTML page and a bounded number of JavaScript assets whose hosts remain within the approved domain/subdomain scope.
- Requests are anonymous GETs; no login, cookies, authorization headers, form submission, session replay or state-changing method is used. Redirects are refused, query-bearing landing URLs are rejected, and unapproved external CDN references are catalogued but not fetched.
- The analyzers catalog script assets and integrity/type hints; statically visible API paths/absolute URLs; methods where explicitly identifiable from XHR/fetch/axios source patterns; API-doc references; source-map references; OAuth/OIDC/SAML/PKCE, authorization/token/userinfo/JWKS/session markers; identity-provider SDK names; and vendor references such as Plaid and Stripe.
- The collector never calls discovered API endpoints, follows source maps or executes the JavaScript.
- Likely credential values are redacted from retained HTML/JavaScript. Original input and retained evidence digests are both recorded.

### Evidence and interpretation
- Raw evidence is stored in private, content-addressed, no-overwrite files.
- Each observation references the SHA-256 of the retained evidence and carries source/time/detection metadata.
- The website snapshot keeps the original input digest separately from the redacted evidence digest.
- A static API route/method is not proof of reachability or functionality; it is not tested.
- OAuth/OIDC/auth-provider markers are architecture hints, not proof of a functioning login or session.
- A Plaid/provider name is an integration reference, not proof of an active partner relationship or account-validation capability.
- Correlation and confidence assessment remain later pipeline stages. Collector outputs are observations, never silently promoted to relationships.

## Tests and fixtures

Added synthetic fixtures under `tests/fixtures/sources/` and tests in `tests/test_sources.py` covering:
- Registry ordering, stable IDs, duplicate source rejection and source definitions.
- CT fixture scope filtering, provenance hashes, malformed fixture retention and idempotent raw preservation.
- Static API route/method extraction, script/source-map/API-doc references, authentication markers and provider references.
- Likely credential-value redaction before retaining website text.
- Explicit live-collection approval gates.
- Mocked crt.live request behavior, exact one-domain query, scope filtering, evidence digests and rate-limit handling without retries.
- Mocked website snapshot behavior, same-scope asset retrieval, external CDN skip, anonymous GET headers and static analysis of fetched script text.
- Fatal raw-evidence persistence errors, structured source-failure logging and JSON result serialization.

All fixtures and mocked responses are synthetic. CI made no network requests.

## Provider and collection review

The crt.live public API documentation describes a hostname/first-seen response, a maximum 10,000-name page, and a 120 requests/minute per-address limit; it also cautions that CT names do not prove a host exists or resolves. FII uses a single request per manual invocation, a smaller default page size, no automatic pagination or retry, and records incomplete/capped results. Reference: [crt.live API documentation](https://crt.live/about).

The live adapters are disabled unless the caller explicitly sets `live_collection_approved=True`. This is a deliberate operator gate, not a blanket claim that public material cannot be collected. Before an actual source run, the operator must review the source's current terms, licensing, robots policy, rate limits and scope.

No live CT query, public page retrieval or financial-institution request was made during this block.

## Verification

GitHub Actions [run #31](https://github.com/xdial9/Financial-Infrastructure-Intelligence-FII-/actions/runs/43121459495) completed successfully on code head `8607e615061278d3c1b3ac31922ff9af85393bf6`:
- Python 3.11: 67 passed; Ruff all checks passed.
- Python 3.12: 67 passed; Ruff all checks passed.
- Python 3.13: 67 passed; Ruff all checks passed.

No local test result is claimed; GitHub Actions is the verification source. Documentation-only changes made after the verified code head are checked by the PR's subsequent CI run.

## Deliberately deferred

- User-facing `fii run`, `fii resume` and `fii collect` orchestration.
- Persistence of collector results into the Block 05 source-execution/observation schema; the current collectors return typed results and preserve raw evidence, but the pipeline runner is not yet connected.
- RDAP, official corporate/regulatory data, vendor-documentation enrichment, passive DNS, Censys, Subfinder, Amass, SpiderFoot, Scrapy and other optional integrations.
- Dynamic JavaScript execution, browser automation, login/authentication, cookie/session capture, endpoint invocation/testing, account actions and payment/customer-data collection.
- Normalization, deduplication/correlation, entity resolution, analyst review and report generation.

## Next block

**Block 07 — RDAP and official-source enrichment.**
