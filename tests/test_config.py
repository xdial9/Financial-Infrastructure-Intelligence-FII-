"""Tests for FII configuration validation."""

from pathlib import Path

import pytest

from fii.core.config import ConfigError, load_config, validate_config


def valid_config() -> dict:
    return {
        "engagement": {
            "name": "Synthetic Financial Institution",
            "slug": "synthetic-financial-institution",
        },
        "scope": {
            "seed_domains": ["Example.Invalid.", "example.invalid"],
            "approved_organizations": ["Example Financial Group"],
        },
    }


def test_validate_config_applies_defaults_and_normalizes_domains() -> None:
    config = validate_config(valid_config())

    assert config["workspace"].endswith("FII-Workspace")
    assert config["scope"]["seed_domains"] == ["example.invalid"]
    assert config["collection"]["sequential"] is True
    assert config["scope"]["allow_active_validation"] is False


def test_validate_config_rejects_unknown_top_level_key() -> None:
    raw = valid_config()
    raw["collecton"] = {}

    with pytest.raises(ConfigError, match="Unknown top-level"):
        validate_config(raw)


def test_validate_config_requires_scope() -> None:
    raw = valid_config()
    raw["scope"] = {"seed_domains": [], "approved_organizations": []}

    with pytest.raises(ConfigError, match="at least one seed domain"):
        validate_config(raw)


def test_validate_config_rejects_active_validation_in_mvp() -> None:
    raw = valid_config()
    raw["scope"]["allow_active_validation"] = True

    with pytest.raises(ConfigError, match="not implemented"):
        validate_config(raw)


def test_validate_config_requires_sequential_collection() -> None:
    raw = valid_config()
    raw["collection"] = {"sequential": False}

    with pytest.raises(ConfigError, match="requires collection.sequential"):
        validate_config(raw)


def test_load_config_reads_yaml_and_applies_defaults(tmp_path: Path) -> None:
    path = tmp_path / "engagement.yaml"
    path.write_text(
        "engagement:\n  name: Synthetic\n  slug: synthetic\n"
        "scope:\n  seed_domains: [example.invalid]\n",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config["engagement"]["slug"] == "synthetic"
    assert config["scope"]["seed_domains"] == ["example.invalid"]


def test_workspace_environment_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FII_WORKSPACE", str(tmp_path / "env-workspace"))
    config = validate_config(valid_config())

    assert config["workspace"] == str(tmp_path / "env-workspace")

def test_default_configuration_is_not_mutated_between_loads() -> None:
    first = validate_config(valid_config())
    first["scope"]["permitted_source_classes"].append("customer_supplied")
    second = validate_config(valid_config())

    assert second["scope"]["permitted_source_classes"] == [
        "public_api",
        "public_dataset",
    ]


def test_validate_config_rejects_unknown_nested_keys() -> None:
    raw = valid_config()
    raw["scope"]["approved_domain"] = ["example.invalid"]

    with pytest.raises(ConfigError, match="Unknown scope keys"):
        validate_config(raw)
