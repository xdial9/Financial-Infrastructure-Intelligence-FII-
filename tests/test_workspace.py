"""Tests for safe FII engagement workspace setup."""

from pathlib import Path

import pytest

from fii.core.config import validate_config
from fii.core.workspace import WorkspaceError, prepare_workspace


def make_config(workspace: Path) -> dict:
    return validate_config(
        {
            "workspace": str(workspace),
            "engagement": {"name": "Synthetic", "slug": "synthetic"},
            "scope": {"seed_domains": ["example.invalid"]},
        }
    )


def test_prepare_workspace_creates_expected_directories(tmp_path: Path) -> None:
    config = make_config(tmp_path / "FII-Workspace")

    paths = prepare_workspace(config)

    assert paths.engagement.is_dir()
    assert paths.database.is_dir()
    assert paths.runs.is_dir()
    assert paths.engagement == paths.root / "engagements" / "synthetic"


def test_prepare_workspace_preserves_existing_files(tmp_path: Path) -> None:
    root = tmp_path / "FII-Workspace"
    existing = root / "engagements" / "synthetic" / "database" / "keep.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("preserve", encoding="utf-8")

    prepare_workspace(make_config(root))

    assert existing.read_text(encoding="utf-8") == "preserve"


def test_prepare_workspace_refuses_symlinked_root(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "workspace-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks are unavailable in this environment.")

    with pytest.raises(WorkspaceError, match="symlinked workspace root"):
        prepare_workspace(make_config(link))
