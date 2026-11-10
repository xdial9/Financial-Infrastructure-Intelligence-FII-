"""Run manifests, resumable stage checkpoints, and engagement workspace locking."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fii.core.workspace import WorkspacePaths

MANIFEST_VERSION = 1
STATE_VERSION = 1
STAGE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SECRET_KEY_RE = re.compile(
    r"(?:api[_-]?key|secret|token|password|credential|private[_-]?key|"
    r"authorization)",
    re.IGNORECASE,
)
TERMINAL_RUN_STATUSES = {"completed", "partial", "failed", "cancelled"}
STAGE_TERMINAL_STATUSES = {
    "success",
    "partial",
    "failed",
    "timed_out",
    "cancelled",
    "interrupted",
}


class RunError(RuntimeError):
    """Raised when run state cannot be safely created or changed."""


class WorkspaceLockError(RunError):
    """Raised when an engagement workspace is already locked."""


@dataclass(frozen=True)
class RunPaths:
    """Resolved paths for one immutable run directory."""

    run_id: str
    directory: Path
    config_snapshot: Path
    manifest: Path
    state: Path


@dataclass(frozen=True)
class StageDecision:
    """Whether a stage should execute or can be skipped on resume."""

    should_run: bool
    attempt: int
    reason: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sanitize_config(value: Any) -> Any:
    """Redact common credential fields before config snapshots or hashes."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for child_key, child_value in value.items():
            normalized_key = str(child_key).lower().replace("-", "_")
            is_secret = (
                normalized_key != "authorization_reference"
                and bool(SECRET_KEY_RE.search(normalized_key))
            )
            sanitized[str(child_key)] = (
                "<redacted>" if is_secret else _sanitize_config(child_value)
            )
        return sanitized
    if isinstance(value, list):
        return [_sanitize_config(item) for item in value]
    return value


def _write_json_atomic(path: Path, value: Any, *, overwrite: bool) -> None:
    """Atomically write a private JSON file in the destination directory."""
    if path.is_symlink():
        raise RunError(f"Refusing symlinked state file: {path}")
    if path.exists() and not overwrite:
        raise RunError(f"Refusing to overwrite existing run artifact: {path}")

    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        if path.exists() and not overwrite:
            raise RunError(f"Refusing to overwrite existing run artifact: {path}")
        os.replace(temporary, path)
        os.chmod(path, 0o600)

        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except RunError:
        raise
    except OSError as exc:
        raise RunError(f"Cannot write run state file {path}: {exc}") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise RunError(f"Refusing symlinked run artifact: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RunError(f"Required run artifact is missing: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RunError(f"Cannot read run artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RunError(f"Run artifact must contain a JSON object: {path}")
    return value


def _validate_run_id(run_id: str) -> str:
    try:
        parsed = uuid.UUID(run_id)
    except (TypeError, ValueError, AttributeError) as exc:
        raise RunError(f"Invalid run ID: {run_id!r}") from exc
    if str(parsed) != run_id.lower():
        raise RunError(f"Run ID is not in canonical UUID form: {run_id!r}")
    return str(parsed)


def _run_paths(workspace: WorkspacePaths, run_id: str) -> RunPaths:
    canonical_id = _validate_run_id(run_id)
    runs_root = workspace.runs.resolve(strict=True)
    directory = workspace.runs / canonical_id
    if directory.is_symlink():
        raise RunError(f"Refusing symlinked run directory: {directory}")
    if not directory.is_dir():
        raise RunError(f"Run directory does not exist: {directory}")
    try:
        directory.resolve(strict=True).relative_to(runs_root)
    except FileNotFoundError:
        raise
    except ValueError as exc:
        raise RunError("Run directory escapes the engagement runs directory.") from exc
    return RunPaths(
        run_id=canonical_id,
        directory=directory,
        config_snapshot=directory / "config" / "effective-config.json",
        manifest=directory / "manifest.json",
        state=directory / "state" / "run.json",
    )


def create_run(
    workspace: WorkspacePaths,
    config: dict[str, Any],
    *,
    implementation_version: str = "0.1.0",
) -> RunPaths:
    """Create a new run directory, immutable manifest, and initial state."""
    if not isinstance(config, dict):
        raise RunError("Run configuration must be a mapping.")
    engagement = config.get("engagement")
    scope = config.get("scope")
    if not isinstance(engagement, dict) or not isinstance(scope, dict):
        raise RunError("Run configuration must include validated engagement and scope mappings.")

    run_id = str(uuid.uuid4())
    directory = workspace.runs / run_id
    try:
        directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        os.chmod(directory, 0o700)
        config_dir = directory / "config"
        state_dir = directory / "state"
        config_dir.mkdir(mode=0o700)
        state_dir.mkdir(mode=0o700)
    except OSError as exc:
        raise RunError(f"Cannot create unique run directory {directory}: {exc}") from exc

    paths = RunPaths(
        run_id=run_id,
        directory=directory,
        config_snapshot=config_dir / "effective-config.json",
        manifest=directory / "manifest.json",
        state=state_dir / "run.json",
    )

    sanitized_config = _sanitize_config(config)
    config_digest = _sha256(sanitized_config)
    scope_digest = _sha256(_sanitize_config(scope))
    created_at = _utc_now()

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "run_id": run_id,
        "created_at": created_at,
        "engagement": {
            "name": engagement.get("name", ""),
            "slug": engagement.get("slug", ""),
            "organization": engagement.get("organization", ""),
        },
        "implementation_version": implementation_version,
        "config_snapshot": "config/effective-config.json",
        "config_sha256": config_digest,
        "scope_sha256": scope_digest,
        "collection_mode": "sequential",
        "active_validation": False,
    }
    state = {
        "state_version": STATE_VERSION,
        "run_id": run_id,
        "engagement_slug": engagement.get("slug", ""),
        "status": "pending",
        "created_at": created_at,
        "updated_at": created_at,
        "stages": {},
    }

    _write_json_atomic(paths.config_snapshot, sanitized_config, overwrite=False)
    _write_json_atomic(paths.manifest, manifest, overwrite=False)
    _write_json_atomic(paths.state, state, overwrite=False)
    return paths


def open_run(workspace: WorkspacePaths, run_id: str) -> RunPaths:
    """Resolve an existing run and verify that its required files are present."""
    paths = _run_paths(workspace, run_id)
    if not paths.directory.is_dir():
        raise RunError(f"Run directory does not exist: {paths.directory}")
    manifest = _read_json(paths.manifest)
    state = _read_json(paths.state)
    if manifest.get("run_id") != paths.run_id or state.get("run_id") != paths.run_id:
        raise RunError("Run ID does not match its manifest and state files.")
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise RunError("Unsupported run manifest version.")
    if state.get("state_version") != STATE_VERSION:
        raise RunError("Unsupported run state version.")
    return paths


def make_stage_fingerprint(
    stage_id: str,
    *,
    implementation_version: str,
    config_digest: str,
    scope_digest: str,
    input_manifest_digest: str = "",
    prerequisite_outputs: dict[str, str] | None = None,
    collector_version: str = "",
) -> str:
    """Build a deterministic resume fingerprint from all relevant stage inputs."""
    if not STAGE_ID_RE.fullmatch(stage_id):
        raise RunError(f"Invalid stage ID: {stage_id!r}")
    if not implementation_version or not config_digest or not scope_digest:
        raise RunError("Stage fingerprints require implementation, config, and scope digests.")

    payload = {
        "stage_id": stage_id,
        "implementation_version": implementation_version,
        "config_digest": config_digest,
        "scope_digest": scope_digest,
        "input_manifest_digest": input_manifest_digest,
        "prerequisite_outputs": prerequisite_outputs or {},
        "collector_version": collector_version,
    }
    return _sha256(payload)


def _recover_running_stages(state: dict[str, Any]) -> int:
    recovered = 0
    now = _utc_now()
    for stage in state.get("stages", {}).values():
        if stage.get("status") != "running":
            continue
        attempts = stage.get("attempts", [])
        if attempts and attempts[-1].get("status") == "running":
            attempts[-1]["status"] = "interrupted"
            attempts[-1]["finished_at"] = now
            attempts[-1]["error"] = "Recovered after an unfinished prior process."
            stage["status"] = "interrupted"
            recovered += 1
    if recovered:
        state["status"] = "interrupted"
        state["updated_at"] = now
    return recovered


def reconcile_interrupted_stages(paths: RunPaths) -> int:
    """Mark abandoned running stages interrupted; never infer success."""
    state = _read_json(paths.state)
    recovered = _recover_running_stages(state)
    if recovered:
        _write_json_atomic(paths.state, state, overwrite=True)
    return recovered


def begin_stage(paths: RunPaths, stage_id: str, fingerprint: str) -> StageDecision:
    """Start a stage or skip it when the prior successful fingerprint matches."""
    if not STAGE_ID_RE.fullmatch(stage_id):
        raise RunError(f"Invalid stage ID: {stage_id!r}")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise RunError("Stage fingerprint must be a SHA-256 hex digest.")

    state = _read_json(paths.state)
    if state.get("status") in TERMINAL_RUN_STATUSES:
        raise RunError(f"Cannot add work to a terminal run ({state['status']}).")

    recovered = _recover_running_stages(state)
    stages = state.setdefault("stages", {})
    prior = stages.get(stage_id)
    if prior and prior.get("status") == "success" and prior.get("fingerprint") == fingerprint:
        if recovered:
            _write_json_atomic(paths.state, state, overwrite=True)
        attempts = prior.get("attempts", [])
        return StageDecision(
            should_run=False,
            attempt=attempts[-1].get("attempt", 1) if attempts else 1,
            reason="A successful attempt with the same fingerprint already exists.",
        )

    attempts = prior.setdefault("attempts", []) if prior else []
    attempt_number = len(attempts) + 1
    now = _utc_now()
    attempts.append(
        {
            "attempt": attempt_number,
            "status": "running",
            "fingerprint": fingerprint,
            "started_at": now,
            "finished_at": None,
            "output_manifest": None,
            "error": None,
        }
    )
    stages[stage_id] = {
        "status": "running",
        "fingerprint": fingerprint,
        "attempt": attempt_number,
        "attempts": attempts,
    }
    state["status"] = "running"
    state["updated_at"] = now
    _write_json_atomic(paths.state, state, overwrite=True)
    return StageDecision(
        should_run=True,
        attempt=attempt_number,
        reason="No matching successful attempt exists.",
    )


def finish_stage(
    paths: RunPaths,
    stage_id: str,
    status: str,
    *,
    output_manifest: str | None = None,
    error: str | None = None,
) -> None:
    """Persist a terminal stage outcome without discarding prior attempts."""
    if status not in STAGE_TERMINAL_STATUSES:
        raise RunError(f"Unsupported terminal stage status: {status!r}")
    state = _read_json(paths.state)
    stage = state.get("stages", {}).get(stage_id)
    if not stage or stage.get("status") != "running":
        raise RunError(f"Stage is not currently running: {stage_id}")
    attempts = stage.get("attempts", [])
    if not attempts or attempts[-1].get("status") != "running":
        raise RunError(f"Stage has no active attempt: {stage_id}")

    now = _utc_now()
    attempt = attempts[-1]
    attempt["status"] = status
    attempt["finished_at"] = now
    attempt["output_manifest"] = output_manifest
    attempt["error"] = error
    stage["status"] = status
    state["updated_at"] = now
    _write_json_atomic(paths.state, state, overwrite=True)


def finalize_run(paths: RunPaths, status: str) -> None:
    """Set the final run status after all active stage attempts have stopped."""
    allowed = {"completed", "partial", "failed", "interrupted", "cancelled"}
    if status not in allowed:
        raise RunError(f"Unsupported final run status: {status!r}")
    state = _read_json(paths.state)
    running = [
        stage_id
        for stage_id, stage in state.get("stages", {}).items()
        if stage.get("status") == "running"
    ]
    if running:
        raise RunError("Cannot finalize while stages are running: " + ", ".join(running))
    state["status"] = status
    state["updated_at"] = _utc_now()
    state["finished_at"] = state["updated_at"]
    _write_json_atomic(paths.state, state, overwrite=True)


class WorkspaceLock:
    """Exclusive, non-stealable lock for one engagement's mutable workspace."""

    def __init__(self, engagement_dir: Path) -> None:
        self.path = engagement_dir / ".workspace.lock"
        self.token = uuid.uuid4().hex
        self.acquired = False

    def acquire(self) -> "WorkspaceLock":
        if self.path.is_symlink():
            raise WorkspaceLockError(f"Refusing symlinked workspace lock: {self.path}")
        payload = {
            "token": self.token,
            "pid": os.getpid(),
            "acquired_at": _utc_now(),
        }
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except FileExistsError as exc:
            owner = "owner details unavailable"
            try:
                existing = _read_json(self.path)
                owner = f"pid={existing.get('pid', '?')}, acquired_at={existing.get('acquired_at', '?')}"
            except RunError:
                pass
            raise WorkspaceLockError(
                f"Workspace is already locked ({owner}). Do not remove the lock "
                "until the owning process has been checked."
            ) from exc
        except OSError as exc:
            raise WorkspaceLockError(f"Cannot create workspace lock {self.path}: {exc}") from exc

        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            self.acquired = True
            return self
        except OSError as exc:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
            raise WorkspaceLockError(f"Cannot persist workspace lock: {exc}") from exc

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            current = _read_json(self.path)
        except RunError as exc:
            if not self.path.exists():
                self.acquired = False
                return
            raise WorkspaceLockError(
                "Cannot verify workspace lock ownership; leaving the lock in place."
            ) from exc
        if current.get("token") != self.token:
            raise WorkspaceLockError(
                "Workspace lock ownership changed; refusing to remove another process's lock."
            )
        try:
            self.path.unlink()
            self.acquired = False
        except OSError as exc:
            raise WorkspaceLockError(f"Cannot release workspace lock {self.path}: {exc}") from exc

    def __enter__(self) -> "WorkspaceLock":
        return self.acquire()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.release()
