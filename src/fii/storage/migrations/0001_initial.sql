-- FII canonical evidence schema, migration 0001.
-- Table names follow docs/architecture/DATA_MODEL.md.

CREATE TABLE engagement (
    engagement_id TEXT PRIMARY KEY CHECK (length(engagement_id) = 36),
    slug TEXT NOT NULL UNIQUE CHECK (length(trim(slug)) > 0),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    organization_name TEXT,
    config_path TEXT NOT NULL CHECK (length(trim(config_path)) > 0),
    scope_json TEXT NOT NULL CHECK (length(trim(scope_json)) > 0),
    authorization_reference TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'archived'))
);

CREATE TABLE run (
    run_id TEXT PRIMARY KEY CHECK (length(run_id) = 36),
    engagement_id TEXT NOT NULL REFERENCES engagement(engagement_id) ON DELETE RESTRICT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'running', 'completed', 'partial', 'failed',
                   'interrupted', 'cancelled')
    ),
    config_digest TEXT NOT NULL CHECK (
        length(config_digest) = 64 AND config_digest NOT GLOB '*[^0-9a-f]*'
    ),
    software_version TEXT NOT NULL,
    scope_digest TEXT NOT NULL CHECK (
        length(scope_digest) = 64 AND scope_digest NOT GLOB '*[^0-9a-f]*'
    ),
    operator_label TEXT,
    summary_json TEXT,
    UNIQUE (run_id, engagement_id)
);

CREATE TABLE stage_attempt (
    attempt_id TEXT PRIMARY KEY CHECK (length(attempt_id) = 36),
    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE RESTRICT,
    stage_id TEXT NOT NULL CHECK (length(trim(stage_id)) > 0),
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'running', 'success', 'partial', 'failed',
                   'timed_out', 'cancelled', 'skipped', 'interrupted')
    ),
    input_digest TEXT CHECK (
        input_digest IS NULL OR (
            length(input_digest) = 64 AND input_digest NOT GLOB '*[^0-9a-f]*'
        )
    ),
    started_at TEXT,
    finished_at TEXT,
    output_manifest_path TEXT,
    error_code TEXT,
    error_summary TEXT,
    UNIQUE (run_id, stage_id, attempt_number)
);

CREATE TABLE source_definition (
    source_id TEXT PRIMARY KEY CHECK (
        length(trim(source_id)) > 0 AND source_id = lower(source_id)
    ),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    adapter_version TEXT NOT NULL,
    source_class TEXT NOT NULL CHECK (
        source_class IN ('public_api', 'public_dataset', 'targeted_public_web',
                         'customer_supplied', 'external_tool')
    ),
    documentation_url TEXT,
    terms_url TEXT,
    requires_credentials INTEGER NOT NULL DEFAULT 0 CHECK (requires_credentials IN (0, 1)),
    default_enabled INTEGER NOT NULL DEFAULT 0 CHECK (default_enabled IN (0, 1))
);

CREATE TABLE source_execution (
    source_execution_id TEXT PRIMARY KEY CHECK (length(source_execution_id) = 36),
    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE RESTRICT,
    source_id TEXT NOT NULL REFERENCES source_definition(source_id) ON DELETE RESTRICT,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    status TEXT NOT NULL CHECK (
        status IN ('success', 'partial', 'failed', 'timed_out', 'skipped', 'cancelled')
    ),
    started_at TEXT,
    finished_at TEXT,
    records_received INTEGER NOT NULL DEFAULT 0 CHECK (records_received >= 0),
    records_accepted INTEGER NOT NULL DEFAULT 0 CHECK (records_accepted >= 0),
    raw_manifest_path TEXT,
    configuration_digest TEXT CHECK (
        configuration_digest IS NULL OR (
            length(configuration_digest) = 64
            AND configuration_digest NOT GLOB '*[^0-9a-f]*'
        )
    ),
    error_code TEXT,
    error_summary TEXT,
    UNIQUE (run_id, source_id, attempt_number),
    UNIQUE (source_execution_id, run_id)
);

CREATE TABLE entity (
    entity_id TEXT PRIMARY KEY CHECK (length(entity_id) = 36),
    entity_type TEXT NOT NULL CHECK (length(trim(entity_type)) > 0),
    canonical_key TEXT NOT NULL CHECK (length(trim(canonical_key)) > 0),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (entity_type, canonical_key)
);

CREATE TABLE observation (
    observation_id TEXT PRIMARY KEY CHECK (length(observation_id) = 36),
    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE RESTRICT,
    source_execution_id TEXT NOT NULL,
    subject_entity_id TEXT REFERENCES entity(entity_id) ON DELETE RESTRICT,
    observation_type TEXT NOT NULL CHECK (length(trim(observation_type)) > 0),
    observed_value TEXT NOT NULL,
    observed_at TEXT,
    collected_at TEXT NOT NULL,
    source_url TEXT,
    raw_evidence_path TEXT,
    raw_sha256 TEXT CHECK (
        raw_sha256 IS NULL OR (
            length(raw_sha256) = 64 AND raw_sha256 NOT GLOB '*[^0-9a-f]*'
        )
    ),
    confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0.0 AND 1.0),
    verification_state TEXT NOT NULL CHECK (
        verification_state IN ('observed', 'corroborated', 'inferred',
                               'unverified', 'rejected')
    ),
    attributes_json TEXT NOT NULL DEFAULT '{}',
    deduplication_key TEXT,
    FOREIGN KEY (source_execution_id, run_id)
        REFERENCES source_execution(source_execution_id, run_id) ON DELETE RESTRICT,
    UNIQUE (observation_id, run_id)
);

CREATE TABLE observation_source_link (
    observation_id TEXT NOT NULL,
    source_execution_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    provenance_role TEXT NOT NULL CHECK (
        provenance_role IN ('primary', 'corroborating', 'contradicting', 'context')
    ),
    PRIMARY KEY (observation_id, source_execution_id),
    FOREIGN KEY (observation_id, run_id)
        REFERENCES observation(observation_id, run_id) ON DELETE RESTRICT,
    FOREIGN KEY (source_execution_id, run_id)
        REFERENCES source_execution(source_execution_id, run_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX idx_observation_one_primary_source
    ON observation_source_link(observation_id)
    WHERE provenance_role = 'primary';

CREATE TRIGGER trg_observation_primary_source
AFTER INSERT ON observation
BEGIN
    INSERT INTO observation_source_link (
        observation_id, source_execution_id, run_id, provenance_role
    ) VALUES (
        NEW.observation_id, NEW.source_execution_id, NEW.run_id, 'primary'
    );
END;

CREATE TABLE entity_identifier (
    identifier_id TEXT PRIMARY KEY CHECK (length(identifier_id) = 36),
    entity_id TEXT NOT NULL REFERENCES entity(entity_id) ON DELETE RESTRICT,
    identifier_type TEXT NOT NULL CHECK (length(trim(identifier_type)) > 0),
    identifier_value TEXT NOT NULL CHECK (length(trim(identifier_value)) > 0),
    source_observation_id TEXT REFERENCES observation(observation_id) ON DELETE RESTRICT,
    first_seen_at TEXT,
    last_seen_at TEXT,
    UNIQUE (entity_id, identifier_type, identifier_value)
);

CREATE TABLE relationship (
    relationship_id TEXT PRIMARY KEY CHECK (length(relationship_id) = 36),
    subject_entity_id TEXT NOT NULL REFERENCES entity(entity_id) ON DELETE RESTRICT,
    predicate TEXT NOT NULL CHECK (length(trim(predicate)) > 0),
    object_entity_id TEXT NOT NULL REFERENCES entity(entity_id) ON DELETE RESTRICT,
    verification_state TEXT NOT NULL CHECK (
        verification_state IN ('observed', 'corroborated', 'inferred',
                               'unverified', 'rejected')
    ),
    confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0.0 AND 1.0),
    rationale TEXT,
    rule_id TEXT,
    rule_version TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT,
    CHECK (subject_entity_id <> object_entity_id)
);

CREATE TABLE relationship_evidence (
    relationship_id TEXT NOT NULL REFERENCES relationship(relationship_id) ON DELETE RESTRICT,
    observation_id TEXT NOT NULL REFERENCES observation(observation_id) ON DELETE RESTRICT,
    evidence_role TEXT NOT NULL CHECK (
        evidence_role IN ('supports', 'contradicts', 'context')
    ),
    PRIMARY KEY (relationship_id, observation_id, evidence_role)
);

CREATE TABLE finding (
    finding_id TEXT PRIMARY KEY CHECK (length(finding_id) = 36),
    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE RESTRICT,
    finding_type TEXT NOT NULL CHECK (length(trim(finding_type)) > 0),
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    priority TEXT CHECK (
        priority IS NULL OR priority IN ('informational', 'low', 'medium', 'high')
    ),
    confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0.0 AND 1.0),
    verification_state TEXT NOT NULL CHECK (
        verification_state IN ('candidate', 'analyst_reviewed', 'verified', 'rejected')
    ),
    disposition TEXT CHECK (
        disposition IS NULL OR disposition IN (
            'accepted', 'needs_research', 'false_positive', 'not_applicable'
        )
    ),
    rationale TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (finding_id, run_id)
);

CREATE TABLE finding_evidence (
    finding_evidence_id TEXT PRIMARY KEY CHECK (length(finding_evidence_id) = 36),
    finding_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    observation_id TEXT,
    relationship_id TEXT,
    evidence_role TEXT NOT NULL CHECK (
        evidence_role IN ('supports', 'contradicts', 'context')
    ),
    CHECK ((observation_id IS NOT NULL) <> (relationship_id IS NOT NULL)),
    FOREIGN KEY (finding_id, run_id)
        REFERENCES finding(finding_id, run_id) ON DELETE RESTRICT,
    FOREIGN KEY (observation_id, run_id)
        REFERENCES observation(observation_id, run_id) ON DELETE RESTRICT,
    FOREIGN KEY (relationship_id)
        REFERENCES relationship(relationship_id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX idx_finding_observation_evidence
    ON finding_evidence(finding_id, observation_id, evidence_role)
    WHERE observation_id IS NOT NULL;

CREATE UNIQUE INDEX idx_finding_relationship_evidence
    ON finding_evidence(finding_id, relationship_id, evidence_role)
    WHERE relationship_id IS NOT NULL;

CREATE TRIGGER trg_finding_relationship_requires_evidence
BEFORE INSERT ON finding_evidence
WHEN NEW.relationship_id IS NOT NULL
 AND NOT EXISTS (
     SELECT 1
     FROM relationship_evidence
     WHERE relationship_id = NEW.relationship_id
 )
BEGIN
    SELECT RAISE(ABORT, 'finding relationship evidence must reference an evidence-backed relationship');
END;

CREATE TRIGGER trg_finding_relationship_update_requires_evidence
BEFORE UPDATE ON finding_evidence
WHEN NEW.relationship_id IS NOT NULL
 AND NOT EXISTS (
     SELECT 1
     FROM relationship_evidence
     WHERE relationship_id = NEW.relationship_id
 )
BEGIN
    SELECT RAISE(ABORT, 'finding relationship evidence must reference an evidence-backed relationship');
END;

CREATE INDEX idx_run_engagement_started
    ON run(engagement_id, started_at);

CREATE INDEX idx_stage_attempt_run_stage
    ON stage_attempt(run_id, stage_id, attempt_number);

CREATE INDEX idx_source_execution_run_source
    ON source_execution(run_id, source_id);

CREATE INDEX idx_observation_run_type
    ON observation(run_id, observation_type);

CREATE INDEX idx_observation_subject_entity
    ON observation(subject_entity_id);

CREATE INDEX idx_observation_raw_sha256
    ON observation(raw_sha256);

CREATE UNIQUE INDEX idx_observation_run_deduplication
    ON observation(run_id, deduplication_key)
    WHERE deduplication_key IS NOT NULL;

CREATE INDEX idx_entity_identifier_type_value
    ON entity_identifier(identifier_type, identifier_value);

CREATE INDEX idx_relationship_subject_predicate
    ON relationship(subject_entity_id, predicate);

CREATE INDEX idx_relationship_object_predicate
    ON relationship(object_entity_id, predicate);

CREATE INDEX idx_finding_run_state_priority
    ON finding(run_id, verification_state, priority);
