from __future__ import annotations

import os
from pathlib import Path

import pytest

from fii.core.config import FIIConfigError, load_config
from fii.core.scope import host_in_scope, normalize_domain
from fii.core.workspace import FIIWorkspaceError, prepare_workspace

ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_profile_loads_and_normalizes_domains():
    config = load_config(ROOT / "examples" / "synthetic_engagement.yaml")
    assert config.engagement.slug == "synthetic-financial-institution"
    assert config.scope.seed_domains == ("example.invalid", "portal.example.invalid")
    assert [source.source_id for source in config.enabled_sources] == ["ct_logs", "rdap"]
    assert config.scope.allow_active_validation is False


def test_domain_normalization_and_label_boundary_scope():
    assert normalize_domain("BÜCHER.Example.") == "xn--bcher-kva.example"
    domains = ("example.invalid",)
    assert host_in_scope("example.invalid", domains)
    assert host_in_scope("api.example.invalid", domains)
    assert not host_in_scope("example.invalid.attacker.test", domains)
    assert not host_in_scope("notexample.invalid", domains)


@pytest.mark.parametrize(
    "bad_domain",
    ["https://example.invalid", "*.example.invalid", "example.invalid/path", "-bad.example", "singlelabel"],
)
def test_invalid_seed_domains_are_rejected(tmp_path, bad_domain):
    content = (ROOT / "examples" / "synthetic_engagement.yaml").read_text()
    content = content.replace('"example.invalid"', f'"{bad_domain}"', 1)
    path = tmp_path / "bad.yaml"
    path.write_text(content)
    with pytest.raises(FIIConfigError):
        load_config(path)


def test_active_validation_and_parallel_mode_are_rejected(tmp_path):
    source = (ROOT / "examples" / "synthetic_engagement.yaml").read_text()
    active = tmp_path / "active.yaml"
    active.write_text(source.replace("allow_active_validation: false", "allow_active_validation: true"))
    with pytest.raises(FIIConfigError, match="Active validation is not implemented"):
        load_config(active)
    parallel = tmp_path / "parallel.yaml"
    parallel.write_text(source.replace("sequential: true", "sequential: false"))
    with pytest.raises(FIIConfigError, match="must be true"):
        load_config(parallel)


def test_invalid_required_source_cannot_be_disabled(tmp_path):
    source = (ROOT / "examples" / "synthetic_engagement.yaml").read_text()
    path = tmp_path / "disabled-required.yaml"
    path.write_text(source.replace("enabled: true\n    required: true", "enabled: false\n    required: true"))
    with pytest.raises(FIIConfigError, match="cannot be disabled"):
        load_config(path)


def test_workspace_is_created_private_and_existing_files_are_preserved(tmp_path):
    source_config = tmp_path / "source.yaml"
    source_config.write_text("engagement: synthetic\n")
    paths = prepare_workspace(
        tmp_path / "workspace", "synthetic-financial-institution", source_config
    )
    assert paths.engagement.is_dir()
    assert paths.config.is_dir() and paths.database.is_dir() and paths.runs.is_dir()
    assert os.stat(paths.engagement).st_mode & 0o777 == 0o700
    assert paths.profile_file.read_text() == "engagement: synthetic\n"
    marker = paths.config / "operator-note.txt"
    marker.write_text("preserve me")
    paths.profile_file.write_text("operator-adjusted profile\n")
    prepare_workspace(tmp_path / "workspace", "synthetic-financial-institution", source_config)
    assert marker.read_text() == "preserve me"
    assert paths.profile_file.read_text() == "operator-adjusted profile\n"


def test_workspace_rejects_unsafe_slug(tmp_path):
    with pytest.raises(FIIWorkspaceError, match="not safe"):
        prepare_workspace(tmp_path / "workspace", "../outside")


def test_workspace_rejects_file_where_directory_is_expected(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "engagements").write_text("not a directory")
    with pytest.raises(FIIWorkspaceError, match="not a directory"):
        prepare_workspace(root, "synthetic-financial-institution")


def test_workspace_rejects_symlink_escape_before_writing(tmp_path):
    root = tmp_path / "workspace"
    engagement = root / "engagements" / "synthetic-financial-institution"
    engagement.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (engagement / "config").symlink_to(outside, target_is_directory=True)
    with pytest.raises(FIIWorkspaceError, match="escapes the configured root"):
        prepare_workspace(root, "synthetic-financial-institution")
