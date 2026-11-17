# Block 04 — Run controller implementation notes

**Branch:** `build/block-04-run-controller`  
**Base:** `main` at `7ea290b031a9ca41c5549abdd44c6af31a7af69f`  
**PR:** [#1 — Build Block 04](https://github.com/xdial9/Financial-Infrastructure-Intelligence-FII-/pull/1)  
**Latest tested head:** `8afc42e9fe1a15935d4c50fb4deb87dca955c493`  
**Status:** Core run-control primitives passed GitHub Actions CI; this is not the full run orchestration block.

## Added primitives

- `src/fii/core/run_controller.py` creates a UUID run directory, an immutable run manifest, a private effective-configuration snapshot, and an initial run-state file.
- Common credential-bearing config keys (API keys, secrets, tokens, passwords, credentials, private keys and authorization values) are redacted before the snapshot and digest are written. The non-secret `authorization_reference` is retained.
- Manifest and state files are JSON, use restrictive permissions on POSIX systems, and are written through a same-directory temporary file followed by flush, fsync and atomic replace.
- Stage fingerprints include the stage ID, implementation version, effective-config digest, scope digest, input-manifest digest, prerequisite-output digests and optional collector version.
- A prior stage is skipped only if its status is successful and its fingerprint matches. Changed inputs create a new attempt.
- A running stage found on recovery is marked `interrupted`; it is never inferred to have succeeded.
- `WorkspaceLock` provides exclusive, token-owned engagement locking. A second writer is rejected. Stale locks are not silently removed or stolen.

## Verification

GitHub Actions [run #8](https://github.com/xdial9/Financial-Infrastructure-Intelligence-FII-/actions/runs/42917841718) is associated with PR head `8afc42e9fe1a15935d4c50fb4deb87dca955c493`. All three Python matrix jobs (3.11, 3.12 and 3.13) completed successfully. Each job ran `python -m pytest -q` with 38 passing tests and `ruff check .` with “All checks passed!”. The pull-request workflow checked merge ref `be8b279cfe512caea11236a0966bbb30a29cb27f`, which contains the tested PR head.

## Remaining Block 04 scope

These are persistence and recovery primitives, not a complete run command. User-facing CLI orchestration, end-to-end interruption/resume through a pipeline, timeout handling and reconciliation of incomplete artifacts/stale locks remain deferred. No source collection, live network activity, active validation, SQLite evidence storage, normalization, correlation or report generation is implemented here.
