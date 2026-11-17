"""Evidence-linked reports generated from the FII canonical evidence store."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fii.storage.database import PersistenceError, connect_database

REPORT_VERSION = "1.0.0"
REPORT_FILES = (
    "executive-summary.md", "technical-report.md", "asset-inventory.csv",
    "entities.json", "relationships.csv", "observations.jsonl",
    "source-register.csv", "analyst-review.csv", "changes.csv",
    "findings.csv", "report-manifest.json",
)


class ReportError(RuntimeError):
    """Raised when a trustworthy report cannot be published."""


@dataclass(frozen=True)
class ReportResult:
    """Published report directory and artifact digests."""

    directory: Path
    files: tuple[Path, ...]
    sha256: dict[str, str]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stable_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_atomic(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise ReportError(f"Refusing symlinked report artifact: {path}")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except OSError as exc:
        raise ReportError(f"Could not publish report artifact {path.name}.") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _csv_cell(value: Any) -> Any:
    """Neutralize spreadsheet formulas in source-controlled CSV values."""
    if value is None:
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def _csv_bytes(headers: tuple[str, ...], rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_cell(row.get(key)) for key in headers})
    return stream.getvalue().encode("utf-8")


def _object(value: str | None) -> dict[str, Any]:
    try:
        result = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return result if isinstance(result, dict) else {}


def _verify_evidence(
    run_directory: Path, records: list[dict[str, Any]]
) -> list[str]:
    verified: set[tuple[str, str]] = set()
    root = run_directory.resolve(strict=True)
    for record in records:
        relative = record.get("raw_evidence_path")
        expected = record.get("raw_sha256")
        if not relative or not expected:
            continue
        key = (str(relative), str(expected))
        if key in verified:
            continue
        candidate = run_directory / relative
        if candidate.is_symlink():
            raise ReportError(f"Evidence artifact is a symlink: {relative}")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise ReportError(
                f"Referenced evidence is missing or outside this run: {relative}"
            ) from exc
        if not resolved.is_file() or _digest(resolved.read_bytes()) != expected:
            raise ReportError(f"Evidence SHA-256 mismatch or non-file artifact: {relative}")
        verified.add(key)
    return sorted(path for path, _ in verified)


def _run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    try:
        parsed = uuid.UUID(run_id)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ReportError("Run ID must be a UUID.") from exc
    if str(parsed) != run_id.lower():
        raise ReportError("Run ID must use canonical UUID form.")
    row = connection.execute(
        """
        SELECT r.*, e.slug AS engagement_slug, e.display_name AS engagement_name,
               e.organization_name, e.scope_json, e.authorization_reference
        FROM run r JOIN engagement e ON e.engagement_id=r.engagement_id
        WHERE r.run_id=?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        raise ReportError(f"Run not found in evidence database: {run_id}")
    return row


def _observations(connection: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT o.observation_id, o.observation_type, o.observed_value, o.observed_at,
               o.collected_at, o.source_url, o.raw_evidence_path, o.raw_sha256,
               o.verification_state, o.confidence, o.attributes_json, o.deduplication_key,
               o.subject_entity_id, se.source_id, sd.name AS source_name
        FROM observation o
        JOIN source_execution se ON se.source_execution_id=o.source_execution_id
          AND se.run_id=o.run_id
        JOIN source_definition sd ON sd.source_id=se.source_id
        WHERE o.run_id=?
        ORDER BY o.observation_type, o.observed_value, o.observation_id
        """,
        (run_id,),
    ).fetchall()
    return [{**dict(row), "attributes": _object(row["attributes_json"])} for row in rows]


def _provenance(connection: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT p.provenance_id, p.observation_id, p.source_execution_id, p.provenance_role,
               p.source_url, p.raw_evidence_path, p.raw_sha256, p.collected_at, p.observed_at,
               p.attributes_json, se.source_id, sd.name AS source_name
        FROM observation_provenance p
        JOIN source_execution se ON se.source_execution_id=p.source_execution_id
          AND se.run_id=p.run_id
        JOIN source_definition sd ON sd.source_id=se.source_id
        WHERE p.run_id=?
        ORDER BY p.observation_id, se.source_id, p.provenance_id
        """,
        (run_id,),
    ).fetchall()
    return [{**dict(row), "attributes": _object(row["attributes_json"])} for row in rows]


def _entities(connection: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT DISTINCT e.entity_id, e.entity_type, e.canonical_key, e.display_name,
               e.created_at, e.updated_at, e.attributes_json
        FROM entity e
        JOIN entity_resolution_decision d
          ON d.proposed_entity_id=e.entity_id OR d.matched_entity_id=e.entity_id
        WHERE d.run_id=?
        ORDER BY e.entity_type, e.display_name, e.entity_id
        """,
        (run_id,),
    ).fetchall()
    result = []
    for row in rows:
        identifiers = connection.execute(
            """
            SELECT identifier_type, identifier_value, first_seen_at, last_seen_at
            FROM entity_identifier WHERE entity_id=? ORDER BY identifier_type, identifier_value
            """,
            (row["entity_id"],),
        ).fetchall()
        decisions = connection.execute(
            """
            SELECT decision_id, source_observation_id, outcome, match_method,
                   confidence, rationale, created_at
            FROM entity_resolution_decision
            WHERE run_id=? AND (proposed_entity_id=? OR matched_entity_id=?)
            ORDER BY created_at, decision_id
            """,
            (run_id, row["entity_id"], row["entity_id"]),
        ).fetchall()
        result.append(
            {
                **dict(row),
                "attributes": _object(row["attributes_json"]),
                "identifiers": [dict(item) for item in identifiers],
                "resolution_decisions": [dict(item) for item in decisions],
            }
        )
    return result


def _relationships(connection: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT DISTINCT r.relationship_id, r.subject_entity_id, s.display_name AS subject_name,
               r.predicate, r.object_entity_id, o.display_name AS object_name,
               r.verification_state, r.confidence, r.rationale, r.rule_id, r.rule_version,
               r.first_seen_at, r.last_seen_at
        FROM relationship r
        JOIN entity s ON s.entity_id=r.subject_entity_id
        JOIN entity o ON o.entity_id=r.object_entity_id
        JOIN relationship_evidence re ON re.relationship_id=r.relationship_id
        JOIN observation evidence ON evidence.observation_id=re.observation_id
        WHERE evidence.run_id=?
        ORDER BY r.predicate, r.subject_entity_id, r.object_entity_id, r.relationship_id
        """,
        (run_id,),
    ).fetchall()
    result = []
    for row in rows:
        evidence = connection.execute(
            """
            SELECT re.observation_id, re.evidence_role, ob.source_url, ob.observed_at,
                   ob.collected_at, ob.raw_evidence_path, ob.raw_sha256,
                   ob.observation_type, ob.observed_value
            FROM relationship_evidence re
            JOIN observation ob ON ob.observation_id=re.observation_id
            WHERE re.relationship_id=? AND ob.run_id=?
            ORDER BY re.evidence_role, re.observation_id
            """,
            (row["relationship_id"], run_id),
        ).fetchall()
        result.append({**dict(row), "evidence": [dict(item) for item in evidence]})
    return result


def _sources(connection: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT sd.source_id, sd.name, sd.adapter_version, sd.source_class,
               sd.documentation_url, sd.terms_url, sd.requires_credentials, sd.default_enabled,
               se.source_execution_id, se.attempt_number, se.status, se.started_at,
               se.finished_at, se.records_received, se.records_accepted,
               se.raw_manifest_path, se.error_code, se.error_summary
        FROM source_definition sd
        LEFT JOIN source_execution se ON se.source_id=sd.source_id AND se.run_id=?
        ORDER BY sd.source_id, se.attempt_number
        """,
        (run_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _findings(connection: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT finding_id, finding_type, title, description, priority, confidence,
               verification_state, disposition, rationale, created_at, updated_at
        FROM finding WHERE run_id=?
        ORDER BY priority, finding_type, finding_id
        """,
        (run_id,),
    ).fetchall()
    result = []
    for row in rows:
        evidence = connection.execute(
            """
            SELECT observation_id, relationship_id, evidence_role
            FROM finding_evidence WHERE finding_id=? AND run_id=?
            ORDER BY evidence_role, observation_id, relationship_id
            """,
            (row["finding_id"], run_id),
        ).fetchall()
        result.append({**dict(row), "evidence": [dict(item) for item in evidence]})
    return result


def _reviews(connection: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT r.relationship_id, s.display_name AS subject_name, r.predicate,
               o.display_name AS object_name, r.verification_state, r.confidence,
               rr.disposition, rr.reviewer_label, rr.rationale AS review_rationale,
               rr.reviewed_at, r.rationale AS relationship_rationale
        FROM relationship r
        JOIN entity s ON s.entity_id=r.subject_entity_id
        JOIN entity o ON o.entity_id=r.object_entity_id
        JOIN relationship_evidence re ON re.relationship_id=r.relationship_id
        JOIN observation evidence ON evidence.observation_id=re.observation_id
        LEFT JOIN relationship_review rr ON rr.review_id=(
            SELECT rr2.review_id FROM relationship_review rr2
            WHERE rr2.relationship_id=r.relationship_id
            ORDER BY rr2.reviewed_at DESC, rr2.review_id DESC LIMIT 1
        )
        WHERE evidence.run_id=?
        GROUP BY r.relationship_id
        ORDER BY r.first_seen_at, r.relationship_id
        """,
        (run_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _changes(
    connection: sqlite3.Connection, run: sqlite3.Row, run_id: str
) -> tuple[str | None, list[dict[str, Any]]]:
    previous = connection.execute(
        """
        SELECT run_id FROM run
        WHERE engagement_id=? AND run_id<>? AND status IN ('completed','partial')
        ORDER BY started_at DESC, run_id DESC LIMIT 1
        """,
        (run["engagement_id"], run_id),
    ).fetchone()
    if previous is None:
        return None, [{
            "change_type": "baseline_unavailable", "observation_id": "",
            "observation_type": "", "observed_value": "", "source_url": "",
            "previous_run_id": "", "current_run_id": run_id,
            "note": "No prior completed or partial run exists for this engagement.",
        }]
    previous_id = previous["run_id"]
    queries = {}
    for key, current_id in (("current", run_id), ("previous", previous_id)):
        queries[key] = {
            row["deduplication_key"]: dict(row)
            for row in connection.execute(
                """
                SELECT observation_id, observation_type, observed_value, source_url,
                       deduplication_key FROM observation WHERE run_id=?
                """,
                (current_id,),
            ).fetchall()
        }
    rows = []
    for key in sorted(set(queries["current"]) - set(queries["previous"])):
        item = queries["current"][key]
        rows.append({
            "change_type": "added", **item, "previous_run_id": previous_id,
            "current_run_id": run_id,
            "note": "Canonical observation was absent from the immediately preceding baseline run.",
        })
    for key in sorted(set(queries["previous"]) - set(queries["current"])):
        item = queries["previous"][key]
        rows.append({
            "change_type": "not_observed", **item, "previous_run_id": previous_id,
            "current_run_id": run_id,
            "note": "Not present in this run; absence does not prove the external asset was removed.",
        })
    return previous_id, rows


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        status = row["status"] or "not_enabled"
        result[status] = result.get(status, 0) + 1
    return dict(sorted(result.items()))


def _executive_summary(
    run: sqlite3.Row, source_counts: dict[str, int],
    observation_count: int, entity_count: int, relationship_count: int,
    finding_count: int, baseline: str | None,
) -> str:
    source_text = ", ".join(f"{key}: {value}" for key, value in source_counts.items())
    return "\n".join([
        f"# Executive summary — {run['engagement_name']}",
        "",
        f"- **Run:** {run['run_id']}",
        f"- **Status:** {str(run['status']).upper()}",
        f"- **Started:** {run['started_at']}",
        f"- **Finished:** {run['finished_at'] or 'not recorded'}",
        f"- **Seed scope:** {run['scope_json']}",
        f"- **Source executions:** {source_text or 'none'}",
        f"- **Observations:** {observation_count}",
        f"- **Resolved or provisional entities:** {entity_count}",
        f"- **Evidence-backed relationships:** {relationship_count}",
        f"- **Research findings:** {finding_count}",
        f"- **Historical baseline:** {baseline or 'not available'}",
        "",
        "## Interpretation",
        "",
        "This report is an evidence inventory and research aid. Counts are not risk scores. "
        "A source reference, certificate observation, registry record or static API string "
        "does not by itself prove ownership, current reachability, an active integration, "
        "or a security vulnerability.",
        "",
        "## Collection limitations",
        "",
        "- Only sources explicitly enabled in the engagement configuration were executed.",
        "- Per-source results and coverage limitations are listed in source-register.csv.",
        "- Static browser-delivered strings were analyzed without executing JavaScript or invoking routes.",
        "- Nameserver and Certificate Transparency observations are third-party records, not ownership proof.",
        "- Findings remain informational research candidates until independently reviewed.",
        "",
        "## Recommended next steps",
        "",
        "1. Review evidence-backed relationships and candidate findings.",
        "2. Resolve name-only identity candidates with independent authoritative identifiers.",
        "3. Research incomplete or failed sources and re-run after configuration updates.",
        "4. Review historical differences alongside source coverage and collection timestamps.",
        "",
    ])


def _technical_report(
    run: sqlite3.Row, sources: list[dict[str, Any]], observations: list[dict[str, Any]],
    entities: list[dict[str, Any]], relationships: list[dict[str, Any]],
    findings: list[dict[str, Any]], baseline: str | None,
) -> str:
    source_lines = [
        f"- {row['source_id']} — {row['status'] or 'not enabled'} "
        f"(received {row['records_received'] or 0}, accepted {row['records_accepted'] or 0})"
        for row in sources
    ] or ["- No registered sources."]
    errors = [
        f"{row['source_id']}: {row['error_summary']}"
        for row in sources if row.get("error_summary")
    ]
    limitations = sorted(set(errors + [
        "No active validation, login, credential collection or API invocation is performed.",
        "Static API routes and vendor strings are references, not proof of use or reachability.",
        "Nameserver and Certificate Transparency observations are not ownership assertions.",
        "Name similarity is a review candidate and never an automatic identity merge.",
    ]))
    return "\n".join([
        f"# Technical report — {run['engagement_name']}",
        "",
        "## 1. Scope and authorization",
        "",
        f"- Engagement: {run['engagement_name']} ({run['engagement_slug']})",
        f"- Organization: {run['organization_name'] or 'not specified'}",
        f"- Authorization reference: {run['authorization_reference'] or 'not supplied'}",
        f"- Declared scope: {run['scope_json']}",
        "",
        "## 2. Objectives and exclusions",
        "",
        "Inventory passive external-asset and public technology-dependency observations, "
        "preserve evidence provenance, resolve entities conservatively, and produce "
        "analyst-reviewable relationships. Active scanning, exploitation, login, state changes, "
        "customer account data, payment information and secret harvesting are excluded.",
        "",
        "## 3. Methodology",
        "",
        f"FII report schema {REPORT_VERSION}; pipeline version {run['software_version']}. "
        "Collection is sequential. Raw evidence is checked against stored SHA-256 before "
        "publication. Observations are canonicalized and de-duplicated within the run, then "
        "linked to source provenance. Exact registered identifiers are used for entity resolution; "
        "weak names remain candidates. Relationship rules require typed evidence from this run.",
        "",
        "## 4. Source register and coverage",
        "",
        *source_lines,
        "",
        "## 5. Collection timeline",
        "",
        f"- Run started: {run['started_at']}",
        f"- Run finished: {run['finished_at'] or 'not recorded'}",
        f"- Historical comparison baseline: {baseline or 'not available'}",
        "",
        "## 6. Inventory and analysis summary",
        "",
        f"- Observations: {len(observations)}",
        f"- Entities: {len(entities)}",
        f"- Relationships: {len(relationships)}",
        f"- Research findings: {len(findings)}",
        "",
        "## 7. Relationship interpretation",
        "",
        "Each relationship export includes source observation identifiers and evidentiary roles. "
        "Verification state and confidence are outputs of a versioned rule; confidence is not "
        "calibrated probability. Analyst acceptance does not increase evidence confidence.",
        "",
        "## 8. Findings",
        "",
        "Findings are informational research leads. No vulnerability severity is assigned to "
        "ordinary asset discovery. Each generated finding is linked to observation evidence.",
        "",
        "## 9. Limitations and unresolved questions",
        "",
        *[f"- {item}" for item in limitations],
        "",
        "## 10. Evidence package",
        "",
        "See observations.jsonl, entities.json, relationships.csv, findings.csv, source-register.csv "
        "and report-manifest.json. Raw evidence remains under the run's private evidence directory "
        "and is cited by relative path and SHA-256.",
        "",
    ])


def render_reports(
    database_path: str | Path, run_id: str, run_directory: str | Path
) -> ReportResult:
    """Render all report exports and verify each cited raw-evidence digest."""
    root = Path(run_directory).expanduser().resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        raise ReportError("Run directory must be a regular directory.")
    report_dir = root / "reports"
    if report_dir.is_symlink():
        raise ReportError("Refusing symlinked reports directory.")
    report_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(report_dir, 0o700)

    connection = connect_database(database_path)
    try:
        run = _run(connection, run_id)
        observations = _observations(connection, run_id)
        provenance = _provenance(connection, run_id)
        verified_raw = _verify_evidence(root, [*observations, *provenance])
        entities = _entities(connection, run_id)
        relationships = _relationships(connection, run_id)
        sources = _sources(connection, run_id)
        findings = _findings(connection, run_id)
        reviews = _reviews(connection, run_id)
        baseline, changes = _changes(connection, run, run_id)
        source_counts = _counts(sources)

        assets = [{
            "entity_id": e["entity_id"], "entity_type": e["entity_type"],
            "display_name": e["display_name"], "canonical_key": e["canonical_key"],
            "identifiers": "; ".join(
                f"{i['identifier_type']}={i['identifier_value']}" for i in e["identifiers"]
            ),
            "attributes": _stable_json(e["attributes"]),
        } for e in entities]
        relationship_rows = [{
            **{k: row[k] for k in (
                "relationship_id", "subject_entity_id", "subject_name", "predicate",
                "object_entity_id", "object_name", "verification_state", "confidence",
                "rationale", "rule_id", "rule_version", "first_seen_at", "last_seen_at",
            )},
            "evidence": _stable_json(row["evidence"]),
        } for row in relationships]
        provenance_by_observation: dict[str, list[dict[str, Any]]] = {}
        for item in provenance:
            provenance_by_observation.setdefault(item["observation_id"], []).append(item)
        observation_lines = []
        for row in observations:
            observation_lines.append(_stable_json({
                "schema_version": REPORT_VERSION, "run_id": run_id,
                "observation_id": row["observation_id"],
                "observation_type": row["observation_type"],
                "observed_value": row["observed_value"], "observed_at": row["observed_at"],
                "collected_at": row["collected_at"], "source_id": row["source_id"],
                "source_name": row["source_name"], "source_url": row["source_url"],
                "raw_evidence_path": row["raw_evidence_path"], "raw_sha256": row["raw_sha256"],
                "verification_state": row["verification_state"], "confidence": row["confidence"],
                "attributes": row["attributes"], "subject_entity_id": row["subject_entity_id"],
                "provenance": provenance_by_observation.get(row["observation_id"], []),
            }))
        source_export = [{
            **row,
            "execution_state": row["status"] or "not_enabled",
            "requires_credentials": bool(row["requires_credentials"]),
            "default_enabled": bool(row["default_enabled"]),
        } for row in sources]
        finding_export = [{
            **row, "evidence": _stable_json(row["evidence"])
        } for row in findings]

        contents: dict[str, bytes] = {
            "asset-inventory.csv": _csv_bytes(
                ("entity_id", "entity_type", "display_name", "canonical_key", "identifiers", "attributes"),
                assets,
            ),
            "entities.json": (
                json.dumps({"schema_version": REPORT_VERSION, "run_id": run_id, "entities": entities},
                           ensure_ascii=False, sort_keys=True, indent=2) + "\n"
            ).encode("utf-8"),
            "relationships.csv": _csv_bytes(
                ("relationship_id", "subject_entity_id", "subject_name", "predicate",
                 "object_entity_id", "object_name", "verification_state", "confidence",
                 "rationale", "rule_id", "rule_version", "first_seen_at", "last_seen_at", "evidence"),
                relationship_rows,
            ),
            "observations.jsonl": ("\n".join(observation_lines) + ("\n" if observation_lines else "")).encode("utf-8"),
            "source-register.csv": _csv_bytes(
                ("source_id", "name", "adapter_version", "source_class", "documentation_url",
                 "terms_url", "requires_credentials", "default_enabled", "source_execution_id",
                 "attempt_number", "execution_state", "started_at", "finished_at", "records_received",
                 "records_accepted", "raw_manifest_path", "error_code", "error_summary"),
                source_export,
            ),
            "analyst-review.csv": _csv_bytes(
                ("relationship_id", "subject_name", "predicate", "object_name", "verification_state",
                 "confidence", "disposition", "reviewer_label", "review_rationale", "reviewed_at",
                 "relationship_rationale"),
                reviews,
            ),
            "changes.csv": _csv_bytes(
                ("change_type", "observation_id", "observation_type", "observed_value", "source_url",
                 "deduplication_key", "previous_run_id", "current_run_id", "note"),
                changes,
            ),
            "findings.csv": _csv_bytes(
                ("finding_id", "finding_type", "title", "description", "priority", "confidence",
                 "verification_state", "disposition", "rationale", "created_at", "updated_at", "evidence"),
                finding_export,
            ),
            "executive-summary.md": _executive_summary(
                run, source_counts, len(observations), len(entities),
                len(relationships), len(findings), baseline,
            ).encode("utf-8"),
            "technical-report.md": _technical_report(
                run, sources, observations, entities, relationships, findings, baseline
            ).encode("utf-8"),
        }

        digests: dict[str, str] = {}
        for name in sorted(contents):
            _write_atomic(report_dir / name, contents[name])
            digests[name] = _digest(contents[name])
        manifest = {
            "report_schema_version": REPORT_VERSION, "run_id": run_id,
            "engagement_slug": run["engagement_slug"], "run_status": run["status"],
            "generated_at": _now(), "database": Path(database_path).name,
            "baseline_run_id": baseline,
            "counts": {
                "source_statuses": source_counts, "observations": len(observations),
                "entities": len(entities), "relationships": len(relationships),
                "findings": len(findings),
            },
            "verified_raw_evidence_files": verified_raw,
            "artifacts": [
                {"path": name, "size_bytes": len(contents[name]), "sha256": digests[name]}
                for name in sorted(contents)
            ],
            "limitations": [
                "An observation absent from a later run is not proof of external removal.",
                "Asset counts are not converted into a risk score.",
                "Static references do not prove operational use or endpoint reachability.",
                "Confidence values are not calibrated probabilities.",
            ],
        }
        manifest_bytes = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        _write_atomic(report_dir / "report-manifest.json", manifest_bytes)
        digests["report-manifest.json"] = _digest(manifest_bytes)
        return ReportResult(
            directory=report_dir,
            files=tuple(report_dir / name for name in REPORT_FILES),
            sha256=digests,
        )
    except (sqlite3.Error, PersistenceError) as exc:
        raise ReportError("Unable to query the FII evidence database for reporting.") from exc
    finally:
        connection.close()
