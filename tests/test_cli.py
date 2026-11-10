"""Offline tests for the FII command-line interface."""

from pathlib import Path

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
