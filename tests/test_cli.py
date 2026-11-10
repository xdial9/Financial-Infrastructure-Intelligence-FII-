"""Offline tests for the initial FII command-line interface."""

from click.testing import CliRunner

from fii import __version__
from fii.cli.main import main


def test_help_displays_commands() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "doctor" in result.output


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
