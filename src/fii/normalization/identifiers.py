"""Canonical entity and identifier registries for FII Block 08."""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType

from fii.core.scope import ScopeError, normalize_domain

REGISTRY_VERSION = "entity-registry-v1"


@dataclass(frozen=True)
class EntityTypeDefinition:
    """Supported canonical entity type."""

    entity_type: str
    description: str


@dataclass(frozen=True)
class IdentifierTypeDefinition:
    """Normalization and resolution policy for one identifier family."""

    identifier_type: str
    entity_type: str
    description: str
    normalization_rule: str
    resolution_strength: str


@dataclass(frozen=True)
class NormalizedIdentifier:
    """Validated identifier with an explicit target entity type."""

    identifier_type: str
    entity_type: str
    identifier_value: str
    resolution_strength: str


ENTITY_TYPE_DEFINITIONS = MappingProxyType(
    {
        item.entity_type: item
        for item in (
            EntityTypeDefinition("organization", "A registered legal organization or institution."),
            EntityTypeDefinition("vendor", "A technology provider, service vendor or brand."),
            EntityTypeDefinition("domain", "A registered DNS domain."),
            EntityTypeDefinition("hostname", "A hostname or nameserver within a DNS namespace."),
            EntityTypeDefinition("ip_address", "An IPv4 or IPv6 address."),
            EntityTypeDefinition("autonomous_system", "An Internet autonomous system number."),
            EntityTypeDefinition(
                "certificate",
                "A cryptographic certificate identified by digest.",
            ),
            EntityTypeDefinition("application", "A software application or package."),
            EntityTypeDefinition("api_endpoint", "A documented public API endpoint or route."),
            EntityTypeDefinition(
                "documentation_resource",
                "A public API, developer or product documentation resource.",
            ),
        )
    }
)

IDENTIFIER_TYPE_DEFINITIONS = MappingProxyType(
    {
        item.identifier_type: item
        for item in (
            IdentifierTypeDefinition(
                "lei", "organization", "Legal Entity Identifier.",
                "iso17442_lei", "strong"
            ),
            IdentifierTypeDefinition(
                "sec_cik", "organization", "US SEC Central Index Key.",
                "sec_cik_10_digit", "strong"
            ),
            IdentifierTypeDefinition(
                "companies_house_number", "organization", "UK Companies House company number.",
                "companies_house", "strong"
            ),
            IdentifierTypeDefinition(
                "legal_name", "organization", "Source-reported legal name.",
                "unicode_name_casefold", "weak"
            ),
            IdentifierTypeDefinition(
                "brand_name", "vendor", "Vendor or product brand name.",
                "unicode_name_casefold", "weak"
            ),
            IdentifierTypeDefinition(
                "domain", "domain", "DNS registered domain name.",
                "idna_domain", "strong"
            ),
            IdentifierTypeDefinition(
                "hostname", "hostname", "DNS hostname or nameserver.",
                "idna_hostname", "strong"
            ),
            IdentifierTypeDefinition(
                "ip_address", "ip_address", "IP address.",
                "ipaddress", "strong"
            ),
            IdentifierTypeDefinition(
                "asn", "autonomous_system", "Autonomous system number.",
                "asn_integer", "strong"
            ),
            IdentifierTypeDefinition(
                "certificate_sha256", "certificate", "SHA-256 certificate fingerprint.",
                "sha256_hex", "strong"
            ),
            IdentifierTypeDefinition(
                "package_id", "application", "Ecosystem-scoped package identifier.",
                "namespaced_text", "weak"
            ),
        )
    }
)


def normalize_name(value: str) -> str:
    """Normalize a name conservatively for comparison, not for display."""
    if not isinstance(value, str):
        raise ValueError("Entity names must be strings.")
    normalized = unicodedata.normalize("NFKC", value)
    normalized = " ".join(normalized.split()).casefold()
    if not normalized:
        raise ValueError("Entity names cannot be empty.")
    if len(normalized) > 512:
        raise ValueError("Entity names cannot exceed 512 characters.")
    return normalized


def _normalize_identifier_value(rule: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Identifier values must be non-empty strings.")
    raw = value.strip()

    if rule == "iso17442_lei":
        normalized = raw.upper()
        if not re.fullmatch(r"[A-Z0-9]{20}", normalized):
            raise ValueError("LEIs must contain exactly 20 uppercase alphanumeric characters.")
        return normalized

    if rule == "sec_cik_10_digit":
        if not re.fullmatch(r"[0-9]{1,10}", raw):
            raise ValueError("SEC CIK identifiers must contain between 1 and 10 digits.")
        return raw.zfill(10)

    if rule == "companies_house":
        normalized = raw.upper()
        if not re.fullmatch(r"[A-Z0-9]{1,8}", normalized):
            raise ValueError("Companies House numbers must contain 1 to 8 letters or digits.")
        return normalized

    if rule in {"idna_domain", "idna_hostname"}:
        try:
            return normalize_domain(raw)
        except ScopeError as exc:
            raise ValueError("Identifier must be a valid DNS name.") from exc

    if rule == "ipaddress":
        try:
            return ipaddress.ip_address(raw).compressed
        except ValueError as exc:
            raise ValueError("Identifier must be a valid IPv4 or IPv6 address.") from exc

    if rule == "asn_integer":
        match = re.fullmatch(r"(?:AS)?([0-9]{1,10})", raw, re.IGNORECASE)
        if match is None:
            raise ValueError("ASN identifiers must be an integer with an optional AS prefix.")
        number = int(match.group(1))
        if number > 4_294_967_295:
            raise ValueError("ASN identifier exceeds the 32-bit autonomous-system range.")
        return f"AS{number}"

    if rule == "sha256_hex":
        normalized = raw.lower()
        if not re.fullmatch(r"[0-9a-f]{64}", normalized):
            raise ValueError("SHA-256 identifiers must contain 64 hexadecimal characters.")
        return normalized

    if rule == "unicode_name_casefold":
        return normalize_name(raw)

    if rule == "namespaced_text":
        normalized = unicodedata.normalize("NFKC", raw)
        normalized = " ".join(normalized.split()).casefold()
        if ":" not in normalized or normalized.startswith(":") or normalized.endswith(":"):
            raise ValueError("Package identifiers must include an ecosystem namespace.")
        return normalized

    raise ValueError(f"Unsupported identifier normalization rule: {rule}")


def normalize_identifier(
    identifier_type: str,
    value: str,
    *,
    entity_type: str | None = None,
) -> NormalizedIdentifier:
    """Validate and normalize an identifier using the fixed registry."""
    definition = IDENTIFIER_TYPE_DEFINITIONS.get(identifier_type)
    if definition is None:
        raise ValueError(f"Unregistered identifier type: {identifier_type!r}")
    if entity_type is not None and entity_type != definition.entity_type:
        raise ValueError(
            f"Identifier type {identifier_type!r} belongs to entity type "
            f"{definition.entity_type!r}, not {entity_type!r}."
        )
    return NormalizedIdentifier(
        identifier_type=definition.identifier_type,
        entity_type=definition.entity_type,
        identifier_value=_normalize_identifier_value(definition.normalization_rule, value),
        resolution_strength=definition.resolution_strength,
    )
