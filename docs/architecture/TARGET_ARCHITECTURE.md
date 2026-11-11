# FII Target Architecture

**Status:** Blueprint baseline; implementation not started.  
**Reference style:** University Audit `automate.py` and APK Workbench architecture.  
**Primary execution model:** Sequential, resumable Python workflow.

## 1. Architectural objective

FII collects permitted public-source observations and explicitly authorized customer-provided inventory data, then turns those observations into traceable entities, relationships, analysis and reports.

The product's differentiator is not raw asset count. It is the quality of the evidence model and the defensibility of relationships: every material assertion should be traceable to its source, timestamp, collection method and verification state.

## 2. System shape

```text
Operator
  |
  v
Click CLI / automate.py
  |
  v
Sequential Run Controller
  |
  +--> Engagement Config + Scope Validator
  |
  +--> Preflight / Source Registry
  |
  +--> Collector 1 --> Raw Evidence
  +--> Collector 2 --> Raw Evidence
  +--> Collector 3 --> Raw Evidence
  |       (one source at a time)
  |
  +--> Normalization
  +--> Deduplication
  +--> Entity Resolution
  +--> Relationship Correlation
  +--> Analysis / Analyst Review
  +--> Report Generation
  |
  +--> SQLite Evidence Store
  +--> CSV / JSON / JSONL / Markdown Reports
  +--> Run Manifest / Logs / Checkpoints
```

The runner owns ordering, checkpointing, error policy and final status. A collector does not call another collector or begin a later pipeline stage.

## 3. Design decisions

### D-001 — Sequential first

The MVP runs source collectors one at a time, in configured order. No asyncio, worker queues, multiprocessing or parallel source fan-out. This makes runs understandable, repeatable and easier to recover.

### D-002 — One orchestration spine, modular functions

Keep one readable orchestration path in `fii/core/runner.py`, called by the CLI. Modules remain small and single-purpose. `automate.py` may be a thin compatibility/shortcut entry point; business logic must not be duplicated there.

### D-003 — Click CLI, YAML configuration

Follow APK Workbench's established Click and PyYAML conventions. Defaults live in code; operator configuration only overrides what needs to change. Configuration is validated before network collection starts.

### D-004 — SQLite is the first canonical store

Use SQLite for runs, attempts, observations, entities, relationships and findings. Keep original source payloads as files in run-specific raw storage, referenced by relative path and SHA-256. CSV and JSON are exports, not the authoritative database.

### D-005 — Fixed built-in collector registry

Use an explicit registry of built-in collectors with stable IDs and versions. Do not load arbitrary Python plugins dynamically in the MVP. External tools are invoked through narrowly defined adapters.

### D-006 — Evidence before conclusions

Collectors emit observations; normalization makes records consistent; correlation proposes relationships; analysis creates candidate findings. A conclusion must never be written as though it were a direct source observation.

### D-007 — Preserve history

Runs, stage attempts, source executions and observations are append-only. Current status may be projected for convenience, but retries must not overwrite prior attempts or raw evidence.

### D-008 — No mandatory graph database or web UI

SQLite plus relational relationship tables is sufficient for the first release. A graph visualization can be produced from exports later. Add Neo4j or a web application only after measured analyst needs justify the complexity.

## 4. Proposed package layout

```
FII/
  automate.py
  pyproject.toml
  requirements.txt
  config.example.yaml
  README.md
  src/
    fii/
      __init__.py
      cli/
        __init__.py
        main.py
      core/
        __init__.py
        config.py
        scope.py
        runner.py
        state.py
        logging.py
        dependencies.py
      sources/
        __init__.py
        contracts.py
        registry.py
        ct_logs.py
        rdap.py
        passive_dns.py
        censys.py
        corporate_web.py
        regulatory_data.py
        vendor_docs.py
        external_tool.py
      normalization/
        __init__.py
        normalize.py
        deduplicate.py
      intelligence/
        __init__.py
        entities.py
        correlate.py
        analyze.py
      database/
        __init__.py
        evidence.py
        migrations.py
      reporting/
        __init__.py
        generator.py
  tests/
    fixtures/
    test_config.py
    test_scope.py
    test_runner.py
    test_sources.py
    test_normalization.py
    test_entities.py
    test_correlate.py
    test_database.py
    test_reporting.py
  docs/
    PROJECT_CHARTER.md
    PROJECT_PLAN.md
    SOURCE_REGISTER.md
    REPORT_SPECIFICATION.md
    OPERATIONS.md
    BUILD_BLOCKS.md
    architecture/
      TARGET_ARCHITECTURE.md
      DATA_MODEL.md
      PIPELINE_CONTRACTS.md
```

Create modules only when their implementation block begins. The layout is a target map, not a requirement to generate empty files.

## 5. Technology choices

| Area | Initial choice | Reason |
|---|---|---|
| Runtime | Python 3.11+ | Available modern Python baseline; verify exact workstation version before pinning |
| CLI | Click | Already used in APK Workbench |
| Config | PyYAML | Human-readable engagement files |
| HTTP | `urllib.request` initially; adapter-specific client only if needed | Small dependency footprint and familiar style |
| Persistent store | SQLite | Standard library, local and portable |
| Raw records | JSON / JSONL | Inspectable and easy to preserve |
| Exports | CSV, JSON, Markdown | Useful to analysts and other tools |
| Web extraction | Scrapy, optional and targeted | Use only where a stable API/dataset is unavailable |
| Tests | pytest | Match existing project conventions |
| Lint/type checks | Ruff and BasedPyright | Match workstation tooling |
| Graphs | CSV/DOT first; NetworkX later if justified | Avoid premature graph infrastructure |

## 6. Collector contract

Each built-in collector exposes a stable definition and a single collection operation.

Conceptual interface:

```python
definition() -> SourceDefinition
collect(context: CollectionContext) -> CollectionResult
```

A source definition includes:
- Stable source ID and version.
- Human-readable name and source class.
- Whether credentials are required.
- Whether the source is passive/public or uses an authorized customer dataset.
- Terms/documentation reference.
- Config schema and required settings.
- Supported entity/observation types.
- Rate and timeout defaults.

A collection result includes:
- Terminal status.
- Raw record count.
- Raw evidence references.
- Normalized observation count, if normalization is collector-local.
- Start/end timestamps.
- Diagnostics and structured error details.

The runner, not the collector, persists global run state and decides whether later stages may proceed.

## 7. Failure isolation

A single optional source failure must not erase successful results from other sources. A failed source is recorded and the run becomes partial unless a required source or core persistence operation fails.

Core database corruption, inability to checkpoint, scope validation failure, or invalid configuration is a fatal run error.

## 8. Collection boundary and evidence semantics

FII gathers intelligence from public-source records, documented provider APIs, approved public website pages and explicitly supplied datasets. Read-only retrieval of public material and static analysis of saved HTML/JavaScript are collection methods, not attacks. Public-page retrieval must still respect the source's terms, robots policy, rate limits and the engagement's approved domain/source scope.

The collector pipeline does not log in, submit forms, change account or platform state, replay sessions, exploit vulnerabilities or perform service/vulnerability testing. It does not collect credentials, session tokens, payment data or customer records. Likely credential values accidentally present in public web text are redacted before retained evidence is written.

API routes, auth architecture markers and vendor names are observations with provenance—not proof of endpoint functionality, login success, account validation or an active commercial relationship. Relationship correlation must preserve observed, documented, inferred and corroborated states separately.

Provider APIs and external tools are optional adapters behind the fixed collector contract. Their terms, data licensing, rate limits, credential requirements, coverage and overlap must be reviewed before implementation or invocation.
