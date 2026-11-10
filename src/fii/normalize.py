"""Convert source records into canonical, stable observations."""

from __future__ import annotations

import hashlib
import json

from fii.models import observation_from_raw
from fii.scope import normalize_domain


def _canonical_value(entity_type: str, value: str) -> str:
    return normalize_domain(value) if entity_type in {"domain", "hostname"} else value.strip()


def _stable_id(record: dict) -> str:
    identity = {
        "subject_type": record["subject_type"],
        "subject_value": _canonical_value(record["subject_type"], str(record["subject_value"])),
        "predicate": record["predicate"],
        "object_type": record["object_type"],
        "object_value": _canonical_value(record["object_type"], str(record["object_value"])),
    }
    raw = json.dumps(identity, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


def normalize_records(records: list[dict]) -> list[dict]:
    observations = []
    for record in records:
        normalized = dict(record)
        normalized["subject_value"] = _canonical_value(record["subject_type"], str(record["subject_value"]))
        normalized["object_value"] = _canonical_value(record["object_type"], str(record["object_value"]))
        observations.append(observation_from_raw(normalized, _stable_id(normalized)).to_dict())
    return observations
