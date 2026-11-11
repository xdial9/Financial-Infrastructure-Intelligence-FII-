# Block 06 — Collector contract and first passive data sources

**Branch:** `build/block-06-collector-contract-passive-sources`  
**Base branch:** `build/block-05-sqlite-evidence-store`  
**Base commit:** `f2d1b6ed1f40c91f978b9cb1121967100295b206`  
**Status:** Implementation submitted as stacked draft [PR #3](https://github.com/xdial9/Financial-Infrastructure-Intelligence-FII-/pull/3); final CI verification is pending for current head.

**Current implementation head before this note update:** `311d11c7519b55434a188770598b012d698f92a2`.

## Scope implemented

### Collector contracts and registry
- Typed `SourceDefinition`, `CollectionContext`, `Observation`, `RawEvidenceReference`, `SourceDiagnostic` and `CollectionResult` records.
- Stable source IDs, adapter versions, source classes, integration kinds and supported observation types.
- A deterministic, fixed built-in registry. Provider APIs and external tools have explicit integration-kind seams, but no arbitrary runtime plugin loading or third-party tool invocation is added.
- `run_collector` converts expected source/input failures into failed results and emits sanitized structured source-execution logs.
- Raw evidence write failures raise `EvidenceWriteError` and propagate as fatal pipeline failures.

### Certificate Transparency fixture adapter
- Reads a saved JSON array or an object containing a `records` array.
- Understands common CT fields such as `id`, `name_value`, `common_name`, `issuer_name`, `not_before` and `not_after`.
- Normalizes DNS names and emits only exact or subdomain matches of explicitly approved seed domains.
- Preserves the original fixture bytes and links every hostname observation to the retained evidence hash.
- Does not contact a CT provider or an institution.

### Website JavaScript/API/auth surface fixture adapter
- Analyzes saved HTML, inline scripts and JavaScript files as text; it never executes JavaScript.
- Catalogs referenced script assets and their available integrity/type attributes. Asset URLs are observations only; the fixture adapter does not fetch them.
- Extracts statically identifiable API paths and absolute URLs, HTTP methods where explicit (XHR, fetch options and common axios methods), API documentation references and source-map references.
- Records authentication architecture hints including OAuth/OIDC, SAML, PKCE, authorization/token/userinfo/JWKS/session route markers and named identity-provider SDK hints.
- Records vendor strings such as Plaid and Stripe as `integration_reference` observations. These records explicitly state that the relationship is not established.
- Sanitizes likely credential values from retained HTML/JavaScript text before writing it. Both the original input digest and the hash of the retained redacted evidence are recorded.
- External asset hosts can be identified as references, but are not fetched by this adapter.

## Evidence and interpretation rules

- API routes are observed static references, not proof that a route is live, public, documented or functional.
- Authentication markers are architecture hints, not proof of a working login, session or identity assertion.
- A provider name is a vendor reference, not proof of an active integration or a successful account-validation capability.
- The collector does not test credentials, submit forms, replay sessions, mutate platform state or attempt to access restricted APIs.
- Relationship correlation and confidence assessment remain later pipeline stages; source observations are not silently upgraded into relationships.

## Tests and fixtures

Added synthetic fixtures under `tests/fixtures/sources/` and offline tests in `tests/test_sources.py` for:
- Fixed registry ordering and duplicate source rejection.
- CT scope filtering, provenance hashes, malformed-fixture failure and idempotent raw preservation.
- API route/method extraction, script/source-map references, API documentation hints, auth markers and provider references.
- Credential-value redaction in retained web text.
- Structured source failure logging and fatal evidence-persistence failures.
- JSON serialization of collection results.

All fixture domains, issuers, IDs and provider page content are synthetic. Tests make no network requests.

## Deliberately deferred

- Live CT-provider queries and live public-page retrieval. The fixture adapters establish parser, contract and evidence behavior first. A live provider must be selected only after its current terms, data licensing, robots policy, rate limits, response-size limits and provenance are reviewed; any first live query must be a separate manual operation.
- Fetching external CDN assets or source maps. References are catalogued; fetching requires the host to be separately approved.
- RDAP, official corporate/regulatory data, vendor documentation crawlers, passive DNS, Censys, Subfinder, Amass, SpiderFoot, Scrapy and other third-party integrations.
- Dynamic JavaScript execution, browser automation, login/authentication, token or cookie capture, endpoint validation and account/payment actions.
- Database insertion of source executions and observations, full run orchestration, normalization, entity resolution, correlation and reporting.

## Verification

- GitHub Actions run [#14](https://github.com/xdial9/Financial-Infrastructure-Intelligence-FII-/actions/runs/43120447008) tested code head `a5f9bc21862ad919c2e72ae03e1f34cb25fc44c3`. All three Python matrix jobs reported **61 tests passed**.
- Ruff reported one `B904` finding in the concurrent evidence-write error path. It was corrected by commit `311d11c7519b55434a188770598b012d698f92a2` with explicit exception chaining.
- Run #14 did not test commit `311d11c`; a successful run against the latest PR head is still required.
- No local test result is claimed; GitHub Actions is the verification source. No local repository checkout or user system was used for this work.
