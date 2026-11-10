# Financial Infrastructure Intelligence (FII)

Evidence-led intelligence for financial-sector external digital assets, technology relationships, and authorized dependency analysis.

FII is designed as a straightforward, sequential Python workflow: validate an engagement, collect permitted sources, normalize and correlate evidence, analyze relationships, and produce clear reports.

## Project status

**Blueprint complete. Package/CLI foundation implemented.** The next work block covers engagement configuration, scope validation and workspace setup. Collectors and the remaining pipeline stages have not yet been implemented.

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

## Core design

- Linear, sequential workflow.
- Passive/public-source collection in the MVP.
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

Implemented:
- Installable `src/fii` package.
- Click command entry point.
- `fii doctor` read-only environment check.
- `python -m fii` and `automate.py` entry points.
- Offline CLI tests.

Not implemented yet:
- Engagement configuration and scope enforcement.
- Workspace and run-state management.
- Source collectors.
- SQLite evidence schema.
- Normalization, correlation and reports.

Work is delivered in bounded blocks. Each block ends with a factual completion report and verified repository changes.
