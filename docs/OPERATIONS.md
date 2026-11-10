# FII Operations and CLI Specification

**Status:** Proposed operator experience. Commands become authoritative when implemented.

## 1. Operator experience

The default task should be simple:

```bash
fii doctor
fii run --config engagements/example-bank.yaml
```

The run command validates configuration and scope, shows the selected source plan, then executes the sequential workflow. The operator should not have to manually invoke every collector.

## 2. Proposed commands

| Command | Purpose |
|---|---|
| `fii --version` | Display application version |
| `fii doctor` | Check Python, configuration, SQLite and configured source prerequisites |
| `fii init` | Create a sample engagement configuration and workspace |
| `fii sources list` | Show available collectors, requirements and current configuration |
| `fii scope show` | Show normalized engagement scope before a run |
| `fii run --config FILE` | Execute complete workflow sequentially |
| `fii status --run-id ID` | Summarize run and stage states |
| `fii resume --run-id ID` | Resume eligible incomplete work |
| `fii report --run-id ID` | Rebuild reports from stored evidence |
| `fii reconcile --run-id ID` | Verify manifests, source runs, evidence and reports |

The implementation should not expose unnecessary subcommands. The primary user path remains `doctor`, then `run`, then `report/status`.

## 3. Configuration locations

Global application configuration:
`~/.config/fii/config.yaml`

Engagement configuration:
`<workspace>/engagements/<slug>/engagement.yaml`

Default workspace:
`~/FII-Workspace/`

The actual path is configurable. Do not put customer data or API credentials in the Git checkout.

## 4. Engagement configuration example

```yaml
engagement:
  name: "Synthetic Financial Institution"
  slug: "synthetic-financial-institution"
  organization: "Example Financial Group"
  authorization_reference: "SYNTHETIC-LAB"

scope:
  seed_domains:
    - "example.invalid"
  approved_organizations:
    - "Example Financial Group"
  permitted_source_classes:
    - "public_api"
    - "public_dataset"
    - "targeted_public_web"
  allow_active_validation: false

collection:
  sequential: true
  request_timeout_seconds: 20
  max_retries: 3
  retry_backoff_seconds: 2
  user_agent: "FII-Research/0.1 (contact: operator-configured)"

sources:
  ct_logs:
    enabled: true
    required: true
  rdap:
    enabled: true
    required: false
  official_corporate_web:
    enabled: false
    required: false
```

The `.invalid` domain is reserved for documentation and synthetic examples; it is not a real target.

## 5. Secrets

- Use environment variables or an OS-protected secret store.
- Never commit API keys, tokens, passwords or customer access material.
- Never place secret values in logs, command-line output, run manifests or report exports.
- Configuration digests must be computed from a sanitized representation with secret values removed.
- Record only whether a credential is configured, not its value.

## 6. Workspace layout

```
~/FII-Workspace/
  engagements/
    <engagement-slug>/
      engagement.yaml
      database/
        fii.sqlite3
        .workspace.lock
        migrations/
      runs/
        <run-id>/
          config/
            effective-config.json
          raw/
            <source-id>/
          normalized/
          analysis/
          reports/
          logs/
          state/
            run.json
            stage-state.json
            source-state.json
            manifest.json
```

Each run is immutable after finalization, except for explicitly versioned analyst review/disposition events. New runs never overwrite old run directories.

## 7. Permissions and privacy

- Create private workspace directories with restrictive permissions (target 0700 for directories, 0600 for sensitive files where supported).
- Do not store unnecessary personal data.
- Do not collect credentials, session cookies, authentication tokens, payment data or customer account records.
- Separate public-source evidence from customer-provided internal datasets.
- Define retention and deletion policies before any customer data ingestion.
- Do not commit run output, raw data, database files, local configs or secrets to Git.

## 8. External tool execution

For any external tool:
- resolve a known executable;
- check its version and required capabilities;
- invoke via an argument list;
- never use `shell=True`;
- capture stdout/stderr to a source-specific log;
- set timeout and maximum output constraints;
- record exact tool version and sanitized argument metadata;
- mark unavailable tools as skipped or failed according to required/optional configuration.

## 9. Operator-facing messages

Progress messages should be concise and consistent:

```text
FII — Financial Infrastructure Intelligence
Engagement: Synthetic Financial Institution
Run: <run-id>
Scope: validated
Sources: 3 enabled (1 required)

[1/3] CT Logs ............ COMPLETE (42 records)
[2/3] RDAP ............... PARTIAL  (8 records, 1 lookup unavailable)
[3/3] Corporate Sources . SKIPPED  (disabled)

Normalization ........... COMPLETE
Entity resolution ....... COMPLETE
Correlation ............. COMPLETE
Reporting ............... COMPLETE

Run status: PARTIAL
Reports: .../reports/
Logs: .../logs/
```

Never use alarming severity language for an unverified relationship or ordinary asset discovery.
