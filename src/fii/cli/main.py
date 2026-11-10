"""FII command-line entry point."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import click

from fii import __version__
from fii.core.config import ConfigError, load_config
from fii.core.scope import ScopeError
from fii.core.workspace import WorkspaceError, prepare_workspace


def _configured_config_path() -> Path:
    """Return the default local configuration path without creating it."""
    import os

    config_dir = Path(
        os.environ.get("FII_CONFIG_DIR", Path.home() / ".config" / "fii")
    ).expanduser()
    return config_dir / "config.yaml"


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

    checks_ok = True
    python_ok = sys.version_info >= (3, 11)
    python_version = ".".join(str(part) for part in sys.version_info[:3])
    _print_check(
        "Python",
        "PASS" if python_ok else "FAIL",
        f"{python_version} (requires 3.11+)",
    )
    checks_ok = checks_ok and python_ok

    _print_check("SQLite", "PASS", sqlite3.sqlite_version)

    config_path = _configured_config_path()
    workspace_path = Path.home() / "FII-Workspace"
    if config_path.is_file():
        try:
            config = load_config(config_path)
            workspace_path = Path(config["workspace"]).expanduser()
            _print_check("Configuration", "PASS", str(config_path))
        except (ConfigError, ScopeError) as exc:
            _print_check("Configuration", "FAIL", str(exc))
            checks_ok = False
    else:
        _print_check("Configuration", "INFO", f"not created yet: {config_path}")

    if workspace_path.is_symlink():
        _print_check("Workspace", "FAIL", f"refusing symlinked path: {workspace_path}")
        checks_ok = False
    elif workspace_path.is_dir():
        _print_check("Workspace", "FOUND", str(workspace_path))
    elif workspace_path.exists():
        _print_check("Workspace", "FAIL", f"path is not a directory: {workspace_path}")
        checks_ok = False
    else:
        _print_check("Workspace", "INFO", f"not initialized yet: {workspace_path}")

    click.echo("")
    if checks_ok:
        click.echo("Doctor result: local prerequisites look good.")
    else:
        click.echo("Doctor result: one or more checks failed.")
        raise click.exceptions.Exit(1)


@main.command("validate-config")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    required=True,
    help="Engagement YAML file to validate.",
)
def validate_config_command(config_path: Path) -> None:
    """Validate an engagement file and display its normalized scope."""
    try:
        config = load_config(config_path)
    except (ConfigError, ScopeError) as exc:
        raise click.ClickException(str(exc)) from exc

    engagement = config["engagement"]
    scope = config["scope"]
    click.echo("Configuration valid.")
    click.echo(f"Engagement: {engagement['name']}")
    click.echo(f"Slug: {engagement['slug']}")
    click.echo(f"Organization: {engagement['organization'] or '(not specified)'}")
    click.echo(f"Seed domains: {len(scope['seed_domains'])}")
    for domain in scope["seed_domains"]:
        click.echo(f"  - {domain}")
    click.echo(f"Approved organizations: {len(scope['approved_organizations'])}")
    click.echo(f"Permitted source classes: {', '.join(scope['permitted_source_classes'])}")
    click.echo("Collection mode: sequential")
    click.echo("Active validation: disabled")


@main.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    required=True,
    help="Validated engagement YAML file.",
)
def init(config_path: Path) -> None:
    """Initialize the engagement workspace without replacing existing data."""
    try:
        config = load_config(config_path)
        paths = prepare_workspace(config)
    except (ConfigError, ScopeError, WorkspaceError) as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Workspace initialized for: {config['engagement']['name']}")
    click.echo(f"Root: {paths.root}")
    click.echo(f"Engagement: {paths.engagement}")
    click.echo(f"Database directory: {paths.database}")
    click.echo(f"Runs directory: {paths.runs}")
    click.echo("Existing files were preserved.")


if __name__ == "__main__":
    main()
