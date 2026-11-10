"""Engagement configuration loading and validation."""

from __future__ import annotations

import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from fii.core.scope import normalize_domain, validate_scope


class ConfigError(ValueError):
    """Raised when an engagement configuration is missing or invalid."""


DEFAULTS: dict[str, Any] = {
    "workspace": "~/FII-Workspace",
    "engagement": {
        "name": "",
        "slug": "",
        "organization": "",
        "authorization_reference": "",
    },
    "scope": {
        "seed_domains": [],
        "approved_organizations": [],
        "permitted_source_classes": ["public_api", "public_dataset"],
        "allow_active_validation": False,
    },
    "collection": {
        "sequential": True,
        "request_timeout_seconds": 20,
        "max_retries": 3,
        "retry_backoff_seconds": 2.0,
        "user_agent": "FII-Research/0.1",
    },
    "sources": {},
}

ALLOWED_TOP_LEVEL = {"workspace", "engagement", "scope", "collection", "sources"}
ALLOWED_ENGAGEMENT_KEYS = {"name", "slug", "organization", "authorization_reference"}
ALLOWED_SCOPE_KEYS = {
    "seed_domains",
    "approved_organizations",
    "permitted_source_classes",
    "allow_active_validation",
}
ALLOWED_COLLECTION_KEYS = {
    "sequential",
    "request_timeout_seconds",
    "max_retries",
    "retry_backoff_seconds",
    "user_agent",
}
ALLOWED_SOURCE_CLASSES = {
    "public_api",
    "public_dataset",
    "targeted_public_web",
    "customer_supplied",
}
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _merge(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Merge nested configuration mappings without mutating defaults."""
    merged = deepcopy(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"Configuration '{name}' must be a mapping.")
    return value


def _validate_string_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list):
        raise ConfigError(f"Configuration '{name}' must be a list.")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"Every item in '{name}' must be a non-empty string.")
        normalized = item.strip()
        if normalized not in result:
            result.append(normalized)
    return result


def validate_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply defaults and return a validated, normalized configuration."""
    if not isinstance(raw, dict):
        raise ConfigError("Configuration root must be a mapping.")

    unknown = sorted(set(raw) - ALLOWED_TOP_LEVEL)
    if unknown:
        raise ConfigError(f"Unknown top-level configuration keys: {', '.join(unknown)}")

    config = _merge(DEFAULTS, raw)

    workspace = config.get("workspace")
    if "workspace" not in raw:
        workspace = os.environ.get("FII_WORKSPACE", workspace)
    if not isinstance(workspace, str) or not workspace.strip():
        raise ConfigError("'workspace' must be a non-empty path string.")
    config["workspace"] = str(Path(workspace).expanduser())

    engagement = _require_mapping(config.get("engagement"), "engagement")
    unknown_engagement = sorted(set(engagement) - ALLOWED_ENGAGEMENT_KEYS)
    if unknown_engagement:
        raise ConfigError(
            "Unknown engagement keys: " + ", ".join(unknown_engagement)
        )
    name = engagement.get("name")
    slug = engagement.get("slug")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError("'engagement.name' is required.")
    if not isinstance(slug, str) or not SLUG_RE.fullmatch(slug):
        raise ConfigError(
            "'engagement.slug' must be lowercase letters, numbers and hyphens, "
            "with an alphanumeric first and last character."
        )
    engagement["name"] = name.strip()
    engagement["slug"] = slug
    for optional_key in ("organization", "authorization_reference"):
        value = engagement.get(optional_key, "")
        if not isinstance(value, str):
            raise ConfigError(f"'engagement.{optional_key}' must be a string.")
        engagement[optional_key] = value.strip()
    config["engagement"] = engagement

    scope = _require_mapping(config.get("scope"), "scope")
    unknown_scope = sorted(set(scope) - ALLOWED_SCOPE_KEYS)
    if unknown_scope:
        raise ConfigError("Unknown scope keys: " + ", ".join(unknown_scope))
    seed_domains = _validate_string_list(scope.get("seed_domains", []), "scope.seed_domains")
    normalized_domains = []
    for domain in seed_domains:
        normalized = normalize_domain(domain)
        if normalized not in normalized_domains:
            normalized_domains.append(normalized)

    approved_organizations = _validate_string_list(
        scope.get("approved_organizations", []),
        "scope.approved_organizations",
    )
    if not normalized_domains and not approved_organizations:
        raise ConfigError(
            "Scope requires at least one seed domain or approved organization."
        )

    source_classes = _validate_string_list(
        scope.get("permitted_source_classes", []),
        "scope.permitted_source_classes",
    )
    if not source_classes:
        raise ConfigError("scope.permitted_source_classes must contain at least one class.")
    invalid_classes = sorted(set(source_classes) - ALLOWED_SOURCE_CLASSES)
    if invalid_classes:
        raise ConfigError(
            "Unsupported permitted source classes: " + ", ".join(invalid_classes)
        )

    active_validation = scope.get("allow_active_validation", False)
    if not isinstance(active_validation, bool):
        raise ConfigError("'scope.allow_active_validation' must be true or false.")
    if active_validation:
        raise ConfigError(
            "Active validation is not implemented in this release. "
            "Set scope.allow_active_validation to false."
        )

    scope["seed_domains"] = normalized_domains
    scope["approved_organizations"] = approved_organizations
    scope["permitted_source_classes"] = source_classes
    scope["allow_active_validation"] = False
    config["scope"] = scope
    validate_scope(scope)

    collection = _require_mapping(config.get("collection"), "collection")
    unknown_collection = sorted(set(collection) - ALLOWED_COLLECTION_KEYS)
    if unknown_collection:
        raise ConfigError(
            "Unknown collection keys: " + ", ".join(unknown_collection)
        )
    sequential = collection.get("sequential", True)
    if sequential is not True:
        raise ConfigError("The initial FII workflow requires collection.sequential: true.")

    timeout = collection.get("request_timeout_seconds", 20)
    retries = collection.get("max_retries", 3)
    backoff = collection.get("retry_backoff_seconds", 2.0)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 120:
        raise ConfigError("'collection.request_timeout_seconds' must be an integer from 1 to 120.")
    if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 5:
        raise ConfigError("'collection.max_retries' must be an integer from 0 to 5.")
    if (
        isinstance(backoff, bool)
        or not isinstance(backoff, (int, float))
        or not 0 < backoff <= 60
    ):
        raise ConfigError(
            "'collection.retry_backoff_seconds' must be greater than 0 and at most 60."
        )
    user_agent = collection.get("user_agent", "")
    if not isinstance(user_agent, str) or not user_agent.strip():
        raise ConfigError("'collection.user_agent' must be a non-empty string.")
    collection["sequential"] = True
    collection["request_timeout_seconds"] = timeout
    collection["max_retries"] = retries
    collection["retry_backoff_seconds"] = float(backoff)
    collection["user_agent"] = user_agent.strip()
    config["collection"] = collection

    sources = _require_mapping(config.get("sources"), "sources")
    for source_id, settings in sources.items():
        source_settings = _require_mapping(settings, f"sources.{source_id}")
        for flag in ("enabled", "required"):
            if flag in source_settings and not isinstance(source_settings[flag], bool):
                raise ConfigError(f"'sources.{source_id}.{flag}' must be true or false.")
    config["sources"] = sources

    return config


def load_config(path: str | Path) -> dict[str, Any]:
    """Read YAML, validate its shape, apply defaults and normalize the scope."""
    config_path = Path(path).expanduser()
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ConfigError(f"Cannot read configuration {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {config_path}: {exc}") from exc

    if not isinstance(loaded, dict):
        raise ConfigError(f"Configuration root in {config_path} must be a mapping.")
    return validate_config(loaded)
