"""FII command-line entry point."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

import click

from fii import __version__
from fii.core.config import ConfigError, load_config
from fii.core.pipeline import PipelineError, PipelineResult, execute_pipeline
from fii.core.run_controller import RunError, open_run
from fii.core.scope import ScopeError
from fii.core.workspace import (
    WorkspaceError,
    WorkspacePaths,
    prepare_workspace,
)
from fii.reporting import ReportError, render_reports
from fii.relationships.correlation import (
    RelationshipError,
    list_relationship_review_queue,
    review_relationship,
)
from fii.sources.registry import get_default_registry
from fii.storage.database import (
    PersistenceError,
    backup_database,
    connect_database,
)

DATABASE_NAME = "fii.sqlite3"


def _configured_config_path() -> Path:
    """Return the default local configuration path without creating it."""
    config_dir = Path(
        os.environ.get("FII_CONFIG_DIR", Path.home() / ".config" / "fii")
    ).expanduser()
    return config_dir / "config.yaml"


def _print_check(name: str, status: str, detail: str) -> None:
    click.echo(f"{status:<5} {name:<14} {detail}")


def _validated_config(config_path: Path) -> dict[str, Any]:
    try:
        return load_config(config_path)
    except (ConfigError, ScopeError) as exc:
        raise click.ClickException(str(exc)) from exc


def _workspace_paths(config: dict[str, Any]) -> WorkspacePaths:
    """Resolve the engagement directories without creating them."""
    root = Path(config["workspace"]).expanduser()
    slug = config["engagement"]["slug"]
    requested = (
        root,
        root / "engagements",
        root / "engagements" / slug,
        root / "engagements" / slug / "database",
        root / "engagements" / slug / "runs",
    )
    for path in requested:
        if path.is_symlink():
            raise click.ClickException(f"Refusing symlinked workspace path: {path}")
    return WorkspacePaths(
        root=root,
        engagement=requested[2],
        database=requested[3],
        runs=requested[4],
    )


def _database_path(paths: WorkspacePaths) -> Path:
    path = paths.database / DATABASE_NAME
    if path.is_symlink():
        raise click.ClickException(f"Refusing symlinked evidence database: {path}")
    if not path.is_file():
        raise click.ClickException(
            f"No FII evidence database exists at {path}. Initialize the workspace "
            "and execute an engagement run first."
        )
    return path


def _readonly_database(path: Path) -> sqlite3.Connection:
    """Open a query-only SQLite connection for operator status and queue views."""
    resolved = path.resolve(strict=True)
    connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _run_and_report(
    config: dict[str, Any],
    config_path: Path,
    *,
    resume_run_id: str | None = None,
) -> PipelineResult:
    try:
        result = execute_pipeline(
            config,
            config_path,
            resume_run_id=resume_run_id,
        )
        report = render_reports(
            result.database_path,
            result.run_id,
            result.run_directory,
        )
    except (PipelineError, ReportError, RunError, PersistenceError) as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Run ID: {result.run_id}")
    click.echo(f"Status: {result.status}")
    click.echo(f"Sources: {json.dumps(result.source_counts, sort_keys=True)}")
    click.echo(f"Observations: {result.observation_count}")
    click.echo(f"Entities: {result.entity_count}")
    click.echo(f"Relationships: {result.relationship_count}")
    click.echo(f"Research findings: {result.finding_count}")
    click.echo(f"Report directory: {report.directory}")
    click.echo("Report files:")
    for path in report.files:
        click.echo(f"  - {path.name}")
    return result


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
    workspace_value = os.environ.get("FII_WORKSPACE", Path.home() / "FII-Workspace")
    workspace_path = Path(workspace_value).expanduser()
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
    config = _validated_config(config_path)
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
    config = _validated_config(config_path)
    try:
        paths = prepare_workspace(config)
    except WorkspaceError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Workspace initialized for: {config['engagement']['name']}")
    click.echo(f"Root: {paths.root}")
    click.echo(f"Engagement: {paths.engagement}")
    click.echo(f"Database directory: {paths.database}")
    click.echo(f"Runs directory: {paths.runs}")
    click.echo("Existing files were preserved.")


@main.group()
def sources() -> None:
    """Inspect the fixed, built-in source catalogue."""


@sources.command("list")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    required=False,
    help="Optional engagement config to show per-engagement enablement.",
)
def sources_list(config_path: Path | None) -> None:
    """List source IDs, collection types, and default activation state."""
    config = _validated_config(config_path) if config_path else None
    configured = config.get("sources", {}) if config else {}
    click.echo("FII source catalogue (all sources default to disabled)")
    for definition in get_default_registry().definitions():
        settings = configured.get(definition.source_id, {})
        enabled = bool(settings.get("enabled", False))
        if settings.get("fixture"):
            collection_mode = "fixture"
        elif definition.source_id in {"ct_logs", "web_surface"}:
            collection_mode = "fixture required"
        elif definition.source_id in {"ct_live", "website_public", "rdap_domain", "gleif_lei"}:
            collection_mode = "live approval required"
        else:
            collection_mode = "operator configured"
        click.echo(
            f"{definition.source_id:<16} "
            f"{'ENABLED' if enabled else 'disabled':<10} "
            f"{definition.source_class:<20} "
            f"{collection_mode}"
        )
        click.echo(f"  {definition.name}: {definition.description}")
        if definition.documentation_url:
            click.echo(f"  Documentation: {definition.documentation_url}")
        if definition.terms_url:
            click.echo(f"  Terms: {definition.terms_url}")


@main.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    required=True,
    help="Validated engagement YAML file.",
)
def run(config_path: Path) -> None:
    """Execute enabled sources sequentially and publish the report package."""
    config = _validated_config(config_path)
    _run_and_report(config, config_path)


@main.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    required=True,
    help="The same engagement YAML used to create the run.",
)
@click.option("--run-id", required=True, help="UUID of an interrupted run to resume.")
def resume(config_path: Path, run_id: str) -> None:
    """Resume unfinished stages and re-publish the evidence report."""
    config = _validated_config(config_path)
    _run_and_report(config, config_path, resume_run_id=run_id)


@main.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    required=True,
    help="Engagement YAML file.",
)
@click.option("--run-id", required=False, help="Show one run instead of recent runs.")
@click.option("--limit", type=click.IntRange(min=1, max=100), default=20, show_default=True)
def status(config_path: Path, run_id: str | None, limit: int) -> None:
    """Read run statuses from the evidence database without changing it."""
    config = _validated_config(config_path)
    paths = _workspace_paths(config)
    db_path = paths.database / DATABASE_NAME
    if db_path.is_symlink():
        raise click.ClickException(f"Refusing symlinked evidence database: {db_path}")
    if not db_path.is_file():
        click.echo("No runs yet. Initialize the workspace and run an engagement.")
        return
    connection: sqlite3.Connection | None = None
    try:
        connection = _readonly_database(db_path)
        if run_id:
            rows = connection.execute(
                """
                SELECT run_id, started_at, finished_at, status, summary_json
                FROM run WHERE run_id=? AND engagement_id=(
                    SELECT engagement_id FROM engagement WHERE slug=?
                )
                """,
                (run_id, config["engagement"]["slug"]),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT r.run_id, r.started_at, r.finished_at, r.status, r.summary_json
                FROM run r JOIN engagement e ON e.engagement_id=r.engagement_id
                WHERE e.slug=?
                ORDER BY r.started_at DESC, r.run_id DESC LIMIT ?
                """,
                (config["engagement"]["slug"], limit),
            ).fetchall()
    except sqlite3.Error as exc:
        raise click.ClickException("Unable to read the run status database.") from exc
    finally:
        if connection is not None:
            connection.close()

    if not rows:
        click.echo("No matching runs.")
        return
    for row in rows:
        click.echo(
            f"{row['run_id']}  {row['status']:<12} "
            f"started={row['started_at']}  finished={row['finished_at'] or '-'}"
        )
        if row["summary_json"]:
            try:
                click.echo(f"  {json.dumps(json.loads(row['summary_json']), sort_keys=True)}")
            except json.JSONDecodeError:
                click.echo("  Warning: stored run summary is not valid JSON.")


@main.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    required=True,
    help="Engagement YAML file.",
)
@click.option("--run-id", required=True, help="Run UUID for report generation.")
def report(config_path: Path, run_id: str) -> None:
    """Regenerate report exports from the canonical evidence store."""
    config = _validated_config(config_path)
    paths = _workspace_paths(config)
    try:
        run_paths = open_run(paths, run_id)
        database = _database_path(paths)
        result = render_reports(database, run_id, run_paths.directory)
    except (RunError, ReportError, PersistenceError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Report directory: {result.directory}")
    for path in result.files:
        click.echo(f"  - {path.name}")


@main.command("review-queue")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    required=True,
    help="Engagement YAML file.",
)
@click.option("--limit", type=click.IntRange(min=1, max=1000), default=100, show_default=True)
def review_queue(config_path: Path, limit: int) -> None:
    """List unresolved evidence-backed relationships for analyst review."""
    config = _validated_config(config_path)
    paths = _workspace_paths(config)
    connection: sqlite3.Connection | None = None
    try:
        connection = _readonly_database(_database_path(paths))
        items = list_relationship_review_queue(connection, limit=limit)
    except (sqlite3.Error, PersistenceError, ValueError) as exc:
        raise click.ClickException("Unable to read the relationship review queue.") from exc
    finally:
        if connection is not None:
            connection.close()
    if not items:
        click.echo("The analyst review queue is empty.")
        return
    for item in items:
        click.echo(
            f"{item.relationship_id}  {item.verification_state}  "
            f"{item.confidence if item.confidence is not None else 'n/a'}"
        )
        click.echo(f"  {item.subject_name} --{item.predicate}--> {item.object_name}")
        click.echo(f"  Last disposition: {item.latest_disposition or 'not reviewed'}")
        click.echo(f"  Rationale: {item.rationale or '(none recorded)'}")


@main.command("review")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    required=True,
    help="Engagement YAML file.",
)
@click.option("--relationship-id", required=True, help="Relationship UUID.")
@click.option(
    "--disposition",
    type=click.Choice(["accepted", "rejected", "needs_research"]),
    required=True,
)
@click.option("--reviewer", required=True, help="Analyst identifier or team label.")
@click.option("--rationale", required=True, help="Reason for the disposition.")
def review(
    config_path: Path,
    relationship_id: str,
    disposition: str,
    reviewer: str,
    rationale: str,
) -> None:
    """Append an analyst disposition without changing underlying evidence confidence."""
    config = _validated_config(config_path)
    paths = _workspace_paths(config)
    try:
        with closing(connect_database(_database_path(paths))) as connection:
            result = review_relationship(
                connection,
                relationship_id=relationship_id,
                disposition=disposition,
                reviewer_label=reviewer,
                rationale=rationale,
            )
    except (RelationshipError, PersistenceError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Review recorded: {result.review_id}")
    click.echo(f"Relationship: {result.relationship_id}")
    click.echo(f"Disposition: {result.disposition}")
    click.echo(f"Verification state: {result.verification_state}")
    click.echo("Evidence confidence was not increased by this review.")


@main.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    required=True,
    help="Engagement YAML file.",
)
@click.option(
    "--destination",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    required=True,
    help="New backup path; an existing file will never be overwritten.",
)
def backup(config_path: Path, destination: Path) -> None:
    """Create and verify a no-overwrite SQLite backup."""
    config = _validated_config(config_path)
    paths = _workspace_paths(config)
    try:
        result = backup_database(_database_path(paths), destination)
    except PersistenceError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Verified database backup: {result}")


if __name__ == "__main__":
    main()
