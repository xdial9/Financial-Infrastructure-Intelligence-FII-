from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from fii.cli.main import main

ROOT = Path(__file__).resolve().parents[1]


def test_validate_command_is_read_only(tmp_path):
    config = ROOT / "examples" / "synthetic_engagement.yaml"
    result = CliRunner().invoke(main, ["validate", "--config", str(config)])
    assert result.exit_code == 0, result.output
    assert "Configuration valid" in result.output
    assert "No workspace or network activity performed" in result.output


def test_scope_show_prints_only_approved_domains():
    config = ROOT / "examples" / "synthetic_engagement.yaml"
    result = CliRunner().invoke(main, ["scope", "show", "--config", str(config)])
    assert result.exit_code == 0, result.output
    assert "example.invalid" in result.output
    assert "Active validation: disabled" in result.output


def test_init_command_creates_workspace_only_after_validation(tmp_path):
    config = ROOT / "examples" / "synthetic_engagement.yaml"
    workspace = tmp_path / "workspace"
    result = CliRunner().invoke(main, ["init", "--config", str(config), "--workspace", str(workspace)])
    assert result.exit_code == 0, result.output
    engagement = workspace / "engagements" / "synthetic-financial-institution"
    assert (engagement / "database").is_dir()
    assert (engagement / "config" / "engagement.yaml").is_file()


def test_invalid_profile_does_not_create_workspace(tmp_path):
    config = tmp_path / "invalid.yaml"
    config.write_text("engagement: nope\n")
    workspace = tmp_path / "workspace"
    result = CliRunner().invoke(main, ["init", "--config", str(config), "--workspace", str(workspace)])
    assert result.exit_code != 0
    assert not workspace.exists()
