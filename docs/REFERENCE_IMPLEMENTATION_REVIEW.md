# Reference Implementation Review

**Purpose:** Record the concrete conventions observed in the two supplied reference implementations and how FII adopts them.  
**Reviewed:** 2026-11-10  
**Status:** Design input; this document does not claim that FII application code exists.

## 1. University Audit automation — attached `automate.py`

### Observed implementation style

The script is a single readable Python entry point using the standard library:
- `csv`, `json`, `os`, `re`, `shutil`, `subprocess`, `sys`, `time`, `urllib`, `datetime` and `pathlib`.
- Constants at module level for base path, request timeout, scan timeout and tool options.
- Small explicit functions: `clean_name()`, `normalize_host()`, `get_json()`, `inventory()`, `find_trufflehog()`, `build_trufflehog_command()`, `run_scans()` and `main()`.
- Standard-library HTTP with an explicit User-Agent and timeout.
- External tool execution through a list of arguments passed to `subprocess.run()`, with captured stdout/stderr, timeout and explicit return-code handling.
- Sequential processing: one project is processed at a time.
- Human-readable progress output with `flush=True`.
- Per-target output folders for lists, results and logs.
- JSON and CSV inventory output.
- State persisted to JSON after each item.
- Failure details persisted separately.
- Completed items are skipped on resume when the stored URL and completion state match.
- Existing results from unknown or incomplete attempts are preserved by creating a suffixed attempt file.
- Graceful Ctrl+C handling and preservation of existing output.

### FII decisions derived from this script

1. Keep the default execution path linear and visible.
2. Use small functions with explicit inputs and outputs.
3. Keep timeouts and error handling adjacent to network/subprocess calls.
4. Use argument arrays for external tools, never shell-string construction.
5. Print progress that an operator can understand without opening logs.
6. Persist state incrementally, not only at the end.
7. Keep raw result files, human-readable exports and logs separate.
8. Never overwrite a prior or incomplete result automatically.
9. Make Ctrl+C leave a recoverable workspace.

## 2. APK Workbench — repository conventions observed

Repository reviewed: `xdial9/apk-workbench`.

### Package and CLI organization

The repository uses a `src/` layout and an installable Python package. Its main areas include:
- `cli/`
- `core/`
- `sources/`
- `acquisition/`
- `decompilation/`
- `analysis/`
- `database/`
- `reporting/`
- `dependencies/`

The Click command group lives in `src/apkworkbench/cli/main.py`. Project metadata and the console script are defined in `pyproject.toml`. Runtime dependencies and development dependencies are declared separately.

### Configuration

The `core/config.py` implementation uses defaults in code, loads YAML overrides, validates that configuration sections have the expected shape, and creates application-owned workspace directories. Configuration and workspace locations are configurable rather than assumed to be inside the source checkout.

### Reliability and persistence

The repository's documented and implemented patterns include:
- Workspace-level interprocess locking.
- Append-only attempt/history records.
- Frozen per-run manifests.
- Separate acquisition identity and analysis identity.
- Atomic file publication.
- Hash verification.
- Explicit timeout and failure statuses.
- Resume and reconciliation commands.
- Preservation of previously successful output when a forced refresh fails.
- SQLite evidence storage with numbered schema migrations.

### Testing and documentation

The project uses pytest and Ruff as development tools and maintains separate documents for target architecture, evidence schema, configuration, commands, reliability/recovery, project history and engineering coordination.

## 3. What FII will reuse

| Pattern | FII adaptation |
|---|---|
| Single sequential runner | One FII run controller orchestrates every stage in a fixed order |
| Small named functions | Each source and pipeline stage has a narrow responsibility |
| Click CLI | `fii doctor`, `fii run`, `fii status`, `fii resume`, `fii report`, `fii reconcile` |
| YAML with code defaults | Engagement configuration with strict schema validation |
| Workspace isolation | One engagement directory with run-specific subdirectories |
| Interprocess lock | Prevent concurrent writers to an engagement database |
| Frozen run manifest | Freeze selected scope, sources, effective config and collector versions |
| Append-only attempts | Preserve every source/stage attempt and error |
| SQLite evidence store | Canonical records and relationships in a versioned database |
| JSON/CSV exports | Analyst-friendly outputs backed by canonical data |
| Recovery and reconciliation | Resume only when fingerprints match; verify every report reference |
| Tests and architecture docs | Test each stage offline with fixtures and synthetic data |

## 4. What FII will deliberately not copy

FII does not need APK Workbench's full acquisition/decompilation framework or its larger analyzer execution model. FII's first release has fewer source types and no APK artifact pipeline.

Avoid introducing:
- A generic plugin loader.
- A distributed task queue.
- Async orchestration.
- Multiple services or containers for ordinary stages.
- A mandatory browser GUI.
- A graph database before SQLite proves inadequate.
- Automatic active scanning or exploitation.

FII should be as simple as the University Audit automation in its normal execution path, while having the modularity and recovery discipline already established in APK Workbench.

## 5. Source grounding and limitations

The University Audit observations above are based on the attached `automate.py` (especially its function layout, sequential scan loop, state/failure handling and `main()` flow).

The APK Workbench observations are based on its repository structure, `pyproject.toml`, `cli/main.py`, `core/config.py`, `database/workspace.py`, `database/evidence.py`, and its architecture and reliability documentation.

This is a design comparison, not a claim that FII's planned architecture has already been implemented or tested.
