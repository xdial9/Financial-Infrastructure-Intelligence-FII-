# FII Source Register

**Status:** Initial research register; availability, terms and coverage must be verified at implementation time.  
**Collection posture:** Passive/public-source first; customer-supplied datasets only when explicitly authorized.

## 1. Source selection principles

A source is included only when it contributes distinct evidence. Before implementing an adapter, document:
- What facts it can actually provide.
- Whether access is public, authenticated API, purchased data or customer-supplied.
- Terms of use and data licensing.
- Rate limits and query constraints.
- Data freshness and coverage limitations.
- Potential personal or sensitive data.
- Its overlap with existing adapters.
- Whether collection is passive or interacts with a target system.

Publicly accessible data is not a blanket authorization for active testing. FII's first release is not an active scanner.

## 2. MVP source sequence

### S-001 — Engagement-provided seed data
**Priority:** P0  
Inputs are supplied by the operator: organization name, approved domains, public brand names, known subsidiaries, approved source URLs and engagement scope reference.

Purpose: establish an explicit, reviewable starting point rather than guessing the customer scope.

### S-002 — Certificate Transparency observations
**Priority:** P0  
Use a documented CT data interface to collect certificate records associated with approved seed domains. Store certificate identifiers, names, validity dates, issuer metadata and source references. A certificate name is an observation, not proof that a host is currently live or controlled by the organization.

### S-003 — RDAP / registration data
**Priority:** P0  
Use authoritative RDAP services where available to enrich domain and IP registration observations. Expect redaction, privacy masking, missing fields and jurisdiction-specific variation. Do not infer ownership from an incomplete registration record.

### S-004 — Official corporate disclosures
**Priority:** P0  
Collect company-published information about legal entities, brands, subsidiaries, acquisitions and official technology relationships. Prefer filings, annual reports, investor relations pages and official corporate pages. Keep the source URL and quoted/fact-extracted context needed for review.

### S-005 — Official regulatory datasets
**Priority:** P1  
Evaluate regulator-maintained institution directories, filings and public datasets relevant to the selected jurisdiction. Record the issuing authority, dataset version/date and entity identifiers. Do not assume one regulator's institution list is comprehensive for every bank, subsidiary or non-bank provider.

### S-006 — Official vendor and partner documentation
**Priority:** P1  
Use public customer stories, partner directories, product documentation, status pages and integration guides to identify documented technology dependencies. A marketing logo is weak evidence; a technical integration document or formal filing is stronger evidence.

### S-013 — Public website API, JavaScript and authentication surface
**Priority:** P0 for approved public pages; fixture analyzer and manually approved read-only snapshot adapter implemented in Block 06.

After operator review of source terms, robots policy, licensing and request limits, retrieve one explicitly approved HTTPS landing page and a bounded number of JavaScript assets whose hosts remain within the approved domain/subdomain scope. Requests are anonymous GETs, redirects are refused, query-bearing landing URLs are rejected, and no login or state-changing method is used. Static fixture analysis remains available for offline testing. Catalog:
- Script and preload asset references, integrity metadata and source-map references.
- Statically identifiable API routes, absolute API URLs, HTTP methods where explicit, and API documentation references such as OpenAPI, Swagger, Redoc and API-docs paths.
- Authentication architecture hints such as OAuth/OIDC, SAML, PKCE, authorization/token/userinfo/JWKS routes, session routes and named identity-provider SDKs.
- Third-party provider references such as Plaid, Stripe, MX, Finicity, Yodlee, Akoya, TrueLayer and others.

An API string in JavaScript is not proof that an endpoint is reachable, that a route is intended for public use, or that a service is usable. An auth marker is not proof of a working login. A vendor string is not proof of an active institutional integration. Preserve the source file/hash and label the detection as static evidence. Never execute JavaScript, submit credentials, replay sessions or collect customer/account data. The Block 06 live adapter requires `live_collection_approved=True` for each run. It does not execute JavaScript, call discovered API routes, follow source maps, fetch unapproved CDN hosts, or validate sessions.

### S-014 — crt.live public Certificate Transparency API
**Priority:** P0 for manually approved single-domain CT enrichment; one-page adapter implemented in Block 06.

Use the public JSON API for one explicitly approved seed domain per invocation. The adapter requests one page (default 1,000 names, maximum 10,000), retains only exact/subdomain matches of the approved domain, and records hostname plus first-seen date. It preserves the provider-response digest and a retained, in-scope evidence payload. It does not paginate automatically or retry HTTP 429; it surfaces `Retry-After` and marks capped/incomplete result pages as partial.

The provider documentation describes a maximum page limit of 10,000 and a limit of 120 requests per minute per address, and cautions that CT names do not prove a host exists or resolves. FII deliberately issues one request per manual invocation. The response does not provide the full certificate issuer/serial/validity/key metadata set. Before invocation, an operator must review the provider's current terms and rate guidance. Reference: [crt.live API documentation](https://crt.live/about).

## 3. Optional infrastructure intelligence sources

### S-007 — Passive DNS provider
**Priority:** P1, optional credentials  
Use only a licensed or documented API with permission to query and retain results. Preserve provider timestamps and distinguish historical DNS observation from current resolution.

### S-008 — Censys API
**Priority:** P1, optional credentials  
Evaluate as a provider-backed source of internet infrastructure observations. Use its documented API and terms. Store source observation timestamps and provider identifiers. Do not treat provider inventory as a direct FII scan.

### S-009 — Subfinder
**Priority:** P2  
Evaluate a passively configured Subfinder adapter after the raw observation model is stable. Run only in passive mode, against operator-approved seed domains and with configured sources. Capture tool version, source configuration digest, command metadata and raw output.

### S-010 — OWASP Amass
**Priority:** P2  
Evaluate passive mode and its distinct data coverage before adoption. Do not enable active enumeration modes in the initial product. Avoid running Amass and Subfinder redundantly unless a documented coverage test demonstrates additive value.

### S-011 — SpiderFoot
**Priority:** P2  
Treat as an optional enrichment system, not FII's core architecture. First assess module overlap, output quality, licensing, credential handling, resource cost and data provenance. Any adapter must preserve module/source identifiers and distinguish direct observations from SpiderFoot-derived associations.

### S-012 — Scrapy
**Priority:** P2  
Use for targeted extraction from approved public corporate, vendor or regulatory websites only when a stable API or downloadable dataset is unavailable. Limit hosts and paths, use conservative request rates, identify the crawler, respect terms and robots policies where applicable, and store fetched URLs and retrieval timestamps. No broad recursive crawling of unrelated domains.

## 4. Source priority and MVP cut line

First vertical slice:
1. Operator-supplied seed scope.
2. One CT source.
3. RDAP enrichment for a subset of discovered identifiers.
4. One official corporate/regulatory source.
5. Raw evidence preservation and normalized CSV/JSON output.

Do not start with all integrations at once. First prove that observations from two independent sources can be normalized, deduplicated, traced and reported correctly.

## 5. Source overlap and deduplication

- A hostname discovered by multiple collectors is one canonical entity with multiple observations.
- Repeated queries against the same provider are not independent corroboration.
- A single CT record may yield multiple DNS names; preserve the original certificate record.
- DNS resolution changes over time; observations are time-bound.
- Vendor documentation can refer to a group, brand or product; do not automatically create a legal ownership relationship.
- SpiderFoot, Subfinder and Amass may overlap; measure added coverage before enabling multiple adapters.

## 6. Source health register

At runtime, record:
- configured/enabled state;
- required/optional status;
- terms/documentation reference;
- adapter version;
- last successful collection;
- records received/accepted;
- latency;
- failure and rate-limit counts;
- credential requirement (never credential value);
- coverage and caveats.

The final report must clearly identify failed, skipped, stale and unavailable sources.
