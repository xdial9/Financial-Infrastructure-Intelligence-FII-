"""Generate analyst-friendly files from the canonical evidence records."""

from __future__ import annotations

import csv
import json
from pathlib import Path


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def generate_reports(run_dir: Path, config, entities: list[dict], relationships: list[dict], findings: list[dict], observations: list[dict]) -> list[str]:
    reports = run_dir / "reports"
    assets = [item for item in entities if item["entity_type"] in {"domain", "hostname", "ip", "asn", "application"}]
    write_csv(reports / "asset-inventory.csv", assets, ["entity_id", "entity_type", "canonical_value"])
    write_csv(
        reports / "relationships.csv", relationships,
        ["relationship_id", "subject_entity_id", "predicate", "object_entity_id", "evidence_count", "independent_source_count", "confidence", "verification_status", "analyst_review_required"],
    )
    write_csv(
        reports / "analyst-review.csv", [row for row in findings if row["analyst_review_required"]],
        ["finding_id", "title", "summary", "priority", "confidence", "verification_status", "relationship_id", "evidence_count", "independent_source_count"],
    )
    source_ids = sorted({item["source_id"] for item in observations})
    source_rows = [{"source_id": source_id, "record_count": sum(1 for item in observations if item["source_id"] == source_id)} for source_id in source_ids]
    write_csv(reports / "source-register.csv", source_rows, ["source_id", "record_count"])

    corroborated = sum(1 for item in relationships if item["verification_status"] == "corroborated")
    review_count = sum(1 for item in findings if item["analyst_review_required"])
    summary = f"""# FII Executive Summary — {config.engagement_name}

**Organization:** {config.organization}  
**Run mode:** synthetic fixture only  
**Authorization / reference:** {config.authorization_reference}  
**Approved domains:** {', '.join(config.approved_domains)}

## Results

- Raw evidence records: {len(observations)}
- Canonical entities: {len(entities)}
- Evidence-backed relationships: {len(relationships)}
- Corroborated relationships: {corroborated}
- Analyst review items: {review_count}

## Interpretation

This run uses deterministic synthetic records and makes no network requests. Relationships are limited to the source evidence represented in the fixture. A documented or corroborated vendor relationship does not establish a vulnerability, exploitable condition, internal trust path, or payment workflow.

## Collection limitations

- No live external sources were queried.
- No active scanning, authentication, or interaction with financial systems occurred.
- Results are a pipeline demonstration, not an assessment of a real institution.

## Output files

- `asset-inventory.csv`
- `relationships.csv`
- `analyst-review.csv`
- `source-register.csv`
- `../analysis/entities.json`
- `../analysis/relationships.json`
- `../analysis/findings.json`
- `../normalized/observations.jsonl`
- `../normalized/deduplicated-observations.json`
"""
    (reports / "executive-summary.md").write_text(summary, encoding="utf-8")
    return [
        "reports/asset-inventory.csv", "reports/relationships.csv", "reports/analyst-review.csv",
        "reports/source-register.csv", "reports/executive-summary.md",
    ]
