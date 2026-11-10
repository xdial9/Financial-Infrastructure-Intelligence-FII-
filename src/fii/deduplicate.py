"""Deduplicate repeated relationships without discarding source evidence."""

from __future__ import annotations


def deduplicate_observations(observations: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for item in observations:
        key = (
            item["subject_type"], item["subject_value"], item["predicate"],
            item["object_type"], item["object_value"],
        )
        groups.setdefault(key, []).append(item)

    result = []
    for key, evidence in sorted(groups.items(), key=lambda pair: pair[0]):
        independent_sources = sorted({item["source_id"] for item in evidence})
        confidence_rank = {"low": 0, "medium": 1, "high": 2}
        best_confidence = max((item["confidence"] for item in evidence), key=confidence_rank.get)
        statuses = {item["verification_status"] for item in evidence}
        if len(independent_sources) > 1 and statuses.issubset({"observed", "corroborated"}):
            verification_status = "corroborated"
        elif "inferred" in statuses:
            verification_status = "inferred"
        elif "unverified" in statuses:
            verification_status = "unverified"
        else:
            verification_status = "observed"

        first = evidence[0]
        result.append({
            "observation_id": first["observation_id"],
            "subject_type": key[0],
            "subject_value": key[1],
            "predicate": key[2],
            "object_type": key[3],
            "object_value": key[4],
            "confidence": best_confidence,
            "verification_status": verification_status,
            "evidence_count": len(evidence),
            "independent_source_count": len(independent_sources),
            "evidence": [
                {
                    "source_id": item["source_id"],
                    "source_name": item["source_name"],
                    "source_url": item["source_url"],
                    "observed_at": item["observed_at"],
                    "method": item["method"],
                    "confidence": item["confidence"],
                    "verification_status": item["verification_status"],
                    "raw_record_id": item["raw_record_id"],
                }
                for item in sorted(evidence, key=lambda entry: (entry["source_id"], entry["observed_at"]))
            ],
        })
    return result
