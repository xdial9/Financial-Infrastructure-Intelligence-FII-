# FII — End-to-End Project Plan
## Financial Infrastructure Intelligence

**Repository:** xdial9/Financial-Infrastructure-Intelligence-FII-  
**Default branch:** main  
**Project type:** Python command-line intelligence collector and analyzer  
**Planning status:** Proposed architecture; implementation not yet started  
**Reference implementation style:** attached `automate.py` (University Audit)

---

## 1. Product definition

FII is a simple, sequential Python workflow that collects authorized and permitted public-source observations about a financial institution's external digital footprint and documented technology dependencies, then normalizes, correlates, analyzes, and reports the evidence.

The product is not a generic scanner. Its differentiator is evidence-linked relationship intelligence: what is observed, where it came from, when it was observed, how confident the relationship is, and what remains unverified.

### Primary users
- Red Team and threat-intelligence teams preparing explicitly authorized engagements.
- Security architecture and third-party risk teams.
- Researchers producing financial-sector infrastructure and dependency reports.

### Core user experience
One command, one clear sequence, visible progress, predictable files, resumable work, and a final report. Advanced controls should be available, but the default workflow should not require the operator to understand the internals.

---

## 2. Design principles from the University Audit script

Preserve the user's established implementation style:
- One straightforward Python entry point.
- Small functions with one responsibility.
- Linear sequential execution in `main()`.
- Standard-library HTTP, JSON, CSV, filesystem and subprocess handling where practical.
- External tools invoked with argument lists (never shell string concatenation).
- Explicit connect/read/overall timeouts.
- Clear progress messages with `flush=True`.
- Engagement-specific output directories.
- Raw JSON/JSONL plus analyst-friendly CSV and Markdown.
- State files written after each completed stage/item.
- Resume completed work and preserve prior/partial outputs.
- Per-source logs and a consolidated failure report.
- Graceful Ctrl+C; no deletion of existing output.
- Explicit confirmation before any active validation stage.

Avoid:
- Async/concurrent orchestration in MVP.
- A microservice architecture.
- A mandatory web interface.
- Complex task queues.
- Premature graph database infrastructure.
- Automatic exploitation, login attempts, credential collection, or unscoped active probing.

---

## 3. MVP scope

### Included
1. Engagement profile and scope validation.
2. Passive collection from selected public sources.
3. Optional documented APIs with configured credentials, stored outside the repository.
4. Source-specific raw evidence preservation.
5. Normalization into a common observation schema.
6. Deduplication without discarding provenance.
7. Organization, domain, certificate, ASN, vendor and application entity records.
8. Evidence-backed relationship correlation.
9. Confidence labels and analyst review queue.
10. Basic analysis and prioritization.
11. JSON, CSV and Markdown reports.
12. Logs, checkpoints, resume and failure handling.

### Explicitly deferred
- Active scanning or service interaction.
- Authenticated customer systems.
- Exploit validation.
- Production banking workflow testing.
- A web dashboard.
- Commercial multi-tenant SaaS.
- Neo4j or other graph database.
- AI-generated conclusions.
- Broad crawling outside approved source lists.

---

## 4. Sequential execution workflow

The default run should execute these stages in order:

`1. Load engagement`
→ `2. Validate scope`
→ `3. Prepare output`
→ `4. Collect sources`
→ `5. Normalize observations`
→ `6. Deduplicate`
→ `7. Resolve entities`
→ `8. Correlate relationships`
→ `9. Analyze and score`
→ `10. Generate reports`
→ `11. Write run summary`

### Stage 1 — Load engagement
Read a simple YAML or JSON engagement profile containing engagement name, organization identifiers, approved domains, permitted sources, collection date range, rate limits, and contact/reference metadata.

### Stage 2 — Validate scope
Normalize domains and URLs; reject malformed entries; show the exact approved domain set and source list; require operator confirmation before collection. Enforce an allowlist in every collector. Public availability alone is not authorization for active testing.

### Stage 3 — Prepare output
Create a per-engagement structure:
```
engagement-name/
  config/
  lists/
  raw/
    source-name/
  normalized/
  analysis/
  reports/
  logs/
  state/
```
Never overwrite earlier runs. Give each run a timestamped directory or unique run ID.

### Stage 4 — Collect sources
Run collectors sequentially, one source at a time. Each collector has a stable interface and returns raw records plus metadata.

Initial source families:
- Certificate Transparency observations.
- Passive DNS / DNS relationship datasets.
- RDAP and ASN / routing registry information.
- Publicly documented asset-intelligence APIs (optional credentials).
- Official corporate disclosures and subsidiary pages.
- Public vendor / partner documentation and status pages.
- Public developer portals and API documentation.
- Public mobile application metadata and store listings.
- Regulatory filings and official publications.

Scrapy is reserved for source-specific public-site extraction where a stable API or downloadable dataset is not available. Follow source terms, robots policies where applicable, rate limits, and data minimization.

### Stage 5 — Normalize
Convert source-specific records into a common observation schema. Keep the complete raw source output. Never replace a source value with an inferred value.

### Stage 6 — Deduplicate
Deduplicate canonical observations by stable keys while preserving all source references and observation timestamps. Distinguish repeated sightings from independent corroboration.

### Stage 7 — Resolve entities
Create canonical entities for organization, subsidiary, brand, domain, hostname, IP, ASN, certificate, application, vendor, public API/documentation endpoint, and external service.

Entity resolution must be explainable. Do not merge entities solely because names look similar.

### Stage 8 — Correlate relationships
Create typed edges such as:
- owns_or_operates (only with evidence)
- uses_vendor (only when documented/corroborated)
- resolves_to (DNS evidence)
- covered_by_certificate (certificate evidence)
- announced_by / documented_at (source relationship)
- associated_with (qualified, non-ownership association)
- historically_observed_as (dated relationship)

Every edge must link to one or more observations. Label inferred relationships explicitly.

### Stage 9 — Analyze and score
Produce deterministic, explainable findings:
- Newly observed assets.
- Historical changes.
- Unverified ownership relationships.
- Shared provider relationships.
- Missing or conflicting evidence.
- Potentially stale public assets (hypothesis only).
- External dependency concentration signals.
- Research leads requiring analyst review.

Do not label an asset vulnerable or exposed merely because it exists. Do not infer internal trust paths or payment workflows from public data alone.

### Stage 10 — Generate reports
Generate:
- `executive-summary.md`
- `asset-inventory.csv`
- `entities.json`
- `relationships.csv`
- `observations.jsonl`
- `analyst-review.csv`
- `source-register.csv`
- `changes.csv`
- `run-summary.json`

Reports must show dates, source references, confidence, verification status, limitations and scope.

### Stage 11 — Run summary
Record counts by source, records collected, normalized observations, deduplicated observations, entities, relationships, errors, skipped sources, elapsed time, and output paths.

---

## 5. Data model

### Engagement
`engagement_id`, `name`, `organization`, `scope_domains`, `approved_sources`, `authorization_reference`, `created_at`.

### Entity
`entity_id`, `entity_type`, `canonical_name`, `canonical_value`, `first_seen`, `last_seen`, `status`.

### Observation
`observation_id`, `run_id`, `source_id`, `observed_at`, `entity_type`, `value`, `raw_record_path`, `source_url`, `method`, `confidence`, `verification_status`.

### Relationship
`relationship_id`, `subject_entity_id`, `predicate`, `object_entity_id`, `observation_ids`, `confidence`, `verification_status`, `analyst_notes`.

### Source
`source_id`, `name`, `source_type`, `terms_url`, `rate_limit`, `enabled`, `configuration_reference`.

### Run state
`run_id`, `stage`, `item_key`, `status`, `started_at`, `finished_at`, `result_path`, `log_path`, `error`.

Use SQLite for the initial canonical store. Raw JSON files remain available for auditability and simple recovery. Add graph storage only if measured query needs justify it.

---

## 6. Suggested repository structure

```
FII/
  automate.py
  config.example.yaml
  requirements.txt
  README.md
  docs/
    PROJECT_CHARTER.md
    PROJECT_PLAN.md
    DATA_MODEL.md
    SOURCE_REGISTER.md
    REPORT_SPECIFICATION.md
    SECURITY_AND_SCOPE.md
  fii/
    __init__.py
    config.py
    scope.py
    sources.py
    normalize.py
    deduplicate.py
    entities.py
    correlate.py
    analyze.py
    report.py
    state.py
    utils.py
    collectors/
      __init__.py
      ct_logs.py
      passive_dns.py
      rdap.py
      corporate_web.py
      vendor_docs.py
      public_apis.py
      mobile_metadata.py
  tests/
    fixtures/
    test_config.py
    test_scope.py
    test_normalize.py
    test_deduplicate.py
    test_entities.py
    test_correlate.py
    test_report.py
```

Keep the first implementation smaller if a module is not yet needed. Do not create empty scaffolding for every future capability.

---

## 7. Technical stack

- Python 3.11+; confirm exact target version on the workstation.
- Standard library for orchestration, filesystem, JSON, CSV, subprocess, logging and SQLite.
- PyYAML only if YAML configuration is selected; JSON is a zero-dependency initial alternative.
- Scrapy only for targeted public-source crawling.
- Requests/httpx only if a collector's needs justify them; otherwise urllib keeps the dependency footprint low.
- SQLite for canonical local records.
- pytest for tests in the project virtual environment.
- Ruff and BasedPyright for code quality and type checking.
- NetworkX may be evaluated later for local graph analysis and export; not required for first collection/report slice.

Use a project virtual environment and a pinned dependency file. Store API keys in environment variables or a local ignored secrets file. Never commit credentials.

---

## 8. Reliability and operational requirements

- Explicit per-request and per-source timeouts.
- Bounded retries with backoff for transient errors and rate limits.
- Sequential collection by default.
- Per-source log files and clear error categories.
- Checkpoint after each source and each long-running item.
- Resume should skip only items marked completed with matching source/config fingerprints.
- Preserve old outputs and incomplete outputs; create attempt suffixes rather than overwriting.
- Atomic writes for state and final reports where feasible.
- Ctrl+C should leave recoverable state.
- A source failure should be recorded and the workflow should continue only where downstream stages remain valid.
- No report should imply completeness when sources failed or were unavailable.

---

## 9. Security, privacy and authorization

- Explicitly approved scope is mandatory for any engagement-specific collection.
- MVP collection is passive/public-source only.
- Respect source terms, rate limits, robots policies where applicable, and privacy obligations.
- Never collect real banking credentials, session tokens, customer account data, payment data, or unnecessary personal data.
- Keep customer-provided/internal evidence separate from public-source evidence.
- Encrypt and restrict access to engagement output directories when customer data is introduced.
- Define retention and deletion procedures before handling client-provided datasets.
- Never treat public reachability as permission for active testing.
- Any future active validation requires a separately configured allowlist, written authorization, operator confirmation, rate limits, and a documented rollback/stop procedure.

---

## 10. Milestones and acceptance criteria

### M0 — Requirements and workspace
- Confirm use cases, scope model, source policies, output requirements.
- Inspect existing repository and agree on structure.
**Done when:** requirements and decisions are documented; no application code is changed without approval.

### M1 — Sequential runner and engagement setup
- Build CLI prompts/config loading.
- Validate scope.
- Create run directory, logs and state.
**Done when:** a synthetic engagement initializes predictably; invalid scope is rejected; existing runs are untouched.

### M2 — First passive collector
- Implement one low-risk public source adapter.
- Store raw response and source metadata.
**Done when:** fixtures and a controlled test produce reproducible raw observations; timeout and source failure are recorded.

### M3 — Normalization and deduplication
- Define observation schema.
- Normalize records and preserve provenance.
**Done when:** repeated observations deduplicate without losing sources or dates.

### M4 — Entity resolution and relationships
- Create entity and relationship records.
- Add evidence references and confidence labels.
**Done when:** analysts can trace every edge to supporting observations; inferred links remain marked inferred.

### M5 — Analysis and report generation
- Generate inventory, change list, evidence register and Markdown summary.
**Done when:** a synthetic dataset produces all expected output files and a useful report with limitations.

### M6 — Additional source adapters
- Add CT, RDAP/ASN, passive DNS and selected corporate/vendor sources one at a time.
**Done when:** each source has documented terms, limits, fixtures, tests and failure handling.

### M7 — Historical comparison
- Compare successive runs and identify added, removed and changed observations.
**Done when:** comparisons are deterministic and do not misrepresent source gaps as asset deletion.

### M8 — Hardening and packaging
- Complete tests, docs, dependency pinning, example configuration and operational instructions.
**Done when:** a new operator can install, configure, run, resume and interpret an example engagement without developer intervention.

### M9 — Optional advanced correlation
- Evaluate NetworkX/graph UI or an interface only after real use cases demonstrate need.
**Done when:** measured analyst workflows show the graph layer improves investigation outcomes.

---

## 11. Task board

| ID | Task | Priority | Estimate | Depends on | Done when |
|---|---|---:|---:|---|---|
| FII-001 | Confirm target use cases and scope policy | P0 | 1–2 hours | — | Approved requirements documented |
| FII-002 | Define engagement configuration schema | P0 | 2–3 hours | 001 | Valid and invalid config fixtures pass |
| FII-003 | Create sequential CLI runner and output folders | P0 | 3–4 hours | 002 | Synthetic run initializes and logs |
| FII-004 | Implement state/checkpoint/resume | P0 | 3–4 hours | 003 | Completed stages skip; interrupted run resumes |
| FII-005 | Define observation and source schemas | P0 | 3–4 hours | 001 | Schema documented and validated |
| FII-006 | Implement first passive source collector | P0 | 3–5 hours | 003, 005 | Fixture-backed collector stores raw evidence |
| FII-007 | Normalize and deduplicate observations | P0 | 4–6 hours | 005, 006 | Provenance preserved through deduplication |
| FII-008 | Implement entity registry | P1 | 4–6 hours | 007 | Canonical entities resolve deterministically |
| FII-009 | Implement evidence-backed relationships | P1 | 4–6 hours | 008 | Every edge traces to evidence |
| FII-010 | Implement analyst review and confidence labels | P1 | 3–4 hours | 009 | Inferences are visibly qualified |
| FII-011 | Generate CSV/JSON/Markdown reports | P1 | 4–6 hours | 007–010 | Full sample report generated |
| FII-012 | Add source failure and retry handling | P1 | 2–4 hours | 006 | Errors are categorized and resumable |
| FII-013 | Add second and third passive source adapters | P1 | 3–5 hours each | 006 | Each has tests and source documentation |
| FII-014 | Add historical run comparison | P2 | 4–6 hours | 007, 011 | Added/removed/changed evidence report |
| FII-015 | Add Scrapy-based targeted public collectors | P2 | 4–8 hours | 006, 007 | Allowlisted spider respects crawl policy |
| FII-016 | Evaluate SpiderFoot/Censys integrations | P2 | 3–5 hours | 009 | Integration decision based on overlap and value |
| FII-017 | Complete packaging, documentation and test suite | P1 | 4–6 hours | 001–015 | Repeatable clean setup and test run |
| FII-018 | Evaluate graph visualization | P3 | 4–8 hours | 009, 011 | Demonstrated benefit over tabular reporting |

Estimates are planning guides, not commitments.

---

## 12. Commercial development hypotheses

1. Pre-engagement financial-sector external intelligence for existing Red Team contracts.
2. Financial institution technology and third-party dependency mapping.
3. Recurring external infrastructure change monitoring.
4. Evidence-backed threat-intelligence reports.
5. White-label analyst tooling for established security providers.

Success should be measured by analyst time saved, evidence coverage, relationship accuracy, useful newly discovered context, report quality, and customer demand—not raw asset count.

Validate the buyer, scope, deliverable, IP ownership, licensing and customer-data handling before commercialization.

---

## 13. Definition of done for the first release

An operator can:
1. Start FII with one command.
2. Load and review an engagement profile.
3. Confirm scope.
4. Run sequential passive collection.
5. See progress and per-source logs.
6. Interrupt and resume without losing previous results.
7. Review normalized observations and evidence provenance.
8. Inspect relationships and confidence labels.
9. Generate useful CSV, JSON and Markdown outputs.
10. Understand source failures, collection gaps and report limitations.

**The first release is successful when it produces one accurate, reproducible, evidence-linked financial infrastructure report from a synthetic or explicitly approved scope.**
