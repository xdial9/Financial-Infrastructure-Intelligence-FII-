# FII Data Model

**Status:** Proposed logical schema for the first SQLite implementation.  
**Canonical store:** SQLite.  
**Raw evidence:** Run-specific JSON/JSONL files referenced by database records.

## 1. Core rules

1. A source observation is immutable once committed.
2. Raw source records are retained when permitted, with a content hash and source reference.
3. An entity is a normalized subject, not proof of ownership or control.
4. A relationship is a claim connecting two entities and must cite one or more observations.
5. An inference remains an inference until authoritative evidence verifies it.
6. Confidence and verification state are separate concepts.
7. A new run creates new observations; it does not overwrite the prior run.
8. Deduplication must preserve all source references and timestamps.
9. No database row should require storing secrets or unnecessary personal/financial data.

## 2. Identifiers and timestamps

- Primary IDs: UUID strings.
- Timestamps: ISO 8601 UTC strings.
- Hashes: lowercase SHA-256 hex strings.
- Stable source IDs: lowercase namespaced identifiers, e.g. `ct_logs`, `rdap`, `official_corporate_web`.
- Domain normalization: lowercase IDNA hostname without scheme, path, port or trailing dot.
- URLs retain original form as evidence and may also have a normalized comparison form.

## 3. Tables

### engagement

One authorized research scope.

| Column | Type | Rule |
|---|---|---|
| engagement_id | TEXT PK | UUID |
| slug | TEXT UNIQUE NOT NULL | Filesystem-safe |
| display_name | TEXT NOT NULL | Operator-facing |
| organization_name | TEXT | Optional |
| config_path | TEXT NOT NULL | Workspace-relative |
| scope_json | TEXT NOT NULL | Exact approved identifiers and boundaries |
| authorization_reference | TEXT | Customer approval/contract reference; no confidential contract text |
| created_at | TEXT NOT NULL | UTC |
| updated_at | TEXT NOT NULL | UTC |
| status | TEXT NOT NULL | active, paused, archived |

### run

One execution of the pipeline.

| Column | Type | Rule |
|---|---|---|
| run_id | TEXT PK | UUID |
| engagement_id | TEXT FK | Required |
| started_at | TEXT NOT NULL | UTC |
| finished_at | TEXT | UTC |
| status | TEXT NOT NULL | pending, running, completed, partial, failed, interrupted, cancelled |
| config_digest | TEXT NOT NULL | SHA-256 of effective sanitized config |
| software_version | TEXT NOT NULL | FII version |
| scope_digest | TEXT NOT NULL | SHA-256 of canonical scope |
| operator_label | TEXT | Optional, non-sensitive |
| summary_json | TEXT | Final counters and output references |

### stage_attempt

Append-only execution history for each pipeline stage.

| Column | Type | Rule |
|---|---|---|
| attempt_id | TEXT PK | UUID |
| run_id | TEXT FK | Required |
| stage_id | TEXT NOT NULL | Stable stage name |
| attempt_number | INTEGER NOT NULL | Starts at 1 |
| status | TEXT NOT NULL | pending, running, success, partial, failed, timed_out, cancelled, skipped |
| input_digest | TEXT | Fingerprint of stage inputs |
| started_at | TEXT | UTC |
| finished_at | TEXT | UTC |
| output_manifest_path | TEXT | Run-relative |
| error_code | TEXT | Stable machine-readable code |
| error_summary | TEXT | Sanitized diagnostic |

Unique key: (run_id, stage_id, attempt_number).

### source_definition

The configured source catalog for an FII release.

| Column | Type | Rule |
|---|---|---|
| source_id | TEXT PK | Stable ID |
| name | TEXT NOT NULL | Display name |
| adapter_version | TEXT NOT NULL | Semantic version |
| source_class | TEXT NOT NULL | public_api, public_dataset, targeted_public_web, customer_supplied, external_tool |
| documentation_url | TEXT | Source documentation |
| terms_url | TEXT | Terms/policy reference |
| requires_credentials | INTEGER NOT NULL | 0/1 |
| default_enabled | INTEGER NOT NULL | 0/1 |

### source_execution

One source's attempt within a run.

| Column | Type | Rule |
|---|---|---|
| source_execution_id | TEXT PK | UUID |
| run_id | TEXT FK | Required |
| source_id | TEXT FK | Required |
| attempt_number | INTEGER NOT NULL | Starts at 1 |
| status | TEXT NOT NULL | success, partial, failed, timed_out, skipped, cancelled |
| started_at | TEXT | UTC |
| finished_at | TEXT | UTC |
| records_received | INTEGER NOT NULL DEFAULT 0 | Count |
| records_accepted | INTEGER NOT NULL DEFAULT 0 | Count |
| raw_manifest_path | TEXT | Run-relative |
| configuration_digest | TEXT | No secrets |
| error_code | TEXT | Stable code |
| error_summary | TEXT | Sanitized |

Unique key: (run_id, source_id, attempt_number).

### observation

A normalized source-backed fact.

| Column | Type | Rule |
|---|---|---|
| observation_id | TEXT PK | UUID |
| run_id | TEXT FK | Required |
| source_execution_id | TEXT FK | Required |
| subject_entity_id | TEXT | Nullable until entity resolution |
| observation_type | TEXT NOT NULL | e.g. domain_seen, certificate_seen, rdap_record, vendor_documentation |
| observed_value | TEXT NOT NULL | Canonical value or JSON |
| observed_at | TEXT | Source event time when known |
| collected_at | TEXT NOT NULL | FII collection time |
| source_url | TEXT | Evidence URL |
| raw_evidence_path | TEXT | Run-relative |
| raw_sha256 | TEXT | Hash of raw record/object |
| confidence | REAL | 0.0–1.0, only when meaningful |
| verification_state | TEXT NOT NULL | observed, corroborated, inferred, unverified, rejected |
| attributes_json | TEXT NOT NULL DEFAULT '{}' | Source-specific attributes |

### entity

A canonical organization, domain, hostname, IP, ASN, certificate, application, vendor, public API/documentation resource or other supported subject.

| Column | Type | Rule |
|---|---|---|
| entity_id | TEXT PK | UUID |
| entity_type | TEXT NOT NULL | Controlled vocabulary |
| canonical_key | TEXT NOT NULL | Type-aware normalized key |
| display_name | TEXT NOT NULL | Human-readable |
| created_at | TEXT NOT NULL | UTC |
| updated_at | TEXT NOT NULL | UTC |
| attributes_json | TEXT NOT NULL DEFAULT '{}' | Non-sensitive metadata |

Unique key: (entity_type, canonical_key).

### entity_identifier

Alternative identifiers and names for an entity.

| Column | Type | Rule |
|---|---|---|
| identifier_id | TEXT PK | UUID |
| entity_id | TEXT FK | Required |
| identifier_type | TEXT NOT NULL | domain, legal_name, brand, registry_id, package_id, etc. |
| identifier_value | TEXT NOT NULL | Normalized |
| source_observation_id | TEXT FK | Evidence supporting identifier |
| first_seen_at | TEXT | UTC |
| last_seen_at | TEXT | UTC |

Unique key: (entity_id, identifier_type, identifier_value).

### relationship

A typed, evidence-backed edge between two entities.

| Column | Type | Rule |
|---|---|---|
| relationship_id | TEXT PK | UUID |
| subject_entity_id | TEXT FK | Required |
| predicate | TEXT NOT NULL | Controlled vocabulary |
| object_entity_id | TEXT FK | Required |
| verification_state | TEXT NOT NULL | observed, corroborated, inferred, unverified, rejected |
| confidence | REAL | 0.0–1.0 |
| rationale | TEXT | Analyst-readable explanation |
| rule_id | TEXT | Correlation rule |
| rule_version | TEXT | Correlation rule version |
| first_seen_at | TEXT | UTC |
| last_seen_at | TEXT | UTC |

No self-relationships. Do not merge different relationship assertions merely because they share endpoints.

### relationship_evidence

Evidence supporting or contradicting a relationship.

| Column | Type | Rule |
|---|---|---|
| relationship_id | TEXT FK | Required |
| observation_id | TEXT FK | Required |
| evidence_role | TEXT NOT NULL | supports, contradicts, context |

Composite primary key: (relationship_id, observation_id, evidence_role).

### finding

An analyst-facing research lead or reportable finding.

| Column | Type | Rule |
|---|---|---|
| finding_id | TEXT PK | UUID |
| run_id | TEXT FK | Required |
| finding_type | TEXT NOT NULL | Controlled category |
| title | TEXT NOT NULL | Concise |
| description | TEXT NOT NULL | Evidence-based |
| priority | TEXT | Informational, low, medium, high; not automatic vulnerability severity |
| confidence | REAL | 0.0–1.0 |
| verification_state | TEXT NOT NULL | candidate, analyst_reviewed, verified, rejected |
| disposition | TEXT | accepted, needs_research, false_positive, not_applicable |
| created_at | TEXT NOT NULL | UTC |
| updated_at | TEXT NOT NULL | UTC |

### finding_evidence

Connects a finding to its supporting observations and relationships.

| Column | Type | Rule |
|---|---|---|
| finding_id | TEXT FK | Required |
| observation_id | TEXT FK | Nullable |
| relationship_id | TEXT FK | Nullable |
| evidence_role | TEXT NOT NULL | supports, contradicts, context |

Exactly one of observation_id or relationship_id is populated.

## 4. Indexes

Create indexes for:
- run(engagement_id, started_at)
- stage_attempt(run_id, stage_id, attempt_number)
- source_execution(run_id, source_id)
- observation(run_id, observation_type)
- observation(subject_entity_id)
- observation(raw_sha256)
- entity(entity_type, canonical_key)
- entity_identifier(identifier_type, identifier_value)
- relationship(subject_entity_id, predicate)
- relationship(object_entity_id, predicate)
- finding(run_id, verification_state, priority)

## 5. Storage separation

Database:
`engagements/<slug>/database/fii.sqlite3`

Raw records:
`engagements/<slug>/runs/<run_id>/raw/<source_id>/`

Derived normalized exports:
`engagements/<slug>/runs/<run_id>/normalized/`

Reports:
`engagements/<slug>/runs/<run_id>/reports/`

Do not put API keys, passwords, customer tokens or secrets in SQLite, source JSON, exports or Git.

## 6. Migration policy

- Use numbered SQL migrations.
- Store schema version in a metadata table.
- Migrations are additive where practical.
- Back up the SQLite database before a migration.
- Refuse to run if the database schema is newer than the application supports.
- Never silently rebuild or delete the database.
