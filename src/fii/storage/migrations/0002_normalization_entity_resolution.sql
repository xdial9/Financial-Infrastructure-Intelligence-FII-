-- FII canonical normalization and explainable entity resolution, migration 0002.

ALTER TABLE observation
    ADD COLUMN canonicalization_version TEXT NOT NULL DEFAULT 'legacy-v1';

CREATE TABLE entity_type_registry (
    entity_type TEXT PRIMARY KEY CHECK (
        length(trim(entity_type)) > 0 AND entity_type = lower(entity_type)
    ),
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    registry_version TEXT NOT NULL CHECK (length(trim(registry_version)) > 0)
);

CREATE TABLE identifier_type_registry (
    identifier_type TEXT PRIMARY KEY CHECK (
        length(trim(identifier_type)) > 0 AND identifier_type = lower(identifier_type)
    ),
    entity_type TEXT NOT NULL REFERENCES entity_type_registry(entity_type) ON DELETE RESTRICT,
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    normalization_rule TEXT NOT NULL CHECK (length(trim(normalization_rule)) > 0),
    resolution_strength TEXT NOT NULL CHECK (
        resolution_strength IN ('strong', 'weak')
    ),
    registry_version TEXT NOT NULL CHECK (length(trim(registry_version)) > 0)
);

CREATE TABLE observation_provenance (
    provenance_id TEXT PRIMARY KEY CHECK (length(provenance_id) = 36),
    observation_id TEXT NOT NULL,
    source_execution_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    provenance_role TEXT NOT NULL CHECK (
        provenance_role IN ('primary', 'context', 'corroborating', 'contradicting')
    ),
    source_url TEXT,
    raw_evidence_path TEXT,
    raw_sha256 TEXT NOT NULL CHECK (
        length(raw_sha256) = 64 AND raw_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    collected_at TEXT NOT NULL,
    observed_at TEXT,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (observation_id, run_id)
        REFERENCES observation(observation_id, run_id) ON DELETE RESTRICT,
    FOREIGN KEY (source_execution_id, run_id)
        REFERENCES source_execution(source_execution_id, run_id) ON DELETE RESTRICT,
    UNIQUE (observation_id, source_execution_id, raw_sha256)
);

CREATE TABLE entity_resolution_decision (
    decision_id TEXT PRIMARY KEY CHECK (length(decision_id) = 36),
    run_id TEXT NOT NULL REFERENCES run(run_id) ON DELETE RESTRICT,
    source_observation_id TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (
        outcome IN ('created', 'matched', 'candidate', 'ambiguous', 'conflict', 'skipped')
    ),
    proposed_entity_id TEXT REFERENCES entity(entity_id) ON DELETE RESTRICT,
    matched_entity_id TEXT REFERENCES entity(entity_id) ON DELETE RESTRICT,
    match_method TEXT NOT NULL CHECK (length(trim(match_method)) > 0),
    confidence REAL CHECK (confidence IS NULL OR confidence BETWEEN 0.0 AND 1.0),
    rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 0),
    rule_id TEXT NOT NULL CHECK (length(trim(rule_id)) > 0),
    rule_version TEXT NOT NULL CHECK (length(trim(rule_version)) > 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_observation_id, run_id)
        REFERENCES observation(observation_id, run_id) ON DELETE RESTRICT,
    UNIQUE (run_id, source_observation_id, rule_id, rule_version)
);

CREATE TABLE entity_resolution_candidate (
    candidate_id TEXT PRIMARY KEY CHECK (length(candidate_id) = 36),
    decision_id TEXT NOT NULL
        REFERENCES entity_resolution_decision(decision_id) ON DELETE RESTRICT,
    candidate_entity_id TEXT NOT NULL
        REFERENCES entity(entity_id) ON DELETE RESTRICT,
    match_method TEXT NOT NULL CHECK (length(trim(match_method)) > 0),
    similarity_score REAL NOT NULL CHECK (similarity_score BETWEEN 0.0 AND 1.0),
    rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 0),
    created_at TEXT NOT NULL,
    UNIQUE (decision_id, candidate_entity_id, match_method)
);

CREATE INDEX idx_observation_provenance_observation
    ON observation_provenance(observation_id, collected_at);

CREATE INDEX idx_observation_provenance_source_execution
    ON observation_provenance(source_execution_id, raw_sha256);

CREATE INDEX idx_identifier_registry_entity_type
    ON identifier_type_registry(entity_type, resolution_strength);

CREATE INDEX idx_entity_resolution_decision_run
    ON entity_resolution_decision(run_id, outcome, created_at);

CREATE INDEX idx_entity_resolution_decision_observation
    ON entity_resolution_decision(source_observation_id);

CREATE INDEX idx_entity_resolution_candidate_entity
    ON entity_resolution_candidate(candidate_entity_id, similarity_score);
