"""Scope validation helpers. MVP collectors are passive and fixture-only."""

from __future__ import annotations

import re

_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_domain(value: str) -> str:
    return value.strip().lower().rstrip(".")


def validate_domain(domain: str) -> None:
    if not domain or len(domain) > 253 or "://" in domain or "/" in domain or "*" in domain:
        raise ValueError(f"Invalid domain in approved scope: {domain!r}")
    labels = domain.split(".")
    if len(labels) < 2 or any(not _LABEL.fullmatch(label) for label in labels):
        raise ValueError(f"Invalid domain in approved scope: {domain!r}")


def host_in_scope(host: str, approved_domains: tuple[str, ...]) -> bool:
    candidate = normalize_domain(host)
    return any(candidate == domain or candidate.endswith("." + domain) for domain in approved_domains)


def validate_record_scope(record: dict, approved_domains: tuple[str, ...]) -> None:
    """Ensure infrastructure subjects and in-scope domain objects respect the allowlist."""
    subject_type = record.get("subject_type")
    subject_value = str(record.get("subject_value", ""))
    object_type = record.get("object_type")
    object_value = str(record.get("object_value", ""))

    if subject_type in {"domain", "hostname"} and not host_in_scope(subject_value, approved_domains):
        raise ValueError(f"Out-of-scope subject rejected: {subject_value}")
    if object_type in {"domain", "hostname"} and not host_in_scope(object_value, approved_domains):
        raise ValueError(f"Out-of-scope infrastructure object rejected: {object_value}")
