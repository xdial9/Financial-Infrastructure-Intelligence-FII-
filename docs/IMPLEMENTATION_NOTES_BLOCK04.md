# Block 04 — Run controller implementation notes

**Branch:** `build/block-04-run-controller`  
**Base:** `main` at `7ea290b031a9ca41c5549abdd44c6af31a7af69f`  
**Status:** Implementation staged; CI verification pending.

## Added primitives

- `src/fii/core/run_controller.py` creates a UUID run directory, an immutable run manifest, a private effective-configuration snapshot, and an initial run-state file.
- Common credential-bearing config keys (API keys, secrets, tokens, passwords, credentials, private keys and authorization values) are redacted before the snapshot and digest are written. The non-secret `authorization_reference` is retained.
- Manifest and state files are JSON, use restrictive permissions on POSIX systems, and are written through a same-directory temporary file followed by flush, fsync and atomic replace.
- Stage fingerprints include the stage ID, implementation version, effective-config digest, scope digest, input-manifest digest, prerequisite-output digests and optional collector version.
- A prior stage is skipped only if its status is successful and its fingerprint matches. Changed inputs create a new attempt.
- A running stage found on recovery is marked `interrupted`; it is never inferred to have succeeded.
- `WorkspaceLock` provides exclusive, token-owned engagement locking. A second writer is rejected. Stale locks are not silently removed or stolen.

## Current boundary

These are persistence and recovery primitives, not a complete run command. They do not collect source data, create the SQLite evidence store, normalize observations, correlate entities, or generate reports. No external network activity is initiated by these functions.

## Verification

New tests cover private run artifacts, secret redaction, run-path validation, matching and changed fingerprints, interrupted-stage retry, terminal-state restrictions, and lock ownership behavior. Results must be taken from the branch's actual CI run before this block is marked complete.
