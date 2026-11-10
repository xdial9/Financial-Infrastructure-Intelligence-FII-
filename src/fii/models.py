"""Canonical observation model used across collectors and analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Observation:
    observation_id: str
    source_id: str
    source_name: str
    observed_at: str
    subject_type: str
    subject_value: str
    predicate: str
    object_type: str
    object_value: str
    source_url: str
    method: str
    confidence: str
    verification_status: str
    raw_record_id: str

    def to_dict(self) -> dict:
        return asdict(self)


def observation_from_raw(record: dict, observation_id: str) -> Observation:
    required = (
        "source_id", "source_name", "observed_at", "subject_type", "subject_value",
        "predicate", "object_type", "object_value", "source_url", "method",
        "confidence", "verification_status", "record_id",
    )
    missing = [key for key in required if not record.get(key)]
    if missing:
        raise ValueError(f"Synthetic record missing required values: {', '.join(missing)}")
    if record["confidence"] not in {"low", "medium", "high"}:
        raise ValueError(f"Unsupported confidence value: {record['confidence']}")
    if record["verification_status"] not in {"observed", "corroborated", "inferred", "unverified"}:
        raise ValueError(f"Unsupported verification status: {record['verification_status']}")
    return Observation(
        observation_id=observation_id,
        source_id=str(record["source_id"]),
        source_name=str(record["source_name"]),
        observed_at=str(record["observed_at"]),
        subject_type=str(record["subject_type"]),
        subject_value=str(record["subject_value"]),
        predicate=str(record["predicate"]),
        object_type=str(record["object_type"]),
        object_value=str(record["object_value"]),
        source_url=str(record["source_url"]),
        method=str(record["method"]),
        confidence=str(record["confidence"]),
        verification_status=str(record["verification_status"]),
        raw_record_id=str(record["record_id"]),
    )
