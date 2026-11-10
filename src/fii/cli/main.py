"""FII command-line entry point."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import click

from fii import __version__


def _configured_paths() -> tuple[Path, Path]:
    """Return default config and workspace paths without creating them."""
    config_dir = Path(
        os.environ.get("FII_CONFIG_DIR", Path.home() / ".config" / "fii")
    ).expanduser()
    workspace = Path(
        os.environ.get("FII_WORKSPACE", Path.home() / "FII-Workspace")
    ).expanduser()
    return config_dir / "config.yaml", workspace


def _print_check(name: str, status: str, detail: str) -> None:
    click.echo(f"{status:<5} {name:<14} {detail}")


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    no_args_is_help=True,
)
@click.version_option(version=__version__, prog_name="fii")
def main() -> None:
    """Collect, correlate and report financial infrastructure intelligence."""


@main.command()
def doctor() -> None:
    """Check the local FII runtime without changing the filesystem."""
    click.echo("FII — Financial Infrastructure Intelligence")
    click.echo("Environment check (read-only)")
    click.echo("")

    python_ok = sys.version_info >= (3, 11)
    python_version = ".".join(str(part) for part in sys.version_info[:3])
    _print_check(
        "Python",
        "PASS" if python_ok else "FAIL",
        f"{python_version} (requires 3.11+)",
    )

    sqlite_version = sqlite3.sqlite_version
    _print_check("SQLite", "PASS", sqlite_version)

    config_path, workspace_path = _configured_paths()
    if config_path.is_file():
        _print_check("Configuration", "FOUND", str(config_path))
    else:
        _print_check(
            "Configuration",
            "INFO",
            f"not created yet: {config_path}",
        )

    if workspace_path.is_dir():
        _print_check("Workspace", "FOUND", str(workspace_path))
    else:
        _print_check(
            "Workspace",
            "INFO",
            f"not initialized yet: {workspace_path}",
        )

    click.echo("")
    if python_ok:
        click.echo("Doctor result: ready for the configuration/workspace phase.")
    else:
        click.echo("Doctor result: Python version is below the supported minimum.")
        raise click.exceptions.Exit(1)


if __name__ == "__main__":
    main()
