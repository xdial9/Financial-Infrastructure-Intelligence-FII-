

## Block 09 — Relationship correlation and analyst review

**Status:** CI-verified on draft [PR #6](https://github.com/xdial9/Financial-Infrastructure-Intelligence-FII-/pull/6) / branch `build/block-09-relationship-correlation-analyst-review`, stacked on Block 08. Final code head: `757f6e363e46778ee84e8836517547aacff1195e`. GitHub Actions [run #52](https://github.com/xdial9/Financial-Infrastructure-Intelligence-FII-/actions/runs/43138667923) passed: Python 3.11, 3.12 and 3.13 each reported **102 tests passed** and Ruff **All checks passed!** No local test result is claimed.

Deliverables:
- Versioned SQLite migration 0003 with a fixed relationship-rule registry and append-only analyst review history.
- Typed relationship rules for RDAP nameserver observations, static vendor references, static API route references and API documentation references.
- Evidence-linked relationship proposals with supporting, contradicting and context roles; deterministic IDs make repeated identical proposals idempotent without collapsing distinct evidence assertions.
- Endpoint-type, run-scope, observation-type, endpoint-anchor and source/value consistency checks.
- Corroboration requires supporting observations from at least two distinct source definitions. Contradicting evidence is retained and prevents automatic corroboration.
- Deterministic rule confidence scores and explicit rationale; scores are heuristic, not probabilities.
- Analyst dispositions accepted/rejected/needs_research with reviewer label, rationale, timestamp and prior/resulting state. Acceptance does not upgrade evidence state; rejection marks the assertion rejected; review history cannot be updated or deleted.
- Synthetic offline SQLite tests; no active requests, JavaScript execution, API invocation, or real institution/provider contact.

Exit criteria:
- Each persisted relationship has at least one supporting evidence link and may also retain contradictory/context evidence.
- Only registered predicates/rules and matching entity types/observation types can be used.
- Two executions from the same source definition do not count as independent corroboration.
- Two distinct source definitions may corroborate an observed rule only when no contradicting evidence exists.
- Contradictions remain visible and prevent corroboration.
- Analyst review is auditable and cannot silently promote confidence or erase evidence.
- CI passes on the final PR head before Block 09 is complete.

## Block 10 — Sequential pipeline integration

**Status:** Implemented and CI-verified in integration PR #7.

Deliverables:
- Fixed source registry preflight, source-class and engagement-scope enforcement.
- Per-source/per-query stage fingerprints, attempt persistence and resume checkpoints.
- Raw evidence and source result manifests persisted under the private run directory.
- Source execution history and canonical observations/provenance persisted in SQLite.
- Existing entity resolution and relationship correlation invoked after collection.
- Required/optional/skipped/partial/failed source outcomes reflected in final run status.
- Workspace lock acquired before SQLite initialization and writes.
- Resume rejects any changed effective configuration or scope digest.

## Block 11 — Findings and reproducible reports

**Status:** Implemented and CI-verified in integration PR #7.

Deliverables:
- Deterministic informational research findings backed by observation evidence.
- Executive and technical Markdown reports.
- Asset inventory, entities, relationships, observations, source register, analyst review, historical changes and finding exports.
- Report manifest with artifact SHA-256 hashes, run metadata, baseline and limitations.
- Raw evidence containment/symlink/digest verification before report publication.
- CSV formula-prefix neutralization and atomic private report writes.
- Historical observations absent from the new run are labelled `not_observed`, never as confirmed asset removal.

## Block 12 — Operator workflow and recovery

**Status:** Implemented and CI-verified in integration PR #7.

Commands:
- `fii sources list`
- `fii run`
- `fii resume`
- `fii status`
- `fii report`
- `fii review-queue`
- `fii review`
- `fii backup`

Resume requires the original configuration/scope digests. Unexpected exceptions and process interruption preserve recoverable state. Database initialization and mutation are serialized by an engagement-level lock. Backups use SQLite's backup API, integrity checks and no-overwrite publication.

## Block 13 — Synthetic reference engagement and handoff docs

**Status:** Implemented and CI-verified in integration PR #7.

Deliverables:
- Ready-to-run local RDAP, CT fixture and static website fixture set for `example.invalid`.
- Reproducible sample engagement configuration at `examples/synthetic-demo/config.yaml`.
- Operator quick start, command guide, data/workspace layout, report interpretation and troubleshooting.
- No live target, institution or third-party service is queried in CI.

## Block 14 — Hardening, packaging and v0.2.0

**Status:** Implemented and merged to `main` in PR #7. Main-branch CI run #83 passed 113 tests and Ruff on Python 3.11, 3.12 and 3.13, including full CLI workflow verification.

Deliverables:
- Package version 0.2.0 and changelog.
- Python 3.11–3.13 CI plus Ruff.
- Synthetic coverage for source preflight, end-to-end persistence, report integrity, resume digest checks and CLI workflow.
- Live/public collection remains disabled by default and requires explicit global and per-source opt-in plus authorization reference.

## Block 15 — Authorized pilot and source-specific expansion

**Status:** Deliberately not executed.

This is not a code-only milestone and cannot be truthfully completed using synthetic fixtures. It requires a real engagement scope, written authorization, source terms/licensing review, privacy and retention review, and the customer's designated operator. No live pilot, production source coverage or customer dataset ingestion is claimed.

Optional future source work should be selected by market/jurisdiction and incremental evidence value. Additional passive-DNS providers, Censys/other external tools, regulatory registers, broader public disclosure sources, internal CMDB/customer inventories, graph UI, dashboard and distributed execution remain optional and are not required to run the offline MVP.
