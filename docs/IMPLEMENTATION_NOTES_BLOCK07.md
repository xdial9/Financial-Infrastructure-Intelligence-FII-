# Block 07 — RDAP and official-source enrichment

Branch: build/block-07-rdap-official-source-enrichment  
Base branch: build/block-06-collector-contract-passive-sources  
Base commit: 90acdba46d19c521736a9e9ab941bd6d96a11af3  
Pull request: Draft PR #4 (opened after the implementation commit)

## Implemented source families

### RDAP — IANA bootstrap and authoritative domain record

- Stable source ID: rdap_domain.
- Accepts exactly one approved seed domain for each invocation.
- Live mode first retrieves IANA's domain RDAP bootstrap JSON, then finds the matching authority using the longest label-wise suffix per RFC 9224 and requests one /domain/{name} object from the selected HTTPS RDAP base URL.
- Rejects non-HTTPS, credential-bearing, custom-port and malformed bootstrap service URLs. The shared HTTP helper rejects redirects, applies timeouts/response limits, sends no cookies or authorization headers and does not retry.
- Emits domain registration, registry status, event-date, nameserver and registrar observations.
- Registrar name, handle and IANA registrar ID are retained when present. Registrar identity is not registrant identity.
- Registrant, administrative and technical contact/vCard data are not retained. Missing and redacted fields are omitted; a redaction indicator is recorded as informational metadata when present.
- A nameserver listed by RDAP is a registry observation, not proof of current DNS resolution or ownership of the nameserver's domain.

### GLEIF — Global LEI Index

- Stable source ID: gleif_lei.
- Accepts exactly one approved legal-entity name or 20-character LEI for each invocation.
- A name search retrieves one bounded page (default 10; adapter maximum 50); an LEI seed retrieves one record. The adapter does not paginate or follow relationship links.
- Emits legal-entity identifier, legal name, entity status, LEI registration status, jurisdiction, legal form and relationship-reference observations where those values are present.
- Name results carry candidate_match=true and match_method=name_search_candidate. An exact LEI input is marked exact_lei_lookup. Neither mode automatically creates an entity-resolution decision.
- Relationship IDs reported in the API response are retained as references only; there is no recursive fetch and no ownership relationship is created by the collector.
- Contact and street-address detail is excluded from retained evidence. Legal-address country may be retained as a jurisdictional hint.
- Entity status and registration status remain independent. Missing optional fields are omitted without invalidating an otherwise valid LEI record.

## Evidence and interpretation

- Both adapters use the Block 06 collector contract and content-addressed raw evidence store.
- RDAP retains the IANA bootstrap evidence plus a minimized RDAP domain payload. The original response digest is preserved separately from the retained payload digest.
- GLEIF retains a minimized JSON:API payload containing identifiers and legal-entity reference fields, with the original response digest preserved.
- Observations reference their retained evidence SHA-256 and source URL.
- RDAP registrars are not assumed to be registrants; nameservers are not treated as domain owners.
- GLEIF name search is candidate discovery, not definitive identity resolution. An LEI does not prove that an entity is a technology provider or that a product supports a particular account-validation capability.
- Missing or redacted fields are not interpreted as negative facts.

## Scope and coverage limitations

- RDAP coverage depends on IANA's current domain bootstrap registry and the fields published by each authoritative TLD registry. Privacy redaction and field availability vary. The adapter performs one lookup only and will surface an unavailable or non-conforming authority response rather than probing alternate registries.
- GLEIF covers entities with LEIs, not every legal business, trade name or institution. Legal names may be similar across jurisdictions. Parent/child relationship references depend on records reported into the Global LEI System and are not fetched or normalized in this block.
- Both providers may change field formats. Unknown fields are ignored; expected optional fields are treated as optional. Malformed top-level response structure is a source error.
- Operator review of current source documentation, usage terms and rate guidance is required before live collection.

## Verification

GitHub Actions results are recorded here after the Block 07 PR head has completed its Python 3.11/3.12/3.13 matrix and Ruff checks. Tests use synthetic fixtures and mocked HTTP only. No actual RDAP, IANA or GLEIF request is part of CI.

## Deliberately deferred

- Persistence of collector results into the Block 05 SQLite observation/source-execution tables and user-facing run/resume/collect orchestration.
- Full normalization, deduplication, entity resolution and relationship graph creation.
- Recursive GLEIF parent/child record retrieval, regulator-specific institution directories, SEC/FDIC/FFIEC adapters and additional official data sources.
- Historical RDAP/LEI change monitoring and bulk data synchronization.
- Automatic terms/licensing/robots review, live production collection and any endpoint validation or state-changing operation.
