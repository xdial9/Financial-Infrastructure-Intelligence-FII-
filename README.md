# Financial Infrastructure Intelligence (FII)

Evidence-led intelligence for financial-sector external digital assets, technology relationships, and authorized dependency analysis.

FII is designed as a straightforward, sequential Python workflow: validate an engagement, collect permitted sources, normalize and correlate evidence, analyze relationships, and produce clear reports.

## Project status

Blueprint baseline is documented; application implementation has not started.

### Core documentation

- [Project charter](docs/PROJECT_CHARTER.md)
- [End-to-end project plan](docs/PROJECT_PLAN.md)
- [Sequential work blocks](docs/BUILD_BLOCKS.md)
- [Target architecture](docs/architecture/TARGET_ARCHITECTURE.md)
- [Data model](docs/architecture/DATA_MODEL.md)
- [Pipeline and recovery contracts](docs/architecture/PIPELINE_CONTRACTS.md)
- [Source register](docs/SOURCE_REGISTER.md)
- [Report specification](docs/REPORT_SPECIFICATION.md)
- [Operations and CLI specification](docs/OPERATIONS.md)

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

## Development

Implementation has not started. Work is being delivered in bounded blocks, each ending with a factual completion report and verified repository changes.
