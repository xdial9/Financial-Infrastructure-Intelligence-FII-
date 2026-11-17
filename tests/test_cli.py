"""Offline tests for the FII command-line interface."""

from pathlib import Path

import yaml
from click.testing import CliRunner

from fii import __version__
from fii.cli.main import main


def write_config(path: Path, workspace: Path) -> None:
    path.write_text(
        "workspace: " + str(workspace) + "\n"
        "engagement:\n  name: Synthetic\n  slug: synthetic\n"
        "scope:\n  seed_domains: [example.invalid]\n",
        encoding="utf-8",
    )


def test_help_displays_commands() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "doctor" in result.output
    assert "validate-config" in result.output
    assert "init" in result.output


def test_version_displays_package_version() -> None:
    result = CliRunner().invoke(main, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output


def test_doctor_is_read_only(tmp_path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("FII_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("FII_WORKSPACE", str(workspace))

    result = CliRunner().invoke(main, ["doctor"])

    assert result.exit_code == 0
    assert "Environment check (read-only)" in result.output
    assert "not created yet" in result.output
    assert not config_dir.exists()
    assert not workspace.exists()


def test_validate_config_displays_normalized_scope(tmp_path: Path) -> None:
    config_path = tmp_path / "engagement.yaml"
    write_config(config_path, tmp_path / "workspace")

    result = CliRunner().invoke(main, ["validate-config", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Configuration valid." in result.output
    assert "example.invalid" in result.output


def test_init_creates_workspace_without_changing_config(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config_path = tmp_path / "engagement.yaml"
    write_config(config_path, workspace)
    original_config = config_path.read_text(encoding="utf-8")

    result = CliRunner().invoke(main, ["init", "--config", str(config_path)])

    assert result.exit_code == 0
    assert (workspace / "engagements" / "synthetic" / "database").is_dir()
    assert (workspace / "engagements" / "synthetic" / "runs").is_dir()
    assert config_path.read_text(encoding="utf-8") == original_config


def test_validate_config_reports_invalid_scope(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text(
        "engagement:\n  name: Invalid\n  slug: invalid\n"
        "scope:\n  seed_domains: [https://example.invalid]\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(main, ["validate-config", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "hostname only" in result.output

def test_help_displays_full_operator_workflow() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    for command in (
        "sources", "run", "resume", "status",
        "report", "review-queue", "review", "backup",
    ):
        assert command in result.output


def test_sources_list_is_read_only_and_shows_disabled_defaults() -> None:
    result = CliRunner().invoke(main, ["sources", "list"])

    assert result.exit_code == 0
    assert "ct_live" in result.output
    assert "rdap_domain" in result.output
    assert "live approval required" in result.output
    assert "all sources default to disabled" in result.output
    assert "ENABLED" not in result.output


def test_status_without_database_does_not_create_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    config_path = tmp_path / "engagement.yaml"
    write_config(config_path, workspace)

    result = CliRunner().invoke(
        main,
        ["status", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    assert "No runs yet" in result.output
    assert not workspace.exists()

def test_cli_executes_full_synthetic_run_status_report_and_backup(tmp_path: Path) -> None:
    demo_path = Path(__file__).parents[1] / "examples" / "synthetic-demo" / "config.yaml"
    config = yaml.safe_load(demo_path.read_text(encoding="utf-8"))
    config["workspace"] = str(tmp_path / "workspace")
    for source_settings in config["sources"].values():
        fixture = source_settings.get("fixture")
        if fixture:
            source_settings["fixture"] = str((demo_path.parent / fixture).resolve())
    config_path = tmp_path / "engagement.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    runner = CliRunner()
    run_result = runner.invoke(main, ["run", "--config", str(config_path)])
    assert run_result.exit_code == 0, run_result.output
    run_line = next(line for line in run_result.output.splitlines() if line.startswith("Run ID: "))
    run_id = run_line.removeprefix("Run ID: ").strip()
    assert "Status: completed" in run_result.output
    assert "executive-summary.md" in run_result.output

    status_result = runner.invoke(
        main, ["status", "--config", str(config_path), "--run-id", run_id]
    )
    assert status_result.exit_code == 0, status_result.output
    assert run_id in status_result.output
    assert "completed" in status_result.output

    report_result = runner.invoke(
        main, ["report", "--config", str(config_path), "--run-id", run_id]
    )
    assert report_result.exit_code == 0, report_result.output
    assert "report-manifest.json" in report_result.output

    backup_path = tmp_path / "backups" / "fii.sqlite3"
    backup_path.parent.mkdir()
    backup_result = runner.invoke(
        main,
        ["backup", "--config", str(config_path), "--destination", str(backup_path)],
    )
    assert backup_result.exit_code == 0, backup_result.output
    assert backup_path.is_file()

