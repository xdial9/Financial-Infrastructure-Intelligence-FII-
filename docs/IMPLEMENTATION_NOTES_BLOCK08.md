# Block 08 — Normalization, deduplication and entity resolution

Branch: build/block-08-normalization-entity-resolution  
Base branch: build/block-07-rdap-official-source-enrichment  
Base commit: 4e2c04c05ec4875251eb2bcd4433010c64dbb1f5  
Pull request: Draft PR #5 (opened after the implementation commit)

## Implementation

### Canonical observations

- Version: observation-v1.
- Normalizes observation types and type-specific values including IDNA domains/hostnames, IP addresses, SHA-256 fingerprints, URLs and LEIs.
- Produces a stable SHA-256 deduplication key from a versioned canonical JSON representation.
- Key material includes observation type, canonical comparison value, source event timestamp when present, and semantic attributes that define subject/scope.
- Volatile collection metadata (provider label, request query, name-search match method and candidate flag) is excluded from the key. Source URL, raw digest and collected-at time are provenance, not fact identity.
- For source families where entity identity changes the meaning of a fact, identity remains a discriminator. GLEIF legal-name observations include the LEI; RDAP nameserver/status observations include the registered parent domain.
- Evidence paths must be safe normalized relative paths. Observations with malformed type/value/attributes fail normalization rather than silently entering the canonical store.

### Deduplication and evidence provenance

- Identical canonical keys in one run yield one observation row.
- Stable observation IDs are UUID5 values derived from run ID and canonical deduplication key.
- Source executions are retained in observation_source_link. Per-source raw hashes, paths, URLs, collected/event timestamps and source attributes are retained in observation_provenance.
- Primary selection and provenance ordering are deterministic by source execution ID and evidence identity.
- Secondary source links are marked context. Deduplication does not automatically promote verification_state to corroborated or infer independent provider ownership.
- Repeated persistence is idempotent. Conflicting values, event times or subject-scope attributes retain separate observation rows.
- Raw files and original source evidence are not modified by this stage.

### Entity and identifier registry

- Version: entity-registry-v1.
- Entity types: organization, vendor, domain, hostname, ip_address, autonomous_system, certificate, application, api_endpoint and documentation_resource.
- Strong identifier types: LEI, SEC CIK, Companies House number, domain, hostname, IP address, ASN and certificate SHA-256.
- Weak candidate identifier types: legal_name, brand_name and ecosystem-scoped package_id.
- Identifier types are bound to one entity type. For example, a domain identifier resolves a domain entity, not an organization. Shared hosting, nameservers and IP addresses cannot merge legal entities.
- Values use type-specific normalization (LEI uppercase; SEC CIK left-padded; Companies House uppercase; DNS IDNA/lowercase; IP compressed notation; ASN canonical AS-number).
- The code registry is persisted in the database and fails loudly if a registry definition changes without a registry-version change.

### Deterministic resolution

- Exact strong identifiers can create a canonical entity or attach a new observation to the one existing entity mapped to the identifier.
- Canonical entity identifiers are persisted with supporting source observation IDs and first/last-seen timestamps.
- A weak-name-only source observation creates an observation-anchored provisional entity. Exact or fuzzy name matches to existing entities are persisted as candidate links, with a deterministic similarity score, jurisdiction comparison and rationale.
- Name-only candidates never auto-merge, including exact normalized-name matches. Candidate outcome does not imply verified identity.
- When exact strong identifiers point to more than one entity, one identifier maps to multiple existing entities, or an existing subject assignment conflicts with the strong identifier, the resolver records a conflict and does not reassign the observation.
- Resolution decisions include source observation, rule ID/version, outcome, match method, confidence where justified and analyst-readable rationale.
- Candidate decisions are suitable for Block 09 review; this block does not implement analyst acceptance/rejection or destructive entity merges.

## Migration 0002

Adds:
- observation.canonicalization_version;
- entity_type_registry;
- identifier_type_registry;
- observation_provenance;
- entity_resolution_decision;
- entity_resolution_candidate;
- lookup indexes for provenance, registry, decisions and candidate entities.

Migration is additive; migration 0001 is unchanged. Existing observations retain canonicalization version legacy-v1 until reprocessed by a future explicit migration/stage. No records are rewritten during schema migration.

## Verification plan

GitHub Actions runs the full Python 3.11/3.12/3.13 test matrix and Ruff. Tests use temporary local SQLite databases and synthetic identifiers/observations only. No live RDAP, GLEIF, financial-institution, website or provider API requests are made.

## Coverage limits and deferred work

- Canonicalization rules are intentionally explicit and incomplete; unknown observation families use conservative Unicode/whitespace normalization rather than guessed domain or URL semantics.
- Strong identifier uniqueness is enforced by the resolver and ambiguity detection, not by a database-wide unique index, so legacy duplicate mappings can be represented and surfaced as conflicts instead of making migration fail.
- Fuzzy matching is a deterministic candidate generator, not a probabilistic identity model. Similarity scores are not confidence scores.
- No entity merge operation, alias redirection, analyst disposition UI, relationship correlation, or cross-run historical reconciliation is included.
- No source adapters are invoked by this stage. It operates only on already collected local observations and evidence references.
