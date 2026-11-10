# FII Implementation Notes — Phase 01

## What exists in this first slice

The first implementation is deliberately an offline, synthetic end-to-end pipeline. It validates an engagement profile and domain allowlist, collects a local fixture, normalizes evidence, deduplicates relationships while retaining independent source records, builds canonical entities and relationship edges, produces deterministic analyst leads, and writes CSV/JSON/Markdown outputs.

## Safety and data boundaries

- Only the `synthetic_fixture` source is implemented in this phase.
- The collector performs no network requests.
- Domain and hostname subjects and objects must remain inside the configured allowlist.
- The included institution, provider, sources, and records are fictional test data.
- A vendor relationship is dependency context, not a vulnerability or proof of an internal trust path.

## Run it

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
python automate.py --config examples/synthetic_engagement.json
```

The example command displays the exact scope and asks for confirmation before it processes the local fixture. Add `--yes` only when intentionally skipping that prompt.

To resume a run, use the run ID shown in the output:

```bash
python automate.py --config examples/synthetic_engagement.json --resume RUN_ID
```

## Current limits / next block

This slice is not yet a live-source intelligence collector. Next, add one passive source adapter only after its data policy, API terms, rate limits, and output fields are documented. RDAP is a reasonable candidate for domain-registration metadata; CT and passive DNS should be separate adapters with separate provenance. Then add source-level retries, failure isolation, a source register with policy metadata, and historical run comparison.
