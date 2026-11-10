# Financial Infrastructure Intelligence (FII)

Evidence-led intelligence for financial-sector external digital assets, documented technology relationships, and authorized dependency analysis.

FII is designed as a straightforward, sequential Python workflow: validate an engagement, collect permitted sources, normalize and correlate evidence, analyze relationships, and produce clear reports.

## Project status

**Blueprint complete. Package/CLI foundation and Block 03 configuration/scope/workspace setup implemented.** The next block adds run control, immutable run state, locking, checkpoints and recovery. Source collection has not started.

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
- [Block 03 implementation notes](docs/IMPLEMENTATION_NOTES_BLOCK03.md)

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

The `doctor` command is read-only. It checks the Python and SQLite runtime and reports whether the future configuration and workspace locations exist; it does not create them.

## Configuration and workspace

Validate the synthetic engagement profile without creating files or making network requests:

```bash
fii validate --config examples/synthetic_engagement.yaml
fii scope show --config examples/synthetic_engagement.yaml
```

Initialize a private engagement workspace only after the profile passes validation:

```bash
fii init --config examples/synthetic_engagement.yaml
```

Use `--workspace /path/to/workspace` to override the default `~/FII-Workspace`. The initializer preserves an existing engagement profile and all existing files; it does not create a database or start collection.

## Current implementation boundary

Implemented:
- Installable package and Click command entry point.
- `fii doctor` read-only environment check.
- `fii validate` YAML profile validation.
- `fii scope show` normalized, allowlisted seed-domain display.
- `fii init` private workspace directory setup and first profile copy.
- Domain normalization, IDNA handling, and label-boundary scope matching.
- Offline tests for CLI, configuration, scope and workspace safety.

Not implemented yet:
- Run controller, immutable manifests, locks and recovery.
- SQLite evidence schema and migrations.
- CT, RDAP or other source collectors.
- Normalization, relationship correlation and report generation.

Work is delivered in bounded blocks. Each block ends with a factual completion report and verified repository changes.
