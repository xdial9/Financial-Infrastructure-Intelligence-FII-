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

**Status:** In progress on `build/block-04-run-controller`; implementation and tests are staged for CI verification.

Implemented so far:
- UUID run directory creation with private file/directory permissions.
- Immutable run manifest and effective configuration snapshot with common credential fields redacted.
- SHA-256 configuration/scope digests and deterministic stage fingerprints.
- Atomic state-file replacement, attempt history and matching-fingerprint resume decisions.
- Explicit interrupted-stage recovery; an interrupted attempt is never treated as successful.
- Exclusive, token-owned workspace lock that does not automatically steal stale locks.

Still required before this block is complete:
- CLI/run-controller integration and end-to-end interruption/resume exercise.
- Reconciliation behavior for stale locks and incomplete run artifacts.
- Successful local and CI test verification.

Deliverables:
- Run UUID and immutable effective config snapshot.
- Stage/source attempt history.
- Workspace interprocess lock.
- Atomic state writes.
- Resume fingerprints.
- Ctrl+C and timeout behavior.
- Reconciliation command.

Exit criteria:
- A synthetic pipeline can be interrupted and resumed.
- Completed stages are skipped only when fingerprints match.
- Existing outputs are not overwritten.
- Stale running state is detected.

## Block 05 — SQLite evidence store

Deliverables:
- Numbered schema migrations.
- Engagement, run, stage, source execution, observation and entity tables.
- Relationship and finding tables.
- Database integrity and backup utilities.

Exit criteria:
- Schema creates from empty workspace.
- Migrations are idempotent/safely versioned.
- Foreign keys and key constraints are tested.
- Persistence failure halts the run.

## Block 06 — Collector contract and first passive data source

Deliverables:
- SourceDefinition and CollectionResult contracts.
- Fixed source registry.
- Fixture-backed CT source adapter.
- Raw evidence preservation.
- Source log and failure reporting.

Exit criteria:
- Fixture-based run works offline.
- One approved live query can be run manually after source terms/limits are checked.
- Raw response, timestamp, hash and source identity are preserved.

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
