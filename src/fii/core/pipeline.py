"""Sequential end-to-end FII collection, evidence persistence and analysis pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fii.core.run_controller import (
    RunError,
    begin_stage,
    create_run,
    finalize_run,
    finish_stage,
    make_stage_fingerprint,
    open_run,
    reconcile_interrupted_stages,
)
from fii.core.workspace import WorkspaceLock, WorkspacePaths, prepare_workspace
from fii.normalization.entities import (
    EntityIdentifier,
    EntitySeed,
    register_entity_registry,
    resolve_entity,
)
from fii.normalization.observations import (
    SourceObservationEnvelope,
    deduplicate_observations,
)
from fii.normalization.persistence import persist_canonical_observations
from fii.relationships.correlation import (
    RelationshipEvidence,
    RelationshipProposal,
    propose_relationship,
)
from fii.sources.contracts import CollectionContext, CollectionResult, run_collector, utc_now
from fii.sources.registry import SourceRegistry, get_default_registry
from fii.storage.database import (
    PersistenceError,
    connect_database,
    initialize_database,
    transaction,
)

IMPLEMENTATION_VERSION = "0.2.0"
DATABASE_NAME = "fii.sqlite3"
_ALLOWED_SOURCE_SETTINGS = {
    "enabled",
    "required",
    "fixture",
    "source_url",
    "domains",
    "organization_names",
    "legal_entity_identifiers",
    "live_approved",
}


class PipelineError(RuntimeError):
    """Raised when orchestration cannot preserve a trustworthy run."""


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    status: str
    workspace: WorkspacePaths
    run_directory: Path
    database_path: Path
    source_counts: dict[str, int]
    observation_count: int
    entity_count: int
    relationship_count: int
    finding_count: int


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _digest(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    """Atomically publish a private JSON run artifact."""
    if path.is_symlink():
        raise PipelineError(f"Refusing symlinked pipeline artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _settings(config: dict[str, Any], registry: SourceRegistry) -> dict[str, dict[str, Any]]:
    configured = config.get("sources", {})
    unknown = sorted(set(configured) - set(registry.source_ids()))
    if unknown:
        raise PipelineError("Unknown configured source IDs: " + ", ".join(unknown))
    normalized: dict[str, dict[str, Any]] = {}
    for source_id, raw in configured.items():
        if not isinstance(raw, dict):
            raise PipelineError(f"sources.{source_id} must be a mapping.")
        extra = sorted(set(raw) - _ALLOWED_SOURCE_SETTINGS)
        if extra:
            raise PipelineError(
                f"Unsupported settings for sources.{source_id}: " + ", ".join(extra)
            )
        for flag in ("enabled", "required", "live_approved"):
            if flag in raw and not isinstance(raw[flag], bool):
                raise PipelineError(f"sources.{source_id}.{flag} must be true or false.")
        if raw.get("required") and not raw.get("enabled"):
            raise PipelineError(f"sources.{source_id}.required cannot be true while disabled.")
        fixture = raw.get("fixture")
        if fixture is not None and (not isinstance(fixture, str) or not fixture.strip()):
            raise PipelineError(f"sources.{source_id}.fixture must be a non-empty path.")
        source_url = raw.get("source_url")
        if source_url is not None and (
            not isinstance(source_url, str) or not source_url.strip()
        ):
            raise PipelineError(f"sources.{source_id}.source_url must be a non-empty URL.")
        normalized[source_id] = dict(raw)
    return normalized


def _fixture_path(value: str | None, config_path: Path) -> Path | None:
    if value is None:
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = config_path.parent / candidate
    return candidate


def _selected_domains(
    source_id: str, settings: dict[str, Any], config: dict[str, Any]
) -> tuple[str, ...]:
    permitted = tuple(config["scope"]["seed_domains"])
    requested = settings.get("domains", permitted)
    if not isinstance(requested, list) or not requested:
        raise PipelineError(f"sources.{source_id}.domains must be a non-empty list.")
    if any(not isinstance(item, str) for item in requested):
        raise PipelineError(f"sources.{source_id}.domains must contain domain strings.")
    selected = tuple(dict.fromkeys(item.strip().lower() for item in requested))
    outside = sorted(set(selected) - set(permitted))
    if outside:
        raise PipelineError(
            f"sources.{source_id} requests domains outside engagement scope: "
            + ", ".join(outside)
        )
    return selected


def _invocations(
    source_id: str, settings: dict[str, Any], config: dict[str, Any]
) -> tuple[dict[str, Any], ...]:
    if source_id in {"rdap_domain", "ct_live"}:
        return tuple({"domains": (domain,)} for domain in _selected_domains(source_id, settings, config))
    if source_id == "gleif_lei":
        names = settings.get("organization_names", [])
        leis = settings.get("legal_entity_identifiers", [])
        if not isinstance(names, list) or not isinstance(leis, list):
            raise PipelineError(
                "GLEIF organization_names and legal_entity_identifiers must be lists."
            )
        if len(names) + len(leis) > 100:
            raise PipelineError("GLEIF entity query list exceeds the 100-entry limit.")
        if any(not isinstance(item, str) or not item.strip() for item in (*names, *leis)):
            raise PipelineError("GLEIF entity queries must be non-empty strings.")
        if names and leis:
            raise PipelineError("Configure GLEIF organization names or LEIs, not both.")
        return tuple(
            {"organization_names": (item,)} for item in names
        ) or tuple({"legal_entity_identifiers": (item,)} for item in leis) or (
            {"organization_names": (config["engagement"]["organization"],)}
            if config["engagement"].get("organization")
            else ()
        )
    return ({},)


def _register_database(
    connection: sqlite3.Connection,
    config: dict[str, Any],
    config_path: Path,
    run_id: str,
    config_digest: str,
    scope_digest: str,
) -> None:
    engagement = config["engagement"]
    timestamp = _now()
    existing = connection.execute(
        "SELECT engagement_id FROM engagement WHERE slug = ?", (engagement["slug"],)
    ).fetchone()
    engagement_id = (
        existing["engagement_id"] if existing else str(uuid.uuid4())
    )
    with transaction(connection, immediate=True):
        connection.execute(
            """
            INSERT INTO engagement (
                engagement_id, slug, display_name, organization_name, config_path,
                scope_json, authorization_reference, created_at, updated_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
            ON CONFLICT(slug) DO UPDATE SET
                display_name=excluded.display_name,
                organization_name=excluded.organization_name,
                config_path=excluded.config_path,
                scope_json=excluded.scope_json,
                authorization_reference=excluded.authorization_reference,
                updated_at=excluded.updated_at,
                status='active'
            """,
            (
                engagement_id,
                engagement["slug"],
                engagement["name"],
                engagement.get("organization") or None,
                str(config_path.resolve()),
                json.dumps(config["scope"], sort_keys=True, separators=(",", ":")),
                engagement.get("authorization_reference") or None,
                timestamp,
                timestamp,
            ),
        )
        row = connection.execute(
            "SELECT engagement_id FROM engagement WHERE slug = ?", (engagement["slug"],)
        ).fetchone()
        engagement_id = row["engagement_id"]
        connection.execute(
            """
            INSERT OR IGNORE INTO run (
                run_id, engagement_id, started_at, status, config_digest,
                software_version, scope_digest, operator_label
            ) VALUES (?, ?, ?, 'running', ?, ?, ?, ?)
            """,
            (
                run_id,
                engagement_id,
                timestamp,
                config_digest,
                IMPLEMENTATION_VERSION,
                scope_digest,
                "fii-cli",
            ),
        )


def _source_execution(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    source_id: str,
    attempt_number: int,
    status: str,
    started_at: str,
    finished_at: str,
    records_received: int = 0,
    records_accepted: int = 0,
    raw_manifest_path: str | None = None,
    configuration_digest: str | None = None,
    error_code: str | None = None,
    error_summary: str | None = None,
) -> str:
    execution_id = str(uuid.uuid4())
    with transaction(connection, immediate=True):
        connection.execute(
            """
            INSERT INTO source_execution (
                source_execution_id, run_id, source_id, attempt_number, status,
                started_at, finished_at, records_received, records_accepted,
                raw_manifest_path, configuration_digest, error_code, error_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                execution_id, run_id, source_id, attempt_number, status,
                started_at, finished_at, records_received, records_accepted,
                raw_manifest_path, configuration_digest, error_code, error_summary,
            ),
        )
    return execution_id


def _insert_stage_attempt(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    stage_id: str,
    attempt_number: int,
    status: str,
    started_at: str,
    finished_at: str | None,
    input_digest: str,
    output_manifest_path: str | None = None,
    error_summary: str | None = None,
) -> str:
    attempt_id = str(uuid.uuid4())
    with transaction(connection, immediate=True):
        connection.execute(
            """
            INSERT INTO stage_attempt (
                attempt_id, run_id, stage_id, attempt_number, status,
                input_digest, started_at, finished_at, output_manifest_path,
                error_summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id, run_id, stage_id, attempt_number, status, input_digest,
                started_at, finished_at, output_manifest_path, error_summary,
            ),
        )
    return attempt_id


def _upsert_source_definition(connection: sqlite3.Connection, definition: Any) -> None:
    with transaction(connection, immediate=True):
        connection.execute(
            """
            INSERT INTO source_definition (
                source_id, name, adapter_version, source_class, documentation_url,
                terms_url, requires_credentials, default_enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                name=excluded.name,
                adapter_version=excluded.adapter_version,
                source_class=excluded.source_class,
                documentation_url=excluded.documentation_url,
                terms_url=excluded.terms_url,
                requires_credentials=excluded.requires_credentials,
                default_enabled=excluded.default_enabled
            """,
            (
                definition.source_id, definition.name, definition.adapter_version,
                definition.source_class, definition.documentation_url, definition.terms_url,
                int(definition.requires_credentials), int(definition.default_enabled),
            ),
        )


def _entity_seed(
    run_id: str, observation_id: str, observation_type: str, value: str, attributes: dict[str, Any]
) -> EntitySeed | None:
    identifiers: tuple[EntityIdentifier, ...] = ()
    entity_type: str | None = None
    display_name = value

    if observation_type in {"rdap_domain", "domain_seen"}:
        entity_type = "domain"
        identifiers = (EntityIdentifier("domain", value),)
    elif observation_type in {
        "rdap_nameserver", "ct_hostname", "certificate_name", "hostname_seen", "hostname"
    }:
        entity_type = "hostname"
        identifiers = (EntityIdentifier("hostname", value),)
    elif observation_type in {
        "legal_entity_identifier", "lei_legal_name", "lei_entity_status",
        "lei_registration_status", "lei_jurisdiction", "lei_legal_form",
        "gleif_relationship_reference"
    }:
        lei = attributes.get("lei") or (value if observation_type == "legal_entity_identifier" else None)
        if isinstance(lei, str) and len(lei) == 20:
            entity_type = "organization"
            identifiers = (EntityIdentifier("lei", lei),)
            display_name = str(attributes.get("legal_name") or attributes.get("lei") or value)
        elif observation_type == "lei_legal_name":
            entity_type = "organization"
            display_name = value
    elif observation_type in {"integration_reference", "rdap_registrar"}:
        entity_type = "vendor"
    elif observation_type == "api_endpoint":
        entity_type = "api_endpoint"
    elif observation_type in {
        "api_documentation_reference", "javascript_asset", "source_map_reference"
    }:
        entity_type = "documentation_resource"

    if entity_type is None:
        return None
    return EntitySeed(
        run_id=run_id,
        source_observation_id=observation_id,
        entity_type=entity_type,
        display_name=display_name,
        identifiers=identifiers,
        attributes=attributes,
    )


def _resolve_entities_and_relationships(
    connection: sqlite3.Connection, run_id: str
) -> tuple[int, int]:
    rows = connection.execute(
        """
        SELECT observation_id, observation_type, observed_value, attributes_json, source_url
        FROM observation WHERE run_id = ?
        ORDER BY CASE observation_type
            WHEN 'rdap_domain' THEN 0
            WHEN 'domain_seen' THEN 0
            ELSE 1 END, observation_id
        """,
        (run_id,),
    ).fetchall()
    resolved: dict[str, str] = {}
    seeds: dict[str, EntitySeed] = {}
    for row in rows:
        try:
            attributes = json.loads(row["attributes_json"] or "{}")
        except json.JSONDecodeError as exc:
            raise PipelineError("Stored observation attributes are invalid JSON.") from exc
        seed = _entity_seed(
            run_id, row["observation_id"], row["observation_type"], row["observed_value"], attributes
        )
        if seed is None:
            continue
        result = resolve_entity(connection, seed)
        if result.entity_id:
            resolved[row["observation_id"]] = result.entity_id
            seeds[row["observation_id"]] = seed

    relationship_count = 0
    for row in rows:
        observation_id = row["observation_id"]
        entity_id = resolved.get(observation_id)
        if entity_id is None:
            continue
        attributes = json.loads(row["attributes_json"] or "{}")
        relationship_spec: tuple[str, str, str] | None = None
        if row["observation_type"] == "rdap_nameserver":
            domain = attributes.get("domain")
            if isinstance(domain, str):
                subject = connection.execute(
                    """
                    SELECT e.entity_id FROM entity e
                    JOIN entity_identifier i ON i.entity_id=e.entity_id
                    WHERE e.entity_type='domain' AND i.identifier_type='domain'
                      AND i.identifier_value=? ORDER BY e.entity_id LIMIT 1
                    """,
                    (domain.lower(),),
                ).fetchone()
                if subject:
                    relationship_spec = (
                        "domain_has_nameserver", subject["entity_id"], entity_id
                    )
        elif row["observation_type"] in {
            "integration_reference", "api_endpoint", "api_documentation_reference"
        }:
            source_url = row["source_url"] or ""
            host = urlsplit(source_url).hostname if source_url else None
            if host:
                subject = connection.execute(
                    """
                    SELECT e.entity_id FROM entity e
                    JOIN entity_identifier i ON i.entity_id=e.entity_id
                    WHERE e.entity_type='domain' AND i.identifier_type='domain'
                      AND i.identifier_value=? ORDER BY e.entity_id LIMIT 1
                    """,
                    (host.lower(),),
                ).fetchone()
                rule_id = {
                    "integration_reference": "website_references_vendor",
                    "api_endpoint": "website_references_api_endpoint",
                    "api_documentation_reference": "website_references_api_documentation",
                }[row["observation_type"]]
                if subject:
                    relationship_spec = (rule_id, subject["entity_id"], entity_id)

        if relationship_spec:
            rule_id, subject_id, object_id = relationship_spec
            relationship = propose_relationship(
                connection,
                RelationshipProposal(
                    run_id=run_id,
                    rule_id=rule_id,
                    subject_entity_id=subject_id,
                    object_entity_id=object_id,
                    evidence=(RelationshipEvidence(observation_id, "supports"),),
                    rationale="Derived by the deterministic FII pipeline; source claim remains qualified.",
                ),
            )
            if relationship.inserted:
                relationship_count += 1
    entity_count = connection.execute(
        """
        SELECT COUNT(DISTINCT COALESCE(proposed_entity_id, matched_entity_id))
        FROM entity_resolution_decision
        WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()[0]
    return int(entity_count), relationship_count


def _create_findings(connection: sqlite3.Connection, run_id: str) -> int:
    rows = connection.execute(
        """
        SELECT observation_id, observation_type, observed_value, source_url,
               verification_state, raw_evidence_path, raw_sha256
        FROM observation
        WHERE run_id = ? AND observation_type IN (
            'integration_reference', 'api_endpoint', 'api_documentation_reference',
            'auth_structure', 'rdap_nameserver', 'rdap_registrar'
        )
        ORDER BY observation_id
        """,
        (run_id,),
    ).fetchall()
    count = 0
    namespace = uuid.UUID("f0a0b7f4-60af-5dbf-90d8-43a429b2b44a")
    for row in rows:
        kind = row["observation_type"]
        title_map = {
            "integration_reference": "Static financial technology provider reference",
            "api_endpoint": "Static API route reference",
            "api_documentation_reference": "Public API documentation reference",
            "auth_structure": "Authentication architecture marker",
            "rdap_nameserver": "Registered domain nameserver reference",
            "rdap_registrar": "Domain registrar metadata",
        }
        finding_type = f"research_{kind}"
        finding_id = str(uuid.uuid5(namespace, f"{run_id}:{finding_type}:{row['observation_id']}"))
        description = (
            f"Observed {kind.replace('_', ' ')}: {row['observed_value']}. "
            "This is an evidence-backed research lead, not a vulnerability or proof "
            "of an operational integration."
        )
        timestamp = _now()
        with transaction(connection, immediate=True):
            connection.execute(
                """
                INSERT OR IGNORE INTO finding (
                    finding_id, run_id, finding_type, title, description, priority,
                    confidence, verification_state, disposition, rationale,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'informational', NULL, 'candidate',
                          'needs_research', ?, ?, ?)
                """,
                (
                    finding_id, run_id, finding_type, title_map[kind], description,
                    f"Derived from observation {row['observation_id']}; no active validation performed.",
                    timestamp, timestamp,
                ),
            )
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO finding_evidence (
                    finding_evidence_id, finding_id, run_id, observation_id,
                    relationship_id, evidence_role
                ) VALUES (?, ?, ?, ?, NULL, 'supports')
                """,
                (
                    str(uuid.uuid5(namespace, f"{finding_id}:{row['observation_id']}")),
                    finding_id, run_id, row["observation_id"],
                ),
            )
            count += cursor.rowcount
    return count


def _run_counts(connection: sqlite3.Connection, run_id: str) -> tuple[dict[str, int], int, int, int, int]:
    sources = {
        row["status"]: int(row["count"])
        for row in connection.execute(
            "SELECT status, COUNT(*) AS count FROM source_execution WHERE run_id=? GROUP BY status",
            (run_id,),
        ).fetchall()
    }
    observations = connection.execute(
        "SELECT COUNT(*) FROM observation WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    entities = connection.execute(
        "SELECT COUNT(DISTINCT COALESCE(proposed_entity_id, matched_entity_id)) "
        "FROM entity_resolution_decision WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    relationships = connection.execute(
        """
        SELECT COUNT(DISTINCT r.relationship_id)
        FROM relationship r JOIN relationship_evidence re
          ON re.relationship_id=r.relationship_id
        JOIN observation o ON o.observation_id=re.observation_id
        WHERE o.run_id=?
        """,
        (run_id,),
    ).fetchone()[0]
    findings = connection.execute(
        "SELECT COUNT(*) FROM finding WHERE run_id=?", (run_id,)
    ).fetchone()[0]
    return sources, int(observations), int(entities), int(relationships), int(findings)


def execute_pipeline(
    config: dict[str, Any],
    config_path: str | Path,
    *,
    resume_run_id: str | None = None,
    registry: SourceRegistry | None = None,
) -> PipelineResult:
    """Run enabled sources sequentially, persist evidence, resolve entities and findings.

    A source must be explicitly enabled in YAML. Live adapters require both a
    global live-collection approval and a per-source approval, as well as an
    authorization reference. Fixture adapters remain fully offline.
    """
    active_registry = registry or get_default_registry()
    path = Path(config_path).expanduser().resolve()
    settings = _settings(config, active_registry)
    workspace = prepare_workspace(config)
    database_path = workspace.database / DATABASE_NAME
    initialize_database(database_path)

    run_paths = (
        open_run(workspace, resume_run_id)
        if resume_run_id
        else create_run(workspace, config, implementation_version=IMPLEMENTATION_VERSION)
    )
    manifest = json.loads(run_paths.manifest.read_text(encoding="utf-8"))
    run_id = run_paths.run_id
    config_digest = manifest["config_sha256"]
    scope_digest = manifest["scope_sha256"]
    state = json.loads(run_paths.state.read_text(encoding="utf-8"))
    if state.get("status") in {"completed", "partial", "failed", "cancelled"}:
        raise PipelineError(f"Run {run_id} is terminal ({state['status']}) and cannot be resumed.")

    raw_directory = run_paths.directory / "evidence"
    raw_directory.mkdir(mode=0o700, exist_ok=True)
    os.chmod(raw_directory, 0o700)

    source_outcomes: list[tuple[str, str]] = []
    source_defs = {definition.source_id: definition for definition in active_registry.definitions()}
    enabled = {
        source_id: source_settings
        for source_id, source_settings in settings.items()
        if source_settings.get("enabled", False)
    }
    permitted_classes = set(config["scope"]["permitted_source_classes"])
    for source_id, source_settings in enabled.items():
        definition = source_defs[source_id]
        if definition.source_class not in permitted_classes:
            raise PipelineError(
                f"Source {source_id} has class {definition.source_class!r}, "
                "which is not permitted by this engagement."
            )
        if source_id in {"ct_live", "website_public"} and not source_settings.get("fixture"):
            globally_approved = config["collection"].get("live_collection_approved", False)
            if not (
                globally_approved
                and source_settings.get("live_approved", False)
                and config["engagement"].get("authorization_reference")
            ):
                raise PipelineError(
                    f"Live source {source_id} requires collection.live_collection_approved, "
                    "sources.{source_id}.live_approved and a written authorization_reference."
                )

    db = connect_database(database_path)
    try:
        with WorkspaceLock(workspace.engagement):
            _register_database(
                db, config, path, run_id, config_digest, scope_digest
            )
            for definition in active_registry.definitions():
                _upsert_source_definition(db, definition)

            if resume_run_id:
                reconcile_interrupted_stages(run_paths)
                with transaction(db, immediate=True):
                    db.execute(
                        "UPDATE run SET status='running', finished_at=NULL WHERE run_id=?",
                        (run_id,),
                    )

            for source_id, source_settings in settings.items():
                if not source_settings.get("enabled", False):
                    continue
                definition = source_defs[source_id]
                fixture = _fixture_path(source_settings.get("fixture"), path)
                invocations = _invocations(source_id, source_settings, config)
                if not invocations:
                    raise PipelineError(
                        f"Source {source_id} is enabled but no approved query was configured."
                    )

                for index, invocation in enumerate(invocations, start=1):
                    stage_id = f"collect_{source_id}_{index}"
                    stage_config = {
                        "source_id": source_id,
                        "settings": source_settings,
                        "invocation": invocation,
                        "adapter_version": definition.adapter_version,
                    }
                    fingerprint = make_stage_fingerprint(
                        stage_id,
                        implementation_version=IMPLEMENTATION_VERSION,
                        config_digest=config_digest,
                        scope_digest=scope_digest,
                        input_manifest_digest=_digest(stage_config),
                        collector_version=definition.adapter_version,
                    )
                    decision = begin_stage(run_paths, stage_id, fingerprint)
                    if not decision.should_run:
                        source_outcomes.append((source_id, "success"))
                        continue

                    attempt_started = _now()
                    _insert_stage_attempt(
                        db, run_id=run_id, stage_id=stage_id,
                        attempt_number=decision.attempt, status="running",
                        started_at=attempt_started, finished_at=None, input_digest=fingerprint,
                    )
                    collector = active_registry.get(source_id)
                    context = CollectionContext(
                        run_id=run_id,
                        raw_directory=raw_directory,
                        fixture_path=fixture,
                        approved_domains=invocation.get("domains", tuple(config["scope"]["seed_domains"])),
                        organization_names=invocation.get("organization_names", ()),
                        legal_entity_identifiers=invocation.get("legal_entity_identifiers", ()),
                        source_url=source_settings.get("source_url"),
                        request_timeout_seconds=config["collection"]["request_timeout_seconds"],
                        user_agent=config["collection"]["user_agent"],
                        max_response_bytes=config["collection"].get("max_response_bytes", 2 * 1024 * 1024),
                        max_linked_assets=config["collection"].get("max_linked_assets", 20),
                        minimum_request_interval_seconds=config["collection"].get(
                            "minimum_request_interval_seconds", 1.0
                        ),
                        live_collection_approved=(
                            config["collection"].get("live_collection_approved", False)
                            and source_settings.get("live_approved", False)
                            and bool(config["engagement"].get("authorization_reference"))
                        ),
                    )
                    try:
                        result: CollectionResult = run_collector(collector, context)
                        attempt_number = db.execute(
                            """
                            SELECT COALESCE(MAX(attempt_number),0)+1 FROM source_execution
                            WHERE run_id=? AND source_id=?
                            """,
                            (run_id, source_id),
                        ).fetchone()[0]
                        source_manifest = run_paths.directory / "source-results" / (
                            f"{source_id}-{attempt_number:03d}.json"
                        )
                        _write_json(source_manifest, result.to_dict())
                        execution_id = _source_execution(
                            db,
                            run_id=run_id,
                            source_id=source_id,
                            attempt_number=attempt_number,
                            status=result.status,
                            started_at=result.started_at,
                            finished_at=result.finished_at,
                            records_received=result.records_received,
                            records_accepted=result.records_accepted,
                            raw_manifest_path=source_manifest.relative_to(run_paths.directory).as_posix(),
                            configuration_digest=_digest(stage_config),
                            error_code=(
                                result.diagnostics[0].code
                                if result.status == "failed" and result.diagnostics else None
                            ),
                            error_summary=(
                                result.diagnostics[0].message
                                if result.status == "failed" and result.diagnostics else None
                            ),
                        )
                        raw_by_hash = {item.sha256: item for item in result.raw_evidence}
                        envelopes = []
                        for observation in result.observations:
                            evidence = raw_by_hash.get(observation.raw_sha256)
                            if evidence is None:
                                raise PipelineError(
                                    f"{source_id} emitted an observation without retained evidence."
                                )
                            evidence_path = f"evidence/{evidence.relative_path}"
                            envelopes.append(
                                SourceObservationEnvelope(
                                    run_id=run_id,
                                    source_execution_id=execution_id,
                                    observation=observation,
                                    raw_evidence_path=evidence_path,
                                )
                            )
                        deduplicated = deduplicate_observations(envelopes)
                        persist_canonical_observations(db, deduplicated.observations)
                        source_outcomes.append((source_id, result.status))
                        stage_status = "success" if result.status == "success" else "partial"
                        finish_stage(
                            run_paths, stage_id, stage_status,
                            output_manifest=source_manifest.relative_to(run_paths.directory).as_posix(),
                        )
                        _insert_stage_attempt(
                            db, run_id=run_id, stage_id=stage_id,
                            attempt_number=decision.attempt, status=stage_status,
                            started_at=attempt_started, finished_at=_now(), input_digest=fingerprint,
                            output_manifest_path=source_manifest.relative_to(run_paths.directory).as_posix(),
                        )
                    except BaseException as exc:
                        try:
                            finish_stage(run_paths, stage_id, "failed", error=str(exc)[:500])
                        except RunError:
                            pass
                        _insert_stage_attempt(
                            db, run_id=run_id, stage_id=stage_id,
                            attempt_number=decision.attempt, status="failed",
                            started_at=attempt_started, finished_at=_now(), input_digest=fingerprint,
                            error_summary=str(exc)[:500],
                        )
                        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                            raise
                        raise

            analysis_stage_id = "resolve_correlate_analyze"
            analysis_fingerprint = make_stage_fingerprint(
                analysis_stage_id,
                implementation_version=IMPLEMENTATION_VERSION,
                config_digest=config_digest,
                scope_digest=scope_digest,
                input_manifest_digest=_digest({
                    "observations": db.execute(
                        "SELECT COUNT(*) FROM observation WHERE run_id=?", (run_id,)
                    ).fetchone()[0],
                    "source_executions": [
                        tuple(row) for row in db.execute(
                            "SELECT source_id, attempt_number, status, configuration_digest "
                            "FROM source_execution WHERE run_id=? ORDER BY source_id, attempt_number",
                            (run_id,),
                        ).fetchall()
                    ],
                }),
            )
            analysis_decision = begin_stage(run_paths, analysis_stage_id, analysis_fingerprint)
            if analysis_decision.should_run:
                analysis_started = _now()
                _insert_stage_attempt(
                    db, run_id=run_id, stage_id=analysis_stage_id,
                    attempt_number=analysis_decision.attempt, status="running",
                    started_at=analysis_started, finished_at=None, input_digest=analysis_fingerprint,
                )
                try:
                    register_entity_registry(db)
                    _resolve_entities_and_relationships(db, run_id)
                    _create_findings(db, run_id)
                    finish_stage(run_paths, analysis_stage_id, "success")
                    _insert_stage_attempt(
                        db, run_id=run_id, stage_id=analysis_stage_id,
                        attempt_number=analysis_decision.attempt, status="success",
                        started_at=analysis_started, finished_at=_now(), input_digest=analysis_fingerprint,
                    )
                except BaseException as exc:
                    finish_stage(run_paths, analysis_stage_id, "failed", error=str(exc)[:500])
                    _insert_stage_attempt(
                        db, run_id=run_id, stage_id=analysis_stage_id,
                        attempt_number=analysis_decision.attempt, status="failed",
                        started_at=analysis_started, finished_at=_now(), input_digest=analysis_fingerprint,
                        error_summary=str(exc)[:500],
                    )
                    raise

            counts, observation_count, entity_count, relationship_count, finding_count = (
                _run_counts(db, run_id)
            )
            required_failures = any(
                settings.get(source_id, {}).get("required", False)
                and outcome in {"failed", "partial", "skipped"}
                for source_id, outcome in source_outcomes
            )
            executed_enabled = len(enabled)
            success_count = counts.get("success", 0)
            failed_count = counts.get("failed", 0) + counts.get("partial", 0)
            if executed_enabled == 0:
                status = "partial"
            elif failed_count and success_count == 0:
                status = "failed"
            elif failed_count or required_failures:
                status = "partial"
            else:
                status = "completed"

            finalize_run(run_paths, status)
            summary = {
                "source_counts": counts,
                "observation_count": observation_count,
                "entity_count": entity_count,
                "relationship_count": relationship_count,
                "finding_count": finding_count,
                "status": status,
            }
            with transaction(db, immediate=True):
                db.execute(
                    """
                    UPDATE run SET status=?, finished_at=?, summary_json=?
                    WHERE run_id=?
                    """,
                    (
                        status, _now(),
                        json.dumps(summary, sort_keys=True, separators=(",", ":")),
                        run_id,
                    ),
                )
            return PipelineResult(
                run_id=run_id,
                status=status,
                workspace=workspace,
                run_directory=run_paths.directory,
                database_path=database_path,
                source_counts=counts,
                observation_count=observation_count,
                entity_count=entity_count,
                relationship_count=relationship_count,
                finding_count=finding_count,
            )
    except Exception as exc:
        try:
            state_now = json.loads(run_paths.state.read_text(encoding="utf-8"))
            if state_now.get("status") not in {"completed", "partial", "failed", "cancelled"}:
                finalize_run(run_paths, "failed")
            with transaction(db, immediate=True):
                db.execute(
                    "UPDATE run SET status='failed', finished_at=? WHERE run_id=?",
                    (_now(), run_id),
                )
        except Exception:
            pass
        if isinstance(exc, (PipelineError, PersistenceError, RunError)):
            raise
        raise PipelineError("The FII pipeline failed; inspect the run state and source diagnostics.") from exc
    finally:
        db.close()
