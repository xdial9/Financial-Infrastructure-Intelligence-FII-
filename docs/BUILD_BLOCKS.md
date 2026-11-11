# FII Sequential Work Blocks

**Purpose:** Deliver the project in bounded, reportable blocks.  
**Method:** Complete one block's defined deliverables and exit criteria, report what changed, then begin the next block.  
**No hidden/background work:** Each block is executed in the active work session and ends with a factual completion report.

## Block reporting format

At the end of every block, report:
- Objective and scope of the block.
- Files created or changed.
- GitHub commits and links.
- Airtable records updated.
- Tests executed and actual results.
- Decisions made and reasons.
- Deferred work and blockers.
- Exact next block.

Do not claim a task is complete unless its acceptance criteria were checked.

## Block 01 — Blueprint completion

**Status:** Completed in Work Block 01.

Deliverables:
- Target architecture.
- Canonical data model.
- Sequential pipeline contracts.
- Source register and integration order.
- Report specification.
- CLI and operations specification.
- Ordered implementation blocks.
- Airtable work-block tracking.

Exit criteria:
- A developer can understand the product boundary, execution order, storage model, source integration contracts and first implementation slice without inventing missing architecture.

## Block 02 — Package skeleton and CLI foundation

**Status:** Completed in Work Block 02.

Deliverables:
- `pyproject.toml` with runtime/development dependencies and package metadata.
- `src/fii/` package and Click CLI.
- `fii doctor`, version and help output.
- Thin `automate.py` entry point if useful.
- Ruff and pytest configuration.

Exit criteria:
- The package installed editable locally using the available build tooling.
- `fii --help`, `fii --version` and `fii doctor` were smoke-tested.
- Three offline CLI tests passed.
- `doctor` did not create missing config/workspace directories.

## Block 03 — Configuration, engagement scope and workspace

**Status:** Completed on `main`; local operator smoke test passed on 2026-11-10.

Deliverables:
- YAML defaults and validation.
- Engagement profile loading.
- Domain/identifier normalization.
- Explicit source and scope review.
- Workspace creation and path containment.
- Safe directory/file permissions.
- Example synthetic configuration.

Exit criteria:
- Valid synthetic config loads.
- Invalid/malformed scope is rejected before any source operation.
- Existing files are preserved.

## Block 04 — Run controller, manifests, locking and recovery

**Status:** Core run-control primitives CI-verified on draft PR #1; broader CLI integration and reconciliation remain deferred.

Implemented on `build/block-04-run-controller`:
- UUID run directory creation with private file/directory permissions.
- Immutable run manifest and effective configuration snapshot with common credential fields redacted.
- SHA-256 configuration/scope digests and deterministic stage fingerprints.
- Atomic state-file replacement, attempt history and matching-fingerprint resume decisions.
- Explicit interrupted-stage recovery; an interrupted attempt is never treated as successful.
- Exclusive, token-owned workspace lock that does not automatically steal stale locks.

Verification:
- GitHub Actions run #8 completed successfully for PR head `8afc42e9fe1a15935d4c50fb4deb87dca955c493`.
- Python 3.11, 3.12 and 3.13 matrix jobs passed; each job reported 38 tests passed and Ruff reported all checks passed.
- The pull-request workflow checked the merge ref containing that head commit. See [run #8](https://github.com/xdial9/Financial-Infrastructure-Intelligence-FII-/actions/runs/42917841718).

Remaining work, not claimed complete:
- User-facing CLI/run-controller integration.
- End-to-end interruption/resume exercise through a pipeline command.
- Reconciliation behavior for incomplete run artifacts and stale locks.
- Ctrl+C and timeout orchestration.

The next block proceeds after the user-directed CI gate; this does not imply the deferred integration items are implemented.

## Block 05 — SQLite evidence store

**Status:** CI-verified on draft PR #2 / `build/block-05-sqlite-evidence-store`, stacked on the verified Block 04 head.

Verification:
- Latest verified Block 05 head: `f2d1b6ed1f40c91f978b9cb1121967100295b206`.
- GitHub Actions run #10 passed for Python 3.11, 3.12 and 3.13.
- Each matrix job reported 48 passing tests and `ruff check .` reported `All checks passed!`.
- See [PR #2](https://github.com/xdial9/Financial-Infrastructure-Intelligence-FII-/pull/2) and [run #10](https://github.com/xdial9/Financial-Infrastructure-Intelligence-FII-/actions/runs/43119148982).
- No local test result is claimed; CI is the verification source.

Deliverables:
- Numbered, checksummed SQL schema migrations and schema-version tracking.
- Engagement, run, stage-attempt, source-definition/execution, observation, provenance-link, entity, relationship, relationship-evidence, finding and finding-evidence tables.
- Standard-library SQLite connection and transaction helpers with foreign keys enabled for every opened connection.
- Constraints and indexes for deduplication, source provenance, relationship evidence and finding evidence.
- Integrity checks and atomic, no-overwrite database backups.
- Fatal persistence exceptions; no persistence failure is silently treated as success.
- Offline synthetic tests for database creation, migrations, foreign keys, uniqueness, evidence constraints, rollback, backup/restore and persistence failures.

Exit criteria:
- Empty database initializes with the latest numbered schema.
- Reapplying migrations is idempotent and a newer schema is never downgraded.
- Foreign keys, uniqueness and evidence constraints reject invalid records.
- Transaction failures roll back and surface as persistence errors.
- A verified backup can be restored without overwriting an existing backup.
- Latest GitHub CI is green before this block is marked complete.

## Block 06 — Collector contract and first passive data sources

**Status:** Implementation on `build/block-06-collector-contract-passive-sources`; verification is pending in stacked draft PR #3.

Deliverables:
- Typed `SourceDefinition`, `CollectionContext`, `Observation`, `CollectionResult` and diagnostic contracts.
- Explicit fixed registry with stable source IDs and adapter metadata for built-in, provider-API and external-tool integration paths. No dynamic code loading.
- Fixture-backed Certificate Transparency adapter with explicit approved-domain filtering.
- Fixture-backed website-surface adapter for saved HTML and JavaScript. It catalogs script assets, static API routes and HTTP methods when identifiable, API-documentation references, source-map references, OAuth/OIDC/SAML/PKCE and identity-provider markers, and third-party integration references such as Plaid and Stripe.
- Content-addressed, private, no-overwrite raw evidence storage. HTML/JavaScript evidence is sanitized for likely credential values before storage; original and retained hashes are both recorded.
- Structured source diagnostics and sanitized execution logging. Raw evidence persistence failures remain fatal.
- Synthetic fixtures only; no institution or provider is contacted. JavaScript is parsed as text and never executed. Asset and source-map URLs are catalogued but not fetched by the fixture adapter.

Interpretation rules:
- An API route is an observed static reference, not proof that the route is reachable or usable.
- An auth marker is an architecture hint, not proof of a valid login/session.
- A provider name is an integration reference, not proof that the institution has an active provider relationship or that a customer account can be validated.
- Provider API and external-tool adapters can implement the same contract in later blocks; credentials, if ever required, must be handled outside evidence and logs.

Exit criteria:
- Synthetic fixture runs produce deterministic, provenance-linked observations offline.
- CT names are limited to approved seed domains.
- API methods, JavaScript assets, auth markers and provider references are recorded with the evidence file/hash and appropriate caveats.
- Likely credential values are not retained in web-surface evidence.
- Source failures are reported; evidence-write failures are fatal.
- A live provider query remains a separate manual step after provider terms, limits and an approved source have been verified; no live request is part of this block's CI.

## Block 07 — RDAP and official-source enrichment

Deliverables:
- RDAP adapter.
- One official corporate or regulatory source adapter.
- Source coverage/limitations recorded.
- Normalized observation conversion.

Exit criteria:
- Two source families can contribute evidence without losing provenance.
- Missing/redacted source fields are handled correctly.

## Block 08 — Normalization, deduplication and entity resolution

Deliverables:
- Canonical observation schema.
- Deduplication key and provenance merge rules.
- Entity types and identifier registry.
- Deterministic entity resolution.

Exit criteria:
- The same observation from two sources produces one canonical fact with two source references.
- Similar-looking entities are not merged without a rule/evidence.

## Block 09 — Relationship correlation and analyst review

Deliverables:
- Typed relationship predicates.
- Evidence links.
- Explainable rules and confidence rationale.
- Inferred/observed distinctions.
- Analyst disposition workflow.

Exit criteria:
- Every relationship has evidence links.
- Every inference is explicitly marked.
- Contradictory evidence is retained rather than overwritten.

## Block 10 — Report generation

Deliverables:
- Executive Markdown report.
- Technical Markdown report.
- Asset inventory CSV.
- Entities and relationships exports.
- Observation JSONL.
- Source register and analyst review exports.
- Report manifest.

Exit criteria:
- A synthetic dataset produces a complete report package.
- Every claim can be traced to evidence.
- Partial collection is clearly disclosed.

## Block 11 — Historical comparison and source expansion

Deliverables:
- Run-to-run observation comparison.
- Added/removed/changed records.
- Optional Censys/passive DNS/Subfinder/Amass integrations selected by measured value.
- Scrapy for selected public-source extraction only where necessary.
- SpiderFoot integration evaluation, not assumed inclusion.

Exit criteria:
- Source expansion shows distinct incremental value.
- Source gaps are not mislabeled as asset removal.
- All integrations respect their terms and configured scope.

## Block 12 — Reliability, packaging and pilot release

Deliverables:
- Full offline integration tests.
- Subprocess failure/timeout tests.
- Install and operator documentation.
- Versioned output schema.
- Synthetic demonstration report.
- Pilot checklist for explicitly authorized scopes.

Exit criteria:
- A new operator can install, configure, run, resume, reconcile and report without developer intervention.
- One complete synthetic run meets the report specification.
- No application secrets or customer data are present in the repository.

## Priority rule

If a later feature delays the first complete evidence-to-report workflow, defer that feature. The first product milestone is one small, reproducible pipeline that creates a trustworthy report, not the largest possible collector catalog.
