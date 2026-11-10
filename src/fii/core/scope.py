"""Domain and engagement-scope normalization helpers."""

from __future__ import annotations

import ipaddress
import re

_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalize_domain(value: str) -> str:
    """Return a lower-case IDNA hostname without a trailing dot."""
    raw = value.strip()
    if not raw or "://" in raw or "/" in raw or "*" in raw or "@" in raw:
        raise ValueError(f"Invalid seed domain: {value!r}")
    if ":" in raw or raw.startswith("["):
        raise ValueError(f"Seed domains must be hostnames, not IP addresses or host:port values: {value!r}")
    try:
        normalized = raw.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError(f"Invalid internationalized domain name: {value!r}") from exc
    if len(normalized) > 253:
        raise ValueError(f"Seed domain is too long: {value!r}")
    labels = normalized.split(".")
    if len(labels) < 2 or any(not _LABEL.fullmatch(label) for label in labels):
        raise ValueError(f"Invalid seed domain: {value!r}")
    return normalized


def host_in_scope(host: str, seed_domains: tuple[str, ...]) -> bool:
    """Match exact domains and subdomains on label boundaries only."""
    try:
        candidate = normalize_domain(host)
    except ValueError:
        return False
    return any(candidate == domain or candidate.endswith(f".{domain}") for domain in seed_domains)


def normalize_seed_domains(values: list[str]) -> tuple[str, ...]:
    if not isinstance(values, list) or not values:
        raise ValueError("scope.seed_domains must be a non-empty list")
    normalized = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Every scope.seed_domains entry must be a string")
        domain = normalize_domain(value)
        if domain not in normalized:
            normalized.append(domain)
    return tuple(normalized)


def validate_ip_address(value: str) -> str:
    """Canonicalize an IP address for later scope extensions."""
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as exc:
        raise ValueError(f"Invalid IP address: {value!r}") from exc
