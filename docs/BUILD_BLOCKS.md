

## Block 09 — Relationship correlation and analyst review

**Status:** Implementation on draft PR #6 / branch `build/block-09-relationship-correlation-analyst-review`, stacked on Block 08. Final CI verification is required before completion.

Deliverables:
- Versioned SQLite migration 0003 with a fixed relationship-rule registry and append-only analyst review history.
- Typed relationship rules for RDAP nameserver observations, static vendor references, static API route references and API documentation references.
- Evidence-linked relationship proposals with supporting, contradicting and context roles; deterministic IDs make repeated identical proposals idempotent without collapsing distinct evidence assertions.
- Endpoint-type, run-scope, observation-type, endpoint-anchor and source/value consistency checks.
- Corroboration requires supporting observations from at least two distinct source definitions. Contradicting evidence is retained and prevents automatic corroboration.
- Deterministic rule confidence scores and explicit rationale; scores are heuristic, not probabilities.
- Analyst dispositions accepted/rejected/needs_research with reviewer label, rationale, timestamp and prior/resulting state. Acceptance does not upgrade evidence state; rejection marks the assertion rejected; review history cannot be updated or deleted.
- Synthetic offline SQLite tests; no active requests, JavaScript execution, API invocation, or real institution/provider contact.

Exit criteria:
- Each persisted relationship has at least one supporting evidence link and may also retain contradictory/context evidence.
- Only registered predicates/rules and matching entity types/observation types can be used.
- Two executions from the same source definition do not count as independent corroboration.
- Two distinct source definitions may corroborate an observed rule only when no contradicting evidence exists.
- Contradictions remain visible and prevent corroboration.
- Analyst review is auditable and cannot silently promote confidence or erase evidence.
- CI passes on the final PR head before Block 09 is complete.
