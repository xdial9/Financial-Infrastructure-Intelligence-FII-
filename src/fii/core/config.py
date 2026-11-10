"""Strict loading and validation for an FII engagement profile."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from fii.core.scope import normalize_seed_domains

_ALLOWED_SOURCE_CLASSES = {
    "public_api",
    "public_dataset",
    "targeted_public_web",
    "customer_supplied",
}
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class FIIConfigError(ValueError):
    """Raised when an engagement profile is missing, unsafe or malformed."""


@dataclass(frozen=True)
class Engagement:
    name: str
    slug: str
    organization: str
    authorization_reference: str


@dataclass(frozen=True)
class Scope:
    seed_domains: tuple[str, ...]
    approved_organizations: tuple[str, ...]
    permitted_source_classes: tuple[str, ...]
    allow_active_validation: bool


@dataclass(frozen=True)
class Collection:
    sequential: bool
    request_timeout_seconds: int
    max_retries: int
    retry_backoff_seconds: int
    user_agent: str


@dataclass(frozen=True)
class SourceSetting:
    source_id: str
    enabled: bool
    required: bool


@dataclass(frozen=True)
class EngagementConfig:
    config_path: Path
    engagement: Engagement
    scope: Scope
    collection: Collection
    sources: tuple[SourceSetting, ...]

    @property
    def fingerprint(self) -> str:
        payload = {
            "engagement": asdict(self.engagement),
            "scope": asdict(self.scope),
            "collection": asdict(self.collection),
            "sources": [asdict(item) for item in self.sources],
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))
        return digest.hexdigest()

    @property
    def enabled_sources(self) -> tuple[SourceSetting, ...]:
        return tuple(source for source in self.sources if source.enabled)


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FIIConfigError(f"{name} must be a YAML mapping")
    return value


def _text(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FIIConfigError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, label: str, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise FIIConfigError(f"{label} must be a list")
    if not allow_empty and not value:
        raise FIIConfigError(f"{label} must not be empty")
    result = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise FIIConfigError(f"Every {label} entry must be a non-empty string")
        item = entry.strip()
        if item not in result:
            result.append(item)
    return tuple(result)


def load_config(path: str | Path) -> EngagementConfig:
    config_path = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FIIConfigError(f"Engagement configuration not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise FIIConfigError(f"Invalid YAML in {config_path}: {exc}") from exc

    root = _mapping(raw, "configuration")
    engagement_data = _mapping(root.get("engagement"), "engagement")
    scope_data = _mapping(root.get("scope"), "scope")
    collection_data = _mapping(root.get("collection", {}), "collection")
    sources_data = _mapping(root.get("sources"), "sources")

    name = _text(engagement_data, "name", "engagement")
    slug = _text(engagement_data, "slug", "engagement")
    organization = _text(engagement_data, "organization", "engagement")
    authorization_reference = _text(engagement_data, "authorization_reference", "engagement")
    if not _SLUG.fullmatch(slug):
        raise FIIConfigError("engagement.slug must be lowercase letters/numbers separated by single hyphens")

    try:
        seed_domains = normalize_seed_domains(scope_data.get("seed_domains"))
    except ValueError as exc:
        raise FIIConfigError(str(exc)) from exc
    approved_organizations = _string_list(
        scope_data.get("approved_organizations", [organization]),
        "scope.approved_organizations",
    )
    permitted_classes = _string_list(
        scope_data.get("permitted_source_classes", ["public_api", "public_dataset"]),
        "scope.permitted_source_classes",
        allow_empty=False,
    )
    unsupported_classes = sorted(set(permitted_classes) - _ALLOWED_SOURCE_CLASSES)
    if unsupported_classes:
        raise FIIConfigError(f"Unsupported source class(es): {', '.join(unsupported_classes)}")

    allow_active = scope_data.get("allow_active_validation", False)
    if not isinstance(allow_active, bool):
        raise FIIConfigError("scope.allow_active_validation must be true or false")
    if allow_active:
        raise FIIConfigError("Active validation is not implemented and must remain disabled in this release")

    sequential = collection_data.get("sequential", True)
    if sequential is not True:
        raise FIIConfigError("collection.sequential must be true in the initial release")
    timeout = collection_data.get("request_timeout_seconds", 20)
    retries = collection_data.get("max_retries", 3)
    backoff = collection_data.get("retry_backoff_seconds", 2)
    user_agent = collection_data.get("user_agent", "FII-Research/0.1")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 120:
        raise FIIConfigError("collection.request_timeout_seconds must be an integer from 1 to 120")
    if not isinstance(retries, int) or isinstance(retries, bool) or not 0 <= retries <= 5:
        raise FIIConfigError("collection.max_retries must be an integer from 0 to 5")
    if not isinstance(backoff, int) or isinstance(backoff, bool) or not 0 <= backoff <= 30:
        raise FIIConfigError("collection.retry_backoff_seconds must be an integer from 0 to 30")
    if not isinstance(user_agent, str) or not user_agent.strip():
        raise FIIConfigError("collection.user_agent must be a non-empty string")

    source_settings = []
    for source_id, setting in sources_data.items():
        if not isinstance(source_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", source_id):
            raise FIIConfigError(f"Invalid source identifier: {source_id!r}")
        source_data = _mapping(setting, f"sources.{source_id}")
        enabled = source_data.get("enabled", False)
        required = source_data.get("required", False)
        if not isinstance(enabled, bool) or not isinstance(required, bool):
            raise FIIConfigError(f"sources.{source_id}.enabled and required must be booleans")
        if required and not enabled:
            raise FIIConfigError(f"Required source {source_id!r} cannot be disabled")
        source_settings.append(SourceSetting(source_id, enabled, required))
    if not source_settings or not any(item.enabled for item in source_settings):
        raise FIIConfigError("At least one source must be configured and enabled")

    return EngagementConfig(
        config_path=config_path,
        engagement=Engagement(name, slug, organization, authorization_reference),
        scope=Scope(seed_domains, approved_organizations, permitted_classes, allow_active),
        collection=Collection(True, timeout, retries, backoff, user_agent.strip()),
        sources=tuple(source_settings),
    )
