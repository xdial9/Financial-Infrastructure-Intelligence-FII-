# Block 05 — SQLite evidence store implementation notes

**Branch:** `build/block-05-sqlite-evidence-store`  
**Base branch:** `build/block-04-run-controller`  
**Base commit:** `8afc42e9fe1a15935d4c50fb4deb87dca955c493`  
**Status:** CI-verified on draft [PR #2](https://github.com/xdial9/Financial-Infrastructure-Intelligence-FII-/pull/2).

## Scope implemented

- Numbered SQL migration `0001_initial.sql` with checksummed migration history and refusal to downgrade a database created by a newer FII version.
- Canonical engagement, run, stage-attempt, source-definition, source-execution, observation, entity, entity-identifier, relationship, relationship-evidence, finding and finding-evidence tables.
- Observation-to-source provenance links. The primary source link is created by a database trigger; additional corroborating, contradicting and context links are retained independently.
- Same-run composite foreign keys for observations, source executions and finding evidence; checks for statuses, confidence ranges, hashes, deduplication keys and relationship endpoints.
- Standard-library connection and explicit transaction helpers. Every connection enables and verifies `PRAGMA foreign_keys=ON`.
- Integrity and foreign-key checks plus a verified backup utility that publishes atomically and refuses to overwrite an existing backup.
- Persistence exceptions surface as fatal errors to the caller; transaction failures roll back.

## Deliberate boundaries

This block does not add source collectors, network calls, live lookups, normalization/correlation logic, report generation, active testing or a user-facing run/resume command. Tests use synthetic fixture rows only. The database path follows the existing workspace contract: `<engagement>/database/fii.sqlite3`; callers explicitly choose when to initialize it.

## Verification

- Verified PR head: `f2d1b6ed1f40c91f978b9cb1121967100295b206`.
- GitHub Actions run [#10](https://github.com/xdial9/Financial-Infrastructure-Intelligence-FII-/actions/runs/43119148982) completed successfully for that PR head.
- Python 3.11: 48 passed; Ruff: all checks passed.
- Python 3.12: 48 passed; Ruff: all checks passed.
- Python 3.13: 48 passed; Ruff: all checks passed.
- No local test result is claimed; GitHub CI is the verification source.

