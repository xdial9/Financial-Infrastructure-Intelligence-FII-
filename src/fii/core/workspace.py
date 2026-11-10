"""Per-engagement workspace creation and path containment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class WorkspaceError(RuntimeError):
    """Raised when an engagement workspace cannot be prepared safely."""


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    engagement: Path
    database: Path
    runs: Path


def _create_private_directory(path: Path, parent: Path | None = None) -> Path:
    if path.is_symlink():
        raise WorkspaceError(f"Refusing symlinked workspace path: {path}")

    existed = path.exists()
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not existed:
            os.chmod(path, 0o700)
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise WorkspaceError(f"Cannot create workspace directory {path}: {exc}") from exc

    if parent is not None:
        try:
            resolved.relative_to(parent.resolve(strict=True))
        except ValueError as exc:
            raise WorkspaceError(
                f"Workspace path escapes its expected parent: {resolved}"
            ) from exc
    return resolved


def prepare_workspace(config: dict[str, Any]) -> WorkspacePaths:
    """Create engagement directories without replacing any existing contents."""
    workspace_value = config.get("workspace")
    engagement_config = config.get("engagement", {})
    slug = engagement_config.get("slug")

    if not isinstance(workspace_value, str) or not workspace_value:
        raise WorkspaceError("Validated configuration must include a workspace path.")
    if not isinstance(slug, str) or not slug:
        raise WorkspaceError("Validated configuration must include an engagement slug.")

    requested_root = Path(workspace_value).expanduser()
    if requested_root.is_symlink():
        raise WorkspaceError(f"Refusing symlinked workspace root: {requested_root}")

    root = _create_private_directory(requested_root)
    engagements_root = _create_private_directory(root / "engagements", root)
    engagement = _create_private_directory(engagements_root / slug, engagements_root)
    database = _create_private_directory(engagement / "database", engagement)
    runs = _create_private_directory(engagement / "runs", engagement)

    return WorkspacePaths(
        root=root,
        engagement=engagement,
        database=database,
        runs=runs,
    )
