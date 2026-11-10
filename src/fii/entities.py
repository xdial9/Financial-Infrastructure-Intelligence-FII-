"""Build stable entities and evidence-linked relationship records."""

from __future__ import annotations

import hashlib


def _entity_id(entity_type: str, value: str) -> str:
    digest = hashlib.sha256(f"{entity_type}|{value}".encode("utf-8")).hexdigest()[:20]
    return f"ent_{digest}"


def build_entities_and_relationships(deduplicated: list[dict]) -> tuple[list[dict], list[dict]]:
    entities: dict[str, dict] = {}
    relationships = []
    for item in deduplicated:
        endpoints = (
            (item["subject_type"], item["subject_value"]),
            (item["object_type"], item["object_value"]),
        )
        endpoint_ids = []
        for entity_type, value in endpoints:
            entity_id = _entity_id(entity_type, value)
            endpoint_ids.append(entity_id)
            if entity_id not in entities:
                entities[entity_id] = {
                    "entity_id": entity_id,
                    "entity_type": entity_type,
                    "canonical_value": value,
                }
        relationships.append({
            "relationship_id": f"rel_{item['observation_id']}",
            "subject_entity_id": endpoint_ids[0],
            "predicate": item["predicate"],
            "object_entity_id": endpoint_ids[1],
            "observation_id": item["observation_id"],
            "evidence_count": item["evidence_count"],
            "independent_source_count": item["independent_source_count"],
            "confidence": item["confidence"],
            "verification_status": item["verification_status"],
            "evidence": item["evidence"],
            "analyst_review_required": item["verification_status"] in {"inferred", "unverified"},
        })
    return sorted(entities.values(), key=lambda item: (item["entity_type"], item["canonical_value"])), relationships
