"""Engagement configuration loading and validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fii.scope import normalize_domain, validate_domain


@dataclass(frozen=True)
class EngagementConfig:
    engagement_name: str
    organization: str
    approved_domains: tuple[str, ...]
    approved_sources: tuple[str, ...]
    authorization_reference: str
    output_dir: Path
    fixture_path: Path

    @property
    def fingerprint(self) -> str:
        payload = {
            "engagement_name": self.engagement_name,
            "organization": self.organization,
            "approved_domains": list(self.approved_domains),
            "approved_sources": list(self.approved_sources),
            "authorization_reference": self.authorization_reference,
            "fixture_path": str(self.fixture_path.resolve()),
        }
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def load_config(path: str | Path) -> EngagementConfig:
    config_path = Path(path).expanduser().resolve()
    try:
        raw: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Configuration file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {config_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ValueError("Engagement profile must be a JSON object")

    required = ("engagement_name", "organization", "approved_domains", "approved_sources", "authorization_reference")
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ValueError(f"Missing required configuration values: {', '.join(missing)}")

    if not isinstance(raw["approved_domains"], list) or not raw["approved_domains"]:
        raise ValueError("approved_domains must be a non-empty list")
    if not isinstance(raw["approved_sources"], list) or not raw["approved_sources"]:
        raise ValueError("approved_sources must be a non-empty list")

    domains: list[str] = []
    for value in raw["approved_domains"]:
        domain = normalize_domain(str(value))
        validate_domain(domain)
        if domain not in domains:
            domains.append(domain)

    if any(source != "synthetic_fixture" for source in raw["approved_sources"]):
        raise ValueError(
            "This build only implements synthetic_fixture. Remove unimplemented sources "
            "from the profile until their collector is added and documented."
        )

    output_dir = Path(raw.get("output_dir", "./results")).expanduser()
    if not output_dir.is_absolute():
        output_dir = (config_path.parent / output_dir).resolve()

    fixture_value = raw.get("fixture_path", "synthetic_records.json")
    fixture_path = Path(fixture_value).expanduser()
    if not fixture_path.is_absolute():
        fixture_path = (config_path.parent / fixture_path).resolve()

    return EngagementConfig(
        engagement_name=str(raw["engagement_name"]).strip(),
        organization=str(raw["organization"]).strip(),
        approved_domains=tuple(domains),
        approved_sources=tuple(str(item) for item in raw["approved_sources"]),
        authorization_reference=str(raw["authorization_reference"]).strip(),
        output_dir=output_dir,
        fixture_path=fixture_path,
    )
