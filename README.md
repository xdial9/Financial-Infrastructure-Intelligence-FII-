# Financial Infrastructure Intelligence (FII)

FII is a sequential, evidence-led command-line workflow for mapping financial-sector external assets and documented technology dependencies within an explicitly authorized engagement. It preserves source provenance, normalizes observations, resolves entities conservatively, correlates evidence-backed relationships, and produces reproducible reports.

FII is not a vulnerability scanner. A public certificate, nameserver, registry entry, vendor string or static API route is not proof of ownership, operational integration, current reachability or vulnerability.

## Current delivery

The integration branch brings together the Blocks 04–09 foundation and adds the source-to-report workflow:

- UUID run manifests, redacted configuration snapshots, stage checkpoints, interrupted-run recovery and an engagement writer lock.
- SQLite evidence storage, source execution history, canonical observations, provenance and retained raw evidence.
- Fixed source registry and bounded passive/fixture adapters.
- Registered-identifier entity resolution with conservative name candidates.
- Evidence-backed relationships and append-only analyst review.
- Sequential source orchestration, informational research findings and historical comparison.
- Executive and technical reports, CSV/JSONL exports and SHA-256 report manifest.
- CLI for source discovery, run/resume/status/report, analyst review and verified database backup.
- Offline synthetic end-to-end test coverage.

Integration is being validated in [PR #7](https://github.com/xdial9/Financial-Infrastructure-Intelligence-FII-/pull/7). Do not treat the project as production-ready until the PR is merged and a properly authorized pilot has been reviewed.

## Safety and collection boundaries

Sources are disabled unless explicitly enabled in engagement YAML. Live-capable adapters require global collection approval, source-specific approval and an authorization reference. Fixture-only adapters require local fixtures. The example engagement uses synthetic .invalid domains and local files only.

FII does not perform login, exploitation, active endpoint validation, customer account/payment collection, credential/session harvesting, JavaScript execution or API-route invocation. Static API and vendor references remain research leads, not proof of live integrations. Generated findings are informational, not vulnerability severity ratings.

## Quick start

Install in a virtual environment:

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -e ".[dev]"

Validate and inspect the synthetic example:

    fii doctor
    fii validate-config --config examples/synthetic-demo/config.yaml
    fii sources list --config examples/synthetic-demo/config.yaml

Run the entire offline workflow:

    fii run --config examples/synthetic-demo/config.yaml

The command prints the run UUID, source/observation/entity/relationship/finding counts and report directory. By default, the workspace is ~/FII-Workspace.

Inspect the output:

    fii status --config examples/synthetic-demo/config.yaml
    fii report --config examples/synthetic-demo/config.yaml --run-id RUN_UUID
    fii review-queue --config examples/synthetic-demo/config.yaml

Resume an interrupted run using the same configuration:

    fii resume --config examples/synthetic-demo/config.yaml --run-id RUN_UUID

Create a verified, no-overwrite database backup:

    fii backup --config examples/synthetic-demo/config.yaml --destination /existing/backup/directory/fii.sqlite3

Record an analyst disposition:

    fii review --config examples/synthetic-demo/config.yaml --relationship-id RELATIONSHIP_UUID --disposition needs_research --reviewer analyst-team --rationale "Retain as a research lead pending independent evidence."

## CLI commands

| Command | Purpose |
|---|---|
| fii doctor | Read-only runtime, config-path and workspace checks |
| fii validate-config --config FILE | Validate engagement YAML and normalized scope |
| fii init --config FILE | Prepare workspace without replacing existing files |
| fii sources list [--config FILE] | List fixed adapters and per-engagement enablement |
| fii run --config FILE | Collect enabled sources, analyze and publish reports |
| fii resume --config FILE --run-id UUID | Resume an interrupted run |
| fii status --config FILE [--run-id UUID] [--limit N] | Read recent or specific run state |
| fii report --config FILE --run-id UUID | Rebuild report exports and verify raw evidence |
| fii review-queue --config FILE [--limit N] | List relationships for analyst review |
| fii review ... | Append accepted/rejected/needs-research decision |
| fii backup --config FILE --destination PATH | Integrity-checked SQLite backup |

## Report package

Each run produces:
- executive-summary.md and technical-report.md
- asset-inventory.csv and entities.json
- relationships.csv and observations.jsonl
- source-register.csv and analyst-review.csv
- changes.csv and findings.csv
- report-manifest.json with counts, baseline and SHA-256 artifact digests

Raw evidence is checked against its database SHA-256 before publication. Missing, escaped, symlinked or altered evidence stops report generation. Historical absence is labelled not_observed, never interpreted as proof of asset removal. CSV exports neutralize spreadsheet formula prefixes.

## Workspace layout

    ~/FII-Workspace/
      engagements/<slug>/
        database/fii.sqlite3
        .workspace.lock
        runs/<run-uuid>/
          config/effective-config.json
          evidence/
          source-results/
          state/run.json
          manifest.json
          reports/

SQLite is canonical. Run directories retain the effective config, immutable manifests, source results, raw evidence, checkpoints and reports. Sensitive workspace directories/files use restrictive permissions where supported.

## Validation

    python -m pytest -q
    ruff check .

CI targets Python 3.11, 3.12 and 3.13. The end-to-end tests use local fixture files and synthetic .invalid domains; no real institution/provider requests are part of CI.

## Documentation

- [Project charter](docs/PROJECT_CHARTER.md)
- [End-to-end project plan](docs/PROJECT_PLAN.md)
- [Sequential work blocks](docs/BUILD_BLOCKS.md)
- [Operations and CLI](docs/OPERATIONS.md)
- [Delivery status](docs/DELIVERY_STATUS.md)
- [Target architecture](docs/architecture/TARGET_ARCHITECTURE.md)
- [Data model](docs/architecture/DATA_MODEL.md)
- [Pipeline and recovery contracts](docs/architecture/PIPELINE_CONTRACTS.md)
- [Source register](docs/SOURCE_REGISTER.md)
- [Report specification](docs/REPORT_SPECIFICATION.md)
