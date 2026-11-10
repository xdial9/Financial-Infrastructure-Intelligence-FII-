# Work Block 03 — Configuration, Scope and Workspace

**Status:** Complete.  
**Branch:** `build/block-03-config-scope-workspace`  
**Approach:** Preserve the existing Click CLI and package foundation, adding small core modules rather than replacing the application structure.

## Implemented

- Strict YAML engagement profile loading with typed dataclasses.
- Required engagement metadata and a filesystem-safe slug.
- Domain normalization using IDNA and label-aware exact/subdomain matching.
- Explicit approved organizations, permitted source classes, and enabled/required source settings.
- Sequential-only configuration and rejection of active validation in this release.
- Bounded timeout, retry and retry-backoff values.
- Workspace path containment checks, including symlink escape detection.
- Private directory creation using mode 0700 and profile copy using mode 0600.
- Existing engagement profile and operator files are preserved.
- CLI commands: `fii validate`, `fii scope show`, and `fii init`.
- Synthetic profile uses the reserved `.invalid` domain and does not represent a real financial institution.

## Verified commands

```bash
python -m fii --help
python -m fii validate --config examples/synthetic_engagement.yaml
python -m fii scope show --config examples/synthetic_engagement.yaml
python -m fii init --config examples/synthetic_engagement.yaml --workspace /tmp/fii-workspace-test
python -m pytest -q
```

The validation and scope commands perform no workspace creation and no network access. Initialization validates the configuration first, then creates only the engagement directory structure and copies the input profile if the destination does not already exist.

## Test results

- 20 offline tests passed.
- Python bytecode compilation passed.
- CLI smoke commands passed.
- No source collector or live external query was run.

## Deferred

- Run IDs, manifests, append-only stage/source attempts, locking, resume and reconciliation are Work Block 04.
- SQLite schema and migrations are Work Block 05.
- The first fixture-backed CT source adapter and raw-evidence persistence are Work Block 06.
