# FII Pipeline Contracts

**Status:** Proposed implementation contract.  
**Execution:** Sequential; one stage at a time and one source at a time.

## 1. Run lifecycle

Run statuses:
- `pending`: created but not started.
- `running`: active pipeline.
- `completed`: all required stages and enabled sources completed successfully.
- `partial`: pipeline completed but one or more optional sources/stages were incomplete.
- `failed`: fatal failure prevented a valid report.
- `interrupted`: operator interruption or process termination was recorded.
- `cancelled`: operator explicitly cancelled before completion.

Stage and source statuses:
- `pending`
- `running`
- `success`
- `partial`
- `failed`
- `timed_out`
- `skipped`
- `cancelled`

A stale `running` entry found on restart is not considered success. It is reconciled as interrupted/unknown and retried according to its input fingerprint.

## 2. Stage order

1. load_config
2. validate_scope
3. prepare_workspace
4. preflight_sources
5. collect_sources
6. normalize_observations
7. deduplicate_observations
8. resolve_entities
9. correlate_relationships
10. analyze_intelligence
11. generate_reports
12. reconcile_run

A stage receives explicit input objects and returns a structured result. It must not use implicit global state or start later stages itself.

## 3. Continuation policy

### Fatal; stop immediately
- Invalid configuration.
- Scope validation failure.
- Database integrity or persistence failure.
- Unable to create a safe run directory.
- Required source configuration missing.
- Checkpoint write failure.
- Detected path traversal or workspace containment violation.

### Non-fatal; record and continue
- Optional source unavailable.
- API rate limit after bounded retries.
- Source returns no records.
- A source's schema changes but other collectors remain valid.
- A single public page is unavailable.
- Optional enrichment is skipped.

If a required source fails, the run may continue only when the engagement configuration explicitly marks downstream analysis as useful without it; final status must be partial and the report must disclose the gap.

## 4. Resume fingerprint

A stage may be skipped on resume only when all of the following match:
- stage ID and implementation version;
- effective configuration digest;
- scope digest;
- input manifest digest;
- prerequisite stage outputs;
- collector version for source stages.

If any fingerprint changes, that stage and dependent stages must be rerun. Existing outputs are preserved; new attempt-specific outputs are created.

## 5. Attempt and output naming

- Every run gets a UUID run_id.
- Every stage and source execution has an increasing attempt number.
- Attempt outputs are unique; never truncate an existing attempt file.
- A stage publishes its output manifest only after successful validation.
- Reports are written to a temporary file in the destination directory, flushed, fsynced where practical, then atomically replaced.
- Raw evidence is retained before normalization so downstream failures can be retried without recollecting.

## 6. Workspace locking

Use an interprocess lock for operations that mutate a single engagement's SQLite database, state or report publication. Follow APK Workbench's proven workspace lock pattern. A second run against the same engagement must fail clearly or wait according to an explicit CLI option; do not allow two writers to interleave.

## 7. Timeouts and retries

- Set connect/read/overall timeouts on each network call.
- Retry only transient failures, with a small bounded retry count.
- Honor Retry-After where provided.
- Do not retry permanent authorization, terms, or invalid-scope failures.
- Log retry count and final outcome.
- Subprocess adapters use argument arrays, never shell command strings.
- A subprocess has an explicit timeout and bounded output size.
- Process groups are terminated on timeout or cancellation.

## 8. Checkpointing and interruption

After each source and major stage:
1. Persist attempt status.
2. Persist source/stage counters.
3. Persist output-manifest references.
4. Update run progress.

On Ctrl+C:
- stop starting new source work;
- allow current operation to close or terminate it cleanly;
- record current stage/source as cancelled or interrupted;
- preserve raw output and logs;
- save a run summary;
- exit with status 130.

Do not delete partial artifacts automatically.

## 9. Output and exit codes

Suggested exit codes:
- 0: completed successfully.
- 1: fatal configuration, scope, persistence or pipeline error.
- 2: partial run (optional sources failed; valid partial report produced).
- 130: interrupted by operator.

The final run summary must include run ID, engagement, timestamps, status, source counts, observation counts, entities, relationships, findings, skipped/failed sources, report paths and limitations.

## 10. Reconciliation

`fii reconcile --run-id <id>` compares the run manifest and database:
- every configured source has an execution row;
- every source result path exists or has an explicit missing status;
- every normalized observation links to a source execution;
- every relationship has evidence references;
- every finding has evidence references or an explicit analyst rationale;
- report files match the final report manifest;
- no stage marked successful is missing its output manifest.

The reconciler reports inconsistencies; it never silently rewrites evidence or changes an error into success.

## 11. Collector interface and evidence semantics

A collector is a fixed, versioned adapter implementing one operation:

```python
definition: SourceDefinition
collect(context: CollectionContext) -> CollectionResult
```

The context carries the run ID, approved seed domains, approved organization-name/LEI seeds, optional fixture location, raw-evidence directory, source URL and bounded input-size settings. The result carries source status, timestamps, received/accepted counters, immutable raw-evidence references, typed observations and sanitized diagnostics.

Collector rules:
- Sources run sequentially. A collector cannot start another collector or a later pipeline stage.
- Every observation references a raw-evidence SHA-256 and records its source URL, collection time and detection metadata.
- Collectors report observed facts. Static API routes, authentication markers and provider references must not be promoted into verified relationships by the collector.
- The fixed registry is explicit. Future provider APIs and external-tool adapters implement the same contract; arbitrary runtime plugin loading is not part of the MVP.
- Website HTML/JavaScript analysis is static text analysis. The fixture adapter does not execute scripts or fetch script/source-map references.
- Likely credential values are redacted from saved web text. The retained evidence SHA-256 and original input digest are both recorded; no secret value belongs in an observation, log or database row.
- Source parsing/unavailability errors produce failed or partial source results. Failure to write or safely reference raw evidence is a fatal persistence error and must propagate to the run controller.
- Raw evidence paths are private, content-addressed, relative to the run's raw directory and never overwrite an existing file.

- Live public-source retrieval is disabled by default. A caller must explicitly set `live_collection_approved=True` after source-specific terms, licensing, robots policy, limits and engagement scope have been reviewed.
- The shared HTTP helper permits HTTPS GET only, sends no cookies or authorization headers, refuses redirects, applies explicit timeout/response-size limits, and reports HTTP 429/Retry-After without automatic retries.
- The crt.live adapter makes one request for one approved seed domain and one page per invocation; it does not paginate or retry. Names outside the approved domain/subdomain are not retained.
- The public website snapshot adapter retrieves one approved HTTPS HTML page and a bounded number of same-scope JavaScript assets. It does not retrieve unapproved CDN assets, source maps, links or discovered API endpoints. All fetched JavaScript is parsed as text, never executed.
- Test suites mock the HTTP layer. CI must not contact real providers, websites or institutions.


### Block 07 enrichment adapters

- rdap_domain accepts exactly one approved seed domain. The live adapter retrieves IANA's DNS RDAP bootstrap JSON, selects the longest matching domain suffix per RFC 9224, then retrieves one domain object from the selected HTTPS service. It does not follow redirects, paginate or retry. Only registry status, event dates, nameserver names and registrar identity are retained. Registrant/admin/technical contact and vCard details are excluded.
- gleif_lei accepts exactly one approved organization name or 20-character LEI. Name-search results remain candidate matches. It retrieves one API page (default 10 records; adapter maximum 50) and does not auto-paginate or follow relationship links. Legal-entity identity and registration fields are emitted as observations; relationship identifiers remain source-reported references, not inferred relationships.
- GLEIF records may contain independent entity-status and LEI-registration-status values; preserve both. Missing optional data and redacted fields are omitted. A missing field is not evidence that the field's real-world value is absent.
- Both adapters retain content-addressed raw evidence with source-response digests and source URLs. RDAP response evidence is minimized to public infrastructure fields; GLEIF response evidence is minimized to legal-entity reference fields. No contact data is required for these enrichment goals.
- All live network requests require live_collection_approved=True. Tests use synthetic fixtures and mocked HTTP responses only.


### Block 08 normalization, deduplication and entity resolution

- Normalize source observations using a versioned, deterministic canonicalization contract. Preserve source values in provenance and source raw evidence; store canonical fact values and stable comparison keys.
- Deduplication keys include observation type, canonical value, source event timestamp when present and semantic scope attributes. Volatile query/provider metadata and transport URLs are not key material. Subject/scope discriminators (for example, parent domain and LEI) prevent unrelated observations from collapsing.
- One canonical fact stores one primary source row and retains every distinct source execution in \`observation_source_link\` plus each source-object hash/path/URL/timestamp/attributes in \`observation_provenance\`. Secondary source links begin as context. Do not automatically set verification_state=corroborated merely because deduplication found a second source.
- Contradictory values remain separate canonical observations. Deduplication never chooses a winner or overwrites a source observation.
- Entity and identifier types are drawn from the fixed, versioned registry. Strong identifiers resolve only the registry-matched entity type; weak name/brand/package identifiers create candidate references.
- Similar names never auto-merge. Exact legal-name matches are still candidates, with jurisdiction and source rationale. Conflicting exact identifiers create a conflict decision and leave existing subject assignments unchanged.
- Domain/hostname/IP/ASN identities are infrastructure entities; shared infrastructure is not evidence that two organizations are the same entity.
- Entity-resolution decisions persist rule/version, source observation, outcome and rationale. Candidate links are separately persisted for analyst review in Block 09.
- These operations are deterministic and offline. They make no network requests and do not alter raw source evidence.
