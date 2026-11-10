# Financial Infrastructure Intelligence (FII)

Evidence-led intelligence for financial-sector external digital assets, documented technology relationships, and authorized dependency analysis.

FII is a straightforward sequential Python tool: validate an engagement profile, collect permitted evidence, normalize and deduplicate records, correlate entities and relationships, analyze the evidence, and produce clear reports.

## Current build status

**Phase 01:** runnable synthetic end-to-end pipeline. The first slice is offline by design; it makes no network requests and uses only fictional test data. Live passive source adapters are not yet enabled.

## Quick start

Python 3.11 or newer is required. Runtime code uses only the standard library.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
python automate.py --config examples/synthetic_engagement.json
```

FII prints the engagement name, organization, approved domains, and source list, then asks for confirmation. The included profile and evidence records are synthetic. Use `--yes` only when deliberately skipping the confirmation prompt.

## Sequential workflow

1. Load and validate the engagement profile.
2. Confirm the configured scope.
3. Create a unique run directory.
4. Collect fixture evidence (no network requests in Phase 01).
5. Normalize observations.
6. Deduplicate while preserving every supporting source and timestamp.
7. Build canonical entities and evidence-backed relationships.
8. Create qualified analyst leads.
9. Generate CSV, JSON, and Markdown reports.
10. Save resumable run state and a summary.

## Output layout

Each run is written to `results/<engagement>/runs/<run-id>/` and contains `raw/`, `normalized/`, `analysis/`, `reports/`, `logs/`, `state/`, and `run-summary.json`. Existing runs are not overwritten. Use the run ID with `--resume` to continue a previous run.

## Scope and safety

The current build implements only `synthetic_fixture`. It performs no active scanning, authentication, or live system interaction. Public reachability is not authorization. Future source adapters must be explicitly enabled, scoped, rate-limited, and documented. Findings describe evidence and research leads; they do not claim vulnerability or internal workflow discovery from public data alone.

See [Project Charter](docs/PROJECT_CHARTER.md), [End-to-End Project Plan](docs/PROJECT_PLAN.md), and [Phase 01 Implementation Notes](docs/IMPLEMENTATION_NOTES.md).
