# Financial Infrastructure Intelligence (FII)

Evidence-led intelligence for financial-sector external digital assets, technology relationships, and authorized dependency analysis.

FII is designed as a straightforward, sequential Python workflow: validate an engagement, collect permitted sources, normalize and correlate evidence, analyze relationships, and produce clear reports.

## Project status

**Blocks 01–03 are implemented on main.** Block 04 run-control primitives are CI-verified on draft PR #1; full CLI orchestration and reconciliation remain future work. Block 05's SQLite evidence store passed GitHub Actions run #10 on draft PR #2 (48 tests and Ruff clean on Python 3.11, 3.12 and 3.13). Block 06's fixture and manual public-source collectors passed run #31 on draft PR #3: 67 tests and Ruff clean on Python 3.11, 3.12 and 3.13. Block 06 includes CT hostname collection from crt.live and approved one-page HTML/JavaScript snapshots; no live query was executed during development or CI. A complete source-to-report pipeline is not available yet.

## Core documentation

- [Project charter](docs/PROJECT_CHARTER.md)
- [End-to-end project plan](docs/PROJECT_PLAN.md)
- [Sequential work blocks](docs/BUILD_BLOCKS.md)
- [Target architecture](docs/architecture/TARGET_ARCHITECTURE.md)
- [Data model](docs/architecture/DATA_MODEL.md)
- [Pipeline and recovery contracts](docs/architecture/PIPELINE_CONTRACTS.md)
- [Source register](docs/SOURCE_REGISTER.md)
- [Report specification](docs/REPORT_SPECIFICATION.md)
- [Operations and CLI specification](docs/OPERATIONS.md)
- [Reference implementation review](docs/REFERENCE_IMPLEMENTATION_REVIEW.md)
- [Block 05 implementation notes](docs/IMPLEMENTATION_NOTES_BLOCK05.md)
- [Block 06 implementation notes](docs/IMPLEMENTATION_NOTES_BLOCK06.md)

## Core design

- Linear, sequential workflow.
- Evidence collection from public-source records, provider datasets and documented APIs.
- Static analysis of saved browser-delivered HTML/JavaScript for API, authentication-architecture and integration references.
- Optional provider-API and external-tool adapter seams without dynamic plugin loading.
- Explicit engagement scope and source restrictions.
- Evidence provenance and verification states.
- Explainable entity and relationship correlation.
- JSON, JSONL, CSV, and Markdown outputs.
- Logs, immutable run manifests, checkpoints, and resumable runs.
- SQLite as the initial canonical evidence store.

FII does not treat public reachability as authorization for active testing, and does not attempt to collect credentials, session tokens, customer account data, or payment data.

## Development installation

Use a project virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Then run the local checks:

```bash
fii --help
fii --version
fii doctor
pytest -q
ruff check .
```

The initial `doctor` command is read-only. It checks the Python and SQLite runtime and reports whether the future configuration and workspace locations exist; it does not create them.

The same CLI can be invoked with `python -m fii` or `python automate.py`.

## Current implementation boundary

Implemented on `main`:
- Installable `src/fii` package and Click command entry point.
- `fii doctor` read-only environment check.
- YAML engagement configuration, normalized DNS scope and validation.
- Safe per-engagement workspace initialization that preserves existing files.
- `python -m fii` and `automate.py` entry points.
- Offline CLI, configuration, scope and workspace tests.

Implemented on `build/block-04-run-controller` and CI-verified in draft PR #1:
- UUID run directories, immutable manifests and redacted effective-config snapshots.
- Atomic state writes, stage fingerprints, attempt history and interrupted-stage recovery.
- Exclusive engagement workspace lock.

CI-verified on `build/block-05-sqlite-evidence-store` / draft PR #2:
- Numbered SQLite migrations for engagements, runs, stage attempts, source definitions/executions, observations, provenance links, entities, relationships and findings.
- Standard-library connection, transaction, integrity-check and no-overwrite backup helpers.
- Foreign-key enforcement on every application-created connection and persistence errors that fail closed.
- 48 synthetic offline tests passed on Python 3.11, 3.12 and 3.13; Ruff passed in all jobs ([run #10](https://github.com/xdial9/Financial-Infrastructure-Intelligence-FII-/actions/runs/43119148982)).

In review on `build/block-06-collector-contract-passive-sources` / draft PR #3:
- Stable collector contracts and explicit source registry.
- Fixture-backed CT observations restricted to approved domains.
- Static HTML/JavaScript analysis for API paths/method hints, JS asset/source-map references, API docs, authentication architecture markers and provider references.
- Private content-addressed raw evidence with likely credential values redacted, and structured source failure reporting.

Not implemented yet:
- A user-facing `fii run` / `fii resume` orchestration command.
- Live website fetching or live provider queries; these require a source-specific terms/limits review and explicit manual invocation.
- Provider API and external-tool adapters, normalization, deduplication/correlation pipelines and report generation.

Work is delivered in bounded blocks. Each block ends with a factual completion report and verified repository changes.
