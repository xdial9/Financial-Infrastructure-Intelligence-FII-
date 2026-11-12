-- FII relationship correlation and analyst review, migration 0003.

CREATE TABLE relationship_rule_registry (
    rule_id TEXT PRIMARY KEY CHECK (length(trim(rule_id)) > 0),
    predicate TEXT NOT NULL CHECK (length(trim(predicate)) > 0),
    subject_entity_types_json TEXT NOT NULL,
    object_entity_types_json TEXT NOT NULL,
    observation_type TEXT NOT NULL CHECK (length(trim(observation_type)) > 0),
    default_state TEXT NOT NULL CHECK (
        default_state IN ('observed', 'inferred', 'unverified')
    ),
    base_confidence REAL NOT NULL CHECK (base_confidence BETWEEN 0.0 AND 1.0),
    description TEXT NOT NULL CHECK (length(trim(description)) > 0),
    rule_version TEXT NOT NULL CHECK (length(trim(rule_version)) > 0)
);

INSERT INTO relationship_rule_registry VALUES
('domain_has_nameserver', 'has_nameserver', '["domain"]', '["hostname"]',
 'rdap_nameserver', 'observed', 0.90,
 'An RDAP domain object explicitly lists the hostname as a nameserver. This is a registry observation, not proof of current DNS resolution.',
 '1.0.0'),
('website_references_vendor', 'references_vendor', '["organization","domain","hostname"]',
 '["vendor"]', 'integration_reference', 'observed', 0.55,
 'Static HTML/JavaScript text contains a vendor reference. This does not establish an active integration, account validation or operational use.',
 '1.0.0'),
('website_references_api_endpoint', 'references_api_endpoint',
 '["organization","domain","hostname"]', '["api_endpoint"]', 'api_endpoint',
 'observed', 0.70,
 'Static HTML/JavaScript analysis found an API route or method reference. The route has not been invoked or validated.',
 '1.0.0'),
('website_references_api_documentation', 'references_api_documentation',
 '["organization","domain","hostname"]', '["documentation_resource"]',
 'api_documentation_reference', 'observed', 0.70,
 'A public page or static source contains an API documentation reference. The referenced documentation has not necessarily been fetched.',
 '1.0.0');

CREATE TABLE relationship_review (
    review_id TEXT PRIMARY KEY CHECK (length(review_id) = 36),
    relationship_id TEXT NOT NULL
        REFERENCES relationship(relationship_id) ON DELETE RESTRICT,
    disposition TEXT NOT NULL CHECK (
        disposition IN ('accepted', 'rejected', 'needs_research')
    ),
    reviewer_label TEXT NOT NULL CHECK (length(trim(reviewer_label)) > 0),
    rationale TEXT NOT NULL CHECK (length(trim(rationale)) > 0),
    prior_verification_state TEXT NOT NULL CHECK (
        prior_verification_state IN ('observed', 'corroborated', 'inferred',
                                     'unverified', 'rejected')
    ),
    resulting_verification_state TEXT NOT NULL CHECK (
        resulting_verification_state IN ('observed', 'corroborated', 'inferred',
                                         'unverified', 'rejected')
    ),
    reviewed_at TEXT NOT NULL
);

CREATE INDEX idx_relationship_review_relationship_time
    ON relationship_review(relationship_id, reviewed_at);

CREATE INDEX idx_relationship_review_disposition_time
    ON relationship_review(disposition, reviewed_at);

CREATE TRIGGER trg_relationship_review_no_update
BEFORE UPDATE ON relationship_review
BEGIN
    SELECT RAISE(ABORT, 'relationship review history is append-only');
END;

CREATE TRIGGER trg_relationship_review_no_delete
BEFORE DELETE ON relationship_review
BEGIN
    SELECT RAISE(ABORT, 'relationship review history is append-only');
END;
