"""Tests for durable FII run manifests, checkpoints, and workspace locks."""

import json
import os
import stat
from pathlib import Path

import pytest

from fii.core.config import validate_config
from fii.core.run_controller import (
    RunError,
    WorkspaceLock,
    WorkspaceLockError,
    begin_stage,
    create_run,
    finalize_run,
    finish_stage,
    make_stage_fingerprint,
    open_run,
    reconcile_interrupted_stages,
)
from fii.core.workspace import prepare_workspace


def make_workspace(tmp_path: Path):
    config = validate_config(
        {
            "workspace": str(tmp_path / "workspace"),
            "engagement": {
                "name": "Synthetic Financial Institution",
                "slug": "synthetic-financial-institution",
                "authorization_reference": "SYNTHETIC-LAB",
            },
            "scope": {
                "seed_domains": ["example.invalid"],
                "approved_organizations": ["Example Financial Group"],
            },
            "sources": {
                "ct_logs": {
                    "enabled": True,
                    "api_key": "do-not-write-this-secret",
                    "authorization": "Bearer do-not-write-this-token",
                }
            },
        }
    )
    return config, prepare_workspace(config)


def fingerprint(value: str = "a") -> str:
    return value * 64


def test_create_run_writes_private_manifest_and_redacted_snapshot(tmp_path: Path) -> None:
    config, workspace = make_workspace(tmp_path)

    run = create_run(workspace, config)

    manifest = json.loads(run.manifest.read_text(encoding="utf-8"))
    snapshot = json.loads(run.config_snapshot.read_text(encoding="utf-8"))
    state = json.loads(run.state.read_text(encoding="utf-8"))

    assert manifest["run_id"] == run.run_id
    assert manifest["scope_sha256"]
    assert state["status"] == "pending"
    assert snapshot["sources"]["ct_logs"]["api_key"] == "<redacted>"
    assert snapshot["engagement"]["authorization_reference"] == "SYNTHETIC-LAB"
    assert snapshot["sources"]["ct_logs"]["authorization"] == "<redacted>"
    if os.name == "posix":
        assert stat.S_IMODE(run.config_snapshot.stat().st_mode) == 0o600
        assert stat.S_IMODE(run.directory.stat().st_mode) == 0o700


def test_open_run_rejects_missing_or_mismatched_run(tmp_path: Path) -> None:
    config, workspace = make_workspace(tmp_path)
    run = create_run(workspace, config)

    assert open_run(workspace, run.run_id) == run
    with pytest.raises(RunError, match="Invalid run ID"):
        open_run(workspace, "../outside")
    with pytest.raises(RunError, match="does not exist"):
        open_run(workspace, "12345678-1234-5678-1234-567812345678")


def test_matching_successful_fingerprint_is_skipped(tmp_path: Path) -> None:
    config, workspace = make_workspace(tmp_path)
    run = create_run(workspace, config)

    first = begin_stage(run, "preflight_sources", fingerprint())
    assert first.should_run is True
    assert first.attempt == 1
    with pytest.raises(RunError, match="A stage is already running"):
        begin_stage(run, "collect_sources", fingerprint())

    finish_stage(
        run,
        "preflight_sources",
        "success",
        output_manifest="state/preflight-output.json",
    )
    resumed = begin_stage(run, "preflight_sources", fingerprint())

    assert resumed.should_run is False
    assert resumed.attempt == 1


def test_changed_fingerprint_creates_a_new_attempt(tmp_path: Path) -> None:
    config, workspace = make_workspace(tmp_path)
    run = create_run(workspace, config)

    begin_stage(run, "collect_sources", fingerprint("a"))
    finish_stage(run, "collect_sources", "success")
    second = begin_stage(run, "collect_sources", fingerprint("b"))

    assert second.should_run is True
    assert second.attempt == 2


def test_interrupted_stage_is_never_treated_as_success(tmp_path: Path) -> None:
    config, workspace = make_workspace(tmp_path)
    run = create_run(workspace, config)

    begin_stage(run, "normalize_observations", fingerprint())
    assert reconcile_interrupted_stages(run) == 1
    state = json.loads(run.state.read_text(encoding="utf-8"))
    assert state["stages"]["normalize_observations"]["status"] == "interrupted"

    retry = begin_stage(run, "normalize_observations", fingerprint())
    assert retry.should_run is True
    assert retry.attempt == 2


def test_run_cannot_be_finalized_while_stage_is_running(tmp_path: Path) -> None:
    config, workspace = make_workspace(tmp_path)
    run = create_run(workspace, config)

    begin_stage(run, "generate_reports", fingerprint())
    with pytest.raises(RunError, match="while stages are running"):
        finalize_run(run, "completed")

    finish_stage(run, "generate_reports", "success")
    finalize_run(run, "completed")
    state = json.loads(run.state.read_text(encoding="utf-8"))
    assert state["status"] == "completed"
    assert state["finished_at"]


def test_terminal_run_rejects_new_stages(tmp_path: Path) -> None:
    config, workspace = make_workspace(tmp_path)
    run = create_run(workspace, config)
    finalize_run(run, "completed")

    with pytest.raises(RunError, match="terminal run"):
        begin_stage(run, "collect_sources", fingerprint())


def test_workspace_lock_blocks_a_second_writer_and_releases(tmp_path: Path) -> None:
    _, workspace = make_workspace(tmp_path)

    with WorkspaceLock(workspace.engagement):
        assert (workspace.engagement / ".workspace.lock").is_file()
        with pytest.raises(WorkspaceLockError, match="already locked"):
            WorkspaceLock(workspace.engagement).acquire()

    assert not (workspace.engagement / ".workspace.lock").exists()


def test_workspace_lock_does_not_remove_another_owners_lock(tmp_path: Path) -> None:
    _, workspace = make_workspace(tmp_path)
    lock = WorkspaceLock(workspace.engagement).acquire()
    lock.path.write_text('{"token":"another-owner"}', encoding="utf-8")

    with pytest.raises(WorkspaceLockError, match="ownership changed"):
        lock.release()

    assert lock.path.is_file()


def test_stage_fingerprint_is_deterministic_and_input_sensitive() -> None:
    base = {
        "implementation_version": "1",
        "config_digest": "config",
        "scope_digest": "scope",
        "prerequisite_outputs": {"collect": "hash-a"},
    }
    first = make_stage_fingerprint("normalize", **base)
    same = make_stage_fingerprint("normalize", **base)
    changed = make_stage_fingerprint(
        "normalize",
        **{**base, "prerequisite_outputs": {"collect": "hash-b"}},
    )

    assert first == same
    assert first != changed


def test_stage_fingerprint_rejects_invalid_stage_id() -> None:
    with pytest.raises(RunError, match="Invalid stage ID"):
        make_stage_fingerprint(
            "../collect",
            implementation_version="1",
            config_digest="config",
            scope_digest="scope",
        )
