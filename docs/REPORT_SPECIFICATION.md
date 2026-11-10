# FII Report Specification

**Audience:** Executive stakeholders, Red Team, threat-intelligence, architecture and third-party risk analysts.  
**Principle:** Reports are evidence products, not raw scanner dumps.

## 1. Required report package

Each completed run produces:

```
reports/
  executive-summary.md
  technical-report.md
  asset-inventory.csv
  entities.json
  relationships.csv
  observations.jsonl
  source-register.csv
  analyst-review.csv
  changes.csv
  report-manifest.json
```

Optional later outputs: PDF, HTML, SVG/DOT relationship graph.

## 2. Executive summary

Must include:
- Engagement name and scope summary.
- Run ID and collection window.
- Overall collection status (complete/partial).
- Number of configured, successful, partial, failed and skipped sources.
- Counts of observations, entities and relationships.
- Key validated findings and material research leads.
- Notable provider/dependency relationships with qualification.
- Data gaps and collection limitations.
- Prioritized recommended next steps.

Do not report raw asset volume as a risk score.

## 3. Technical report

Sections:
1. Scope and authorization reference.
2. Objectives and exclusions.
3. Methodology and pipeline version.
4. Source register and coverage.
5. Collection timeline.
6. Asset inventory summary.
7. Entity and organization relationships.
8. Vendor and technology dependency observations.
9. Historical changes.
10. Candidate findings and analyst dispositions.
11. Evidence references.
12. Limitations, unresolved questions and recommendations.

Each technical assertion should cite an observation ID, relationship ID, source URL/reference, collection timestamp and verification state.

## 4. Evidence display standard

Every displayed claim should include, when applicable:
- Claim / observation text.
- Entity or entities involved.
- Evidence identifier.
- Source name and URL.
- Source observation date and FII collection time.
- Raw evidence path and SHA-256.
- Verification state: observed, corroborated, inferred, unverified or rejected.
- Confidence value and its rationale, if supplied.
- Analyst disposition.

Confidence is not probability unless a later documented calibration process establishes that interpretation.

## 5. Relationship reporting

The report must distinguish:
- direct facts from official sources;
- infrastructure observations from external data providers;
- time-bound technical associations;
- analyst-inferred relationships;
- contradictory or missing evidence.

Example: "Certificate record contained hostname X" is an observation. "Organization Y operates X" is a separate ownership claim and requires separate evidence.

## 6. Finding quality

A finding should answer:
- What was observed?
- Why is it relevant?
- What evidence supports it?
- What is known and what is only inferred?
- What is the confidence and why?
- What additional validation would establish the claim?
- What should the customer do next?

Do not assign vulnerability severity to ordinary asset discovery. Use informational / research-lead classifications where a security impact is not established.

## 7. CSV and JSON rules

- Stable documented headers and schema version.
- UTF-8 output.
- UTC timestamps.
- One row/object per observation or relationship.
- Preserve source references.
- Do not emit credentials or secrets.
- Escape embedded newlines correctly in CSV.
- Include report/schema version in `report-manifest.json`.
- Reports must be reproducible from the database and raw evidence.

## 8. Report validation

Before publication, verify:
- every relationship cites evidence;
- every finding cites evidence or contains an explicit analyst rationale;
- each source has a recorded outcome;
- all referenced evidence files exist;
- all report outputs are listed in the manifest;
- report status reflects incomplete sources;
- no unsupported claim is presented as a verified internal fact.
