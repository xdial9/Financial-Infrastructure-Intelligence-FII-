# Block 09 — Relationship correlation and analyst review

Branch: build/block-09-relationship-correlation-analyst-review  
Base branch: build/block-08-normalization-entity-resolution  
Base commit: c23c18db3241dfce81d7ae70b74908d32c8722be

## Scope

Block 09 adds typed, evidence-linked relationship proposals and an append-only analyst disposition history. It does not perform active testing, invoke discovered API routes, execute JavaScript, authenticate to provider systems, or infer that a vendor reference is an operational integration.

## Relationship rules

Migration 0003 installs a versioned rule registry:

- `domain_has_nameserver`: an RDAP domain object explicitly lists a hostname as a nameserver.
- `website_references_vendor`: static HTML/JavaScript contains a vendor reference. It does not establish use, account validation or operational integration.
- `website_references_api_endpoint`: static source contains an API route/method reference. The route is not invoked or validated.
- `website_references_api_documentation`: static source contains a documentation reference. The referenced documentation is not necessarily fetched.

Each rule fixes allowed subject/object entity types, source observation type, predicate, version, default evidence state and a conservative base confidence. Invalid endpoint types, unsupported observation types, observations from another run, endpoint mismatches and unanchored evidence are rejected.

## Evidence and corroboration

Every relationship has at least one supporting observation. Supporting, contradicting and context evidence are stored separately in `relationship_evidence`; contradictions are never overwritten.

Corroboration requires supporting evidence from at least two distinct source definitions, not merely two executions of one source. Corroboration is not assigned when any contradicting evidence is attached. A contradictory assertion becomes `unverified`, with the conflicting evidence retained. Confidence is a deterministic rule score, not a probability; its rationale records the evidence counts and limits.

A static vendor/API/auth marker remains a reference observation. In particular, a Plaid string is not evidence that Plaid is actively integrated, that an account can be validated, or that an institution has a working Plaid connection.

## Analyst review

The review API supports `accepted`, `rejected` and `needs_research`. Each review stores reviewer label, rationale, prior/resulting evidence state and timestamp. Review history is append-only at the database level.

Acceptance records analyst disposition but does not upgrade an observed or inferred relationship to corroborated/verified. Rejection marks the relationship rejected. `needs_research` remains in the review queue. No entity merge or identity reassignment is performed.

## Verification

GitHub Actions CI is the verification source for this connector-authored branch. Tests use temporary SQLite databases and synthetic observations/entities only. No live RDAP, GLEIF, website, vendor or financial-institution endpoints are contacted. No local test result is claimed.

## Deferred

- Automatic multi-stage relationship correlation orchestration.
- Analyst UI and reviewer identity/authentication integration.
- Entity merge/alias operations and merge audit.
- Finding generation and report publication.
- Broader source-specific predicates beyond the fixed initial rule registry.
