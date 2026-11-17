# FII Operations and CLI

**Status:** Implemented in the integration branch, with offline end-to-end coverage.

## 1. Recommended operator sequence

    fii doctor
    fii validate-config --config engagement.yaml
    fii sources list --config engagement.yaml
    fii init --config engagement.yaml
    fii run --config engagement.yaml
    fii status --config engagement.yaml

The run command validates config and source scope, creates a UUID run, executes explicitly enabled sources sequentially, persists observations and provenance, resolves entities, correlates relationships, generates informational findings, finalizes run state and publishes reports.

## 2. Commands

| Command | Behavior |
|---|---|
| fii --version | Display package version |
| fii doctor | Read-only Python, SQLite, config and workspace checks |
| fii validate-config --config FILE | Validate config and normalized domain scope |
| fii init --config FILE | Prepare workspace without replacing files |
| fii sources list [--config FILE] | Display fixed source catalogue and enablement |
| fii run --config FILE | Execute enabled sources and publish reports |
| fii resume --config FILE --run-id UUID | Resume unfinished stages of an interrupted run |
| fii status --config FILE [--run-id UUID] [--limit N] | Read run state from SQLite |
| fii report --config FILE --run-id UUID | Regenerate reports and validate raw evidence |
| fii review-queue --config FILE [--limit N] | Read unresolved relationship proposals |
| fii review --config FILE ... | Append analyst disposition to review history |
| fii backup --config FILE --destination PATH | Integrity-checked, no-overwrite database backup |

Analyst review requires relationship UUID, disposition, reviewer label and rationale. The accepted disposition does not increase confidence or mark the relationship independently corroborated. Rejection records a rejected state. Every decision is appended to immutable review history.

## 3. Synthetic engagement

The executable example is examples/synthetic-demo/config.yaml. Fixture paths are resolved relative to that YAML file. It uses synthetic .invalid names and local files only.

The configuration enables RDAP, Certificate Transparency and static website analysis in fixture mode. All network collection flags remain false.

## 4. Live-source authorization gate

Each network-capable adapter requires all three conditions:
1. collection.live_collection_approved: true.
2. sources.<source_id>.live_approved: true.
3. A non-empty engagement.authorization_reference.

The adapter must also belong to the engagement's permitted source classes. Fixture-only collectors reject configurations without a fixture. Preflight checks happen before workspace or database creation.

These flags are an operator assertion; FII does not independently establish legal permission. Before enabling a public source, review source terms, licensing, robots policy, rate limits and applicable privacy requirements. No authentication cookies or customer credentials are used. JavaScript is not executed and discovered routes are not invoked.

## 5. Run, resume and status

Each run receives a UUID, immutable redacted config snapshot and config/scope digests. Each source invocation and analysis stage has a fingerprinted attempt record. A completed stage is skipped on resume only if its fingerprint matches. Failed or interrupted stages are never inferred to have succeeded.

Unexpected process exceptions mark the run interrupted so it remains eligible for resume. Explicit collector outcomes of partial or failed are recorded as source execution results; after all sources have been considered the overall run is finalized partial or failed as appropriate. Completed, partial and failed runs are terminal; run again after correcting inputs to preserve the audit trail.

Resume with the same engagement config because the config digest participates in stage fingerprints. Never manually edit a run state file to mark unfinished work successful.

## 6. Workspace and evidence reports

    <workspace>/engagements/<slug>/
      database/fii.sqlite3
      .workspace.lock
      runs/<run-uuid>/
        config/effective-config.json
        evidence/
        source-results/
        state/run.json
        manifest.json
        reports/

SQLite is canonical. Each observation retains source URL, relative evidence path and SHA-256. The report builder refuses to publish if evidence is missing, escapes the run directory, is a symlink or has a mismatched digest. Report artifact digests and limitations are recorded in report-manifest.json. CSV exports neutralize spreadsheet formula prefixes.

Historical change exports compare canonical observation keys to the immediately previous completed/partial run. A not_observed record is not evidence that an asset was removed.

## 7. Permissions, privacy and source handling

- Keep workspace data outside the Git checkout.
- Use private accounts and encrypted storage appropriate to the engagement.
- Never commit customer datasets, raw evidence, databases, local configs or secrets.
- Do not collect credentials, session tokens, customer account records, payment details or unnecessary personal data.
- Keep customer-provided internal data separate from public-source observations; define retention/deletion policies before ingestion.
- Collection is sequential; no distributed queue or concurrent source run is required.
- No exploitation, unscoped active scan, authentication, account action or transaction testing is performed.

## 8. Operational recovery

If a process exits unexpectedly:
1. Run fii status and record the run UUID.
2. Inspect the run state and source result manifests.
3. Run fii resume with the same config and UUID.
4. Re-run fii report if report publication was interrupted after collection.

If SQLite reports a persistence or integrity error, preserve the database and run directory, create a verified backup when possible, and investigate before retrying.

## 9. Backup and restore

The backup command uses SQLite's backup API, checks database integrity and publishes without overwriting an existing file. Its destination parent directory must already exist. Manage backups under the engagement retention policy; the database contains all evidence metadata.

## 10. Synthetic smoke test

    python -m pip install -e ".[dev]"
    fii validate-config --config examples/synthetic-demo/config.yaml
    fii run --config examples/synthetic-demo/config.yaml
    fii status --config examples/synthetic-demo/config.yaml

CI uses temporary workspaces and synthetic local fixtures; no live external requests are part of the test run.
