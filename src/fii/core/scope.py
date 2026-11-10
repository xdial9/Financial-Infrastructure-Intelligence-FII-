"""Engagement scope normalization and validation."""

from __future__ import annotations

import ipaddress
import re
from typing import Any


DOMAIN_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class ScopeError(ValueError):
    """Raised when a scope identifier is malformed or unsupported."""


def normalize_domain(value: str) -> str:
    """Normalize a DNS name to lowercase IDNA ASCII without URL components."""
    if not isinstance(value, str) or not value.strip():
        raise ScopeError("Domain must be a non-empty string.")

    domain = value.strip()
    if any(token in domain for token in ("://", "/", "?", "#", "@")):
        raise ScopeError(f"Enter a hostname only, without a scheme or path: {value!r}")

    domain = domain.rstrip(".")
    try:
        domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ScopeError(f"Domain cannot be converted to IDNA ASCII: {value!r}") from exc

    if len(domain) > 253:
        raise ScopeError("Domain exceeds the maximum DNS name length.")

    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ScopeError("IP addresses are not accepted in seed_domains; provide DNS names.")

    labels = domain.split(".")
    if len(labels) < 2 or any(not DOMAIN_LABEL_RE.fullmatch(label) for label in labels):
        raise ScopeError(f"Invalid DNS hostname: {value!r}")

    return domain


def validate_scope(scope: dict[str, Any]) -> dict[str, Any]:
    """Validate the normalized scope mapping returned by configuration loading."""
    if not isinstance(scope, dict):
        raise ScopeError("Scope must be a mapping.")

    domains = scope.get("seed_domains", [])
    organizations = scope.get("approved_organizations", [])
    if not isinstance(domains, list) or not all(isinstance(item, str) for item in domains):
        raise ScopeError("scope.seed_domains must be a list of normalized hostnames.")
    if not isinstance(organizations, list) or not all(
        isinstance(item, str) and item.strip() for item in organizations
    ):
        raise ScopeError("scope.approved_organizations must be a list of non-empty names.")

    for domain in domains:
        if normalize_domain(domain) != domain:
            raise ScopeError(f"Seed domain is not normalized: {domain!r}")

    if not domains and not organizations:
        raise ScopeError("Scope must contain at least one seed domain or organization.")

    return scope
