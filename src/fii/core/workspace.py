"""Safe, non-destructive engagement workspace initialization."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class FIIWorkspaceError(RuntimeError):
    """Raised when a workspace path is invalid or unsafe to initialize."""


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    engagement: Path
    config: Path
    profile_file: Path
    database: Path
    runs: Path


def _ensure_private_directory(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise FIIWorkspaceError(f"Workspace path exists but is not a directory: {path}")
        return
    _ensure_private_directory(path.parent)
    try:
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700)
    except FileExistsError:
        if not path.is_dir():
            raise FIIWorkspaceError(f"Workspace path is not a directory: {path}")


def prepare_workspace(
    workspace_root: str | Path,
    engagement_slug: str,
    source_config_path: str | Path | None = None,
) -> WorkspacePaths:
    if not _SLUG.fullmatch(engagement_slug):
        raise FIIWorkspaceError("Engagement slug is not safe for use as a directory name")

    root = Path(workspace_root).expanduser().resolve()
    engagement = (root / "engagements" / engagement_slug).resolve()
    try:
        engagement.relative_to(root)
    except ValueError as exc:
        raise FIIWorkspaceError("Engagement workspace escapes the configured workspace root") from exc

    paths = WorkspacePaths(
        root=root,
        engagement=engagement,
        config=engagement / "config",
        profile_file=engagement / "config" / "engagement.yaml",
        database=engagement / "database",
        runs=engagement / "runs",
    )
    managed_paths = (
        paths.root / "engagements", paths.engagement, paths.config, paths.database, paths.runs
    )
    for path in managed_paths:
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise FIIWorkspaceError(f"Workspace subdirectory escapes the configured root: {path}") from exc
    _ensure_private_directory(paths.root)
    for path in managed_paths:
        _ensure_private_directory(path)

    if source_config_path is not None and not paths.profile_file.exists():
        source = Path(source_config_path).expanduser().resolve()
        if not source.is_file():
            raise FIIWorkspaceError(f"Source engagement configuration not found: {source}")
        try:
            shutil.copy2(source, paths.profile_file)
            os.chmod(paths.profile_file, 0o600)
        except FileExistsError:
            # A concurrent initializer won the race; never replace its file.
            pass
    return paths
