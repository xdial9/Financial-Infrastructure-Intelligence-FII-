# FII Pipeline Contracts

**Status:** Proposed implementation contract.  
**Execution:** Sequential; one stage at a time and one source at a time.

## 1. Run lifecycle

Run statuses:
- `pending`: created but not started.
- `running`: active pipeline.
- `completed`: all required stages and enabled sources completed successfully.
- `partial`: pipeline completed but one or more optional sources/stages were incomplete.
- `failed`: fatal failure prevented a valid report.
- `interrupted`: operator interruption or process termination was recorded.
- `cancelled`: operator explicitly cancelled before completion.

Stage and source statuses:
- `pending`
- `running`
- `success`
- `partial`
- `failed`
- `timed_out`
- `skipped`
- `cancelled`

A stale `running` entry found on restart is not considered success. It is reconciled as interrupted/unknown and retried according to its input fingerprint.

## 2. Stage order

1. load_config
2. validate_scope
3. prepare_workspace
4. preflight_sources
5. collect_sources
6. normalize_observations
7. deduplicate_observations
8. resolve_entities
9. correlate_relationships
10. analyze_intelligence
11. generate_reports
12. reconcile_run

A stage receives explicit input objects and returns a structured result. It must not use implicit global state or start later stages itself.

## 3. Continuation policy

### Fatal; stop immediately
- Invalid configuration.
- Scope validation failure.
- Database integrity or persistence failure.
- Unable to create a safe run directory.
- Required source configuration missing.
- Checkpoint write failure.
- Detected path traversal or workspace containment violation.

### Non-fatal; record and continue
- Optional source unavailable.
- API rate limit after bounded retries.
- Source returns no records.
- A source's schema changes but other collectors remain valid.
- A single public page is unavailable.
- Optional enrichment is skipped.

If a required source fails, the run may continue only when the engagement configuration explicitly marks downstream analysis as useful without it; final status must be partial and the report must disclose the gap.

## 4. Resume fingerprint

A stage may be skipped on resume only when all of the following match:
- stage ID and implementation version;
- effective configuration digest;
- scope digest;
- input manifest digest;
- prerequisite stage outputs;
- collector version for source stages.

If any fingerprint changes, that stage and dependent stages must be rerun. Existing outputs are preserved; new attempt-specific outputs are created.

## 5. Attempt and output naming

- Every run gets a UUID run_id.
- Every stage and source execution has an increasing attempt number.
- Attempt outputs are unique; never truncate an existing attempt file.
- A stage publishes its output manifest only after successful validation.
- Reports are written to a temporary file in the destination directory, flushed, fsynced where practical, then atomically replaced.
- Raw evidence is retained before normalization so downstream failures can be retried without recollecting.

## 6. Workspace locking

Use an interprocess lock for operations that mutate a single engagement's SQLite database, state or report publication. Follow APK Workbench's proven workspace lock pattern. A second run against the same engagement must fail clearly or wait according to an explicit CLI option; do not allow two writers to interleave.

## 7. Timeouts and retries

- Set connect/read/overall timeouts on each network call.
- Retry only transient failures, with a small bounded retry count.
- Honor Retry-After where provided.
- Do not retry permanent authorization, terms, or invalid-scope failures.
- Log retry count and final outcome.
- Subprocess adapters use argument arrays, never shell command strings.
- A subprocess has an explicit timeout and bounded output size.
- Process groups are terminated on timeout or cancellation.

## 8. Checkpointing and interruption

After each source and major stage:
1. Persist attempt status.
2. Persist source/stage counters.
3. Persist output-manifest references.
4. Update run progress.

On Ctrl+C:
- stop starting new source work;
- allow current operation to close or terminate it cleanly;
- record current stage/source as cancelled or interrupted;
- preserve raw output and logs;
- save a run summary;
- exit with status 130.

Do not delete partial artifacts automatically.

## 9. Output and exit codes

Suggested exit codes:
- 0: completed successfully.
- 1: fatal configuration, scope, persistence or pipeline error.
- 2: partial run (optional sources failed; valid partial report produced).
- 130: interrupted by operator.

The final run summary must include run ID, engagement, timestamps, status, source counts, observation counts, entities, relationships, findings, skipped/failed sources, report paths and limitations.

## 10. Reconciliation

`fii reconcile --run-id <id>` compares the run manifest and database:
- every configured source has an execution row;
- every source result path exists or has an explicit missing status;
- every normalized observation links to a source execution;
- every relationship has evidence references;
- every finding has evidence references or an explicit analyst rationale;
- report files match the final report manifest;
- no stage marked successful is missing its output manifest.

The reconciler reports inconsistencies; it never silently rewrites evidence or changes an error into success.
