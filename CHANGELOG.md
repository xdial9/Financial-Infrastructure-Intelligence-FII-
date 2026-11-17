# Changelog

## 0.2.0 — 2026-11-17

### Added
- Sequential end-to-end collection orchestration from fixed source registry into SQLite.
- Per-source execution attempts, resumable stage checkpoints and strict configuration/scope digest checks on resume.
- Registered identifier entity resolution and evidence-backed relationship correlation.
- Informational, observation-linked research findings.
- Executive/technical report generation, asset/entity/relationship/observation/source/review/change/finding exports and a SHA-256 manifest.
- Evidence-integrity checks before report publication.
- CLI commands for source listing, run/resume/status/report, relationship review and SQLite backup.
- Local synthetic demo engagement with RDAP, CT and static website fixtures.
- End-to-end, report-integrity, resume-scope and CLI tests.

### Safety and correctness
- Live collection disabled by default and guarded by global approval, per-source approval and an authorization reference.
- Fixture-only source adapters fail closed when fixtures are missing.
- An enabled collector returning skipped now produces a partial run.
- Unexpected process exceptions mark a run interrupted and eligible for recovery.
- A changed configuration or scope cannot reuse old stage checkpoints.
- Report generation halts when cited raw evidence is missing, outside the run directory, symlinked or modified.

### Not included
- Production live collection, active validation, exploitation, login or customer data processing.
- Optional integrations with passive-DNS vendors, broad scanners or third-party crawling frameworks.
- Web dashboard, graph database, distributed execution or hosted multi-tenant service.

### Validation
GitHub Actions is the release gate for Python 3.11, 3.12 and 3.13 plus Ruff. The release tag should be created only from the merged, fully green integration commit.
### Final main-branch verification
- GitHub Actions run #83: 113 tests passed on Python 3.11, 3.12 and 3.13.
- Ruff passed on all three Python jobs.
- Full CLI smoke path exercised in CI: run, status, report regeneration and verified backup.
