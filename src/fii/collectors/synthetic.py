"""Deterministic offline fixture collector used for development and first-run testing."""

from __future__ import annotations

import json
from pathlib import Path

from fii.scope import validate_record_scope


def collect(fixture_path: Path, approved_domains: tuple[str, ...]) -> list[dict]:
    if not fixture_path.is_file():
        raise FileNotFoundError(f"Synthetic fixture not found: {fixture_path}")
    try:
        records = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid synthetic fixture JSON: {exc}") from exc
    if not isinstance(records, list):
        raise ValueError("Synthetic fixture must contain a JSON list of evidence records")
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Each synthetic evidence record must be a JSON object")
        validate_record_scope(record, approved_domains)
    return records
