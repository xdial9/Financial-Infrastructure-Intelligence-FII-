"""Linear orchestration for a single FII engagement run."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fii.analyze import analyze_relationships
from fii.collectors.synthetic import collect as collect_synthetic
from fii.config import load_config
from fii.deduplicate import deduplicate_observations
from fii.entities import build_entities_and_relationships
from fii.normalize import normalize_records
from fii.report import generate_reports, write_json, write_jsonl
from fii.state import read_json, write_json_atomic


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "fii-engagement"


def _new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_or_create_state(run_dir: Path, config, resume: bool) -> dict:
    state_path = run_dir / "state" / "run-state.json"
    if resume:
        if not state_path.is_file():
            raise ValueError(f"Cannot resume; run state not found: {state_path}")
        state = read_json(state_path)
        if state.get("config_fingerprint") != config.fingerprint:
            raise ValueError("Cannot resume: engagement configuration changed since this run started")
        return state
    state = {
        "run_id": run_dir.name,
        "engagement_name": config.engagement_name,
        "config_fingerprint": config.fingerprint,
        "status": "in_progress",
        "completed_stages": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "failed_stage": None,
    }
    write_json_atomic(state_path, state)
    return state


def run_engagement(config_path: str | Path, yes: bool = False, output_dir: str | Path | None = None, resume_run_id: str | None = None) -> Path:
    config = load_config(config_path)
    root = Path(output_dir).expanduser().resolve() if output_dir else config.output_dir
    engagement_dir = root / _slug(config.engagement_name) / "runs"
    engagement_dir.mkdir(parents=True, exist_ok=True)

    if resume_run_id:
        run_dir = engagement_dir / resume_run_id
        if not run_dir.is_dir():
            raise ValueError(f"Run directory not found: {run_dir}")
    else:
        run_id = _new_run_id()
        run_dir = engagement_dir / run_id
        suffix = 1
        while run_dir.exists():
            run_dir = engagement_dir / f"{run_id}-{suffix}"
            suffix += 1
        run_dir.mkdir(parents=True)

    for directory in ("raw", "normalized", "analysis", "reports", "logs", "state", "lists"):
        (run_dir / directory).mkdir(parents=True, exist_ok=True)

    state = _load_or_create_state(run_dir, config, bool(resume_run_id))
    state_path = run_dir / "state" / "run-state.json"
    started = time.monotonic()

    def stage(name: str, required_files: list[str], action) -> None:
        if name in state["completed_stages"] and all((run_dir / item).is_file() for item in required_files):
            print(f"[SKIP] {name}: checkpoint and outputs already exist", flush=True)
            return
        print(f"[START] {name}", flush=True)
        state["current_stage"] = name
        write_json_atomic(state_path, state)
        action()
        state["completed_stages"].append(name)
        state["completed_stages"] = list(dict.fromkeys(state["completed_stages"]))
        state["current_stage"] = None
        write_json_atomic(state_path, state)
        print(f"[DONE]  {name}", flush=True)

    try:
        print("\nFII — Financial Infrastructure Intelligence", flush=True)
        print(f"Engagement: {config.engagement_name}", flush=True)
        print(f"Organization: {config.organization}", flush=True)
        print(f"Approved domains: {', '.join(config.approved_domains)}", flush=True)
        print(f"Approved sources: {', '.join(config.approved_sources)}", flush=True)
        print("Collection mode: synthetic fixture only; network access disabled", flush=True)
        if not yes:
            answer = input("Proceed with this synthetic run? [y/N]: ").strip().lower()
            if answer not in {"y", "yes"}:
                print("Run canceled. No collection was performed.")
                return run_dir

        stage("collect", ["raw/source-results.json"], lambda: write_json(
            run_dir / "raw" / "source-results.json",
            collect_synthetic(config.fixture_path, config.approved_domains),
        ))
        raw_records = read_json(run_dir / "raw" / "source-results.json")

        stage("normalize", ["normalized/observations.jsonl"], lambda: write_jsonl(
            run_dir / "normalized" / "observations.jsonl", normalize_records(raw_records)
        ))
        normalized = [json.loads(line) for line in (run_dir / "normalized" / "observations.jsonl").read_text(encoding="utf-8").splitlines() if line]

        stage("deduplicate", ["normalized/deduplicated-observations.json"], lambda: write_json(
            run_dir / "normalized" / "deduplicated-observations.json", deduplicate_observations(normalized)
        ))
        deduplicated = read_json(run_dir / "normalized" / "deduplicated-observations.json")

        def build_graph() -> None:
            entities, relationships = build_entities_and_relationships(deduplicated)
            write_json(run_dir / "analysis" / "entities.json", entities)
            write_json(run_dir / "analysis" / "relationships.json", relationships)

        stage("correlate", ["analysis/entities.json", "analysis/relationships.json"], build_graph)
        entities = read_json(run_dir / "analysis" / "entities.json")
        relationships = read_json(run_dir / "analysis" / "relationships.json")

        stage("analyze", ["analysis/findings.json"], lambda: write_json(
            run_dir / "analysis" / "findings.json", analyze_relationships(relationships)
        ))
        findings = read_json(run_dir / "analysis" / "findings.json")

        report_files: list[str] = []
        stage("report", ["reports/executive-summary.md", "reports/asset-inventory.csv", "reports/relationships.csv"], lambda: report_files.extend(
            generate_reports(run_dir, config, entities, relationships, findings, normalized)
        ))
        if not report_files:
            report_files = [
                "reports/executive-summary.md", "reports/asset-inventory.csv", "reports/relationships.csv",
                "reports/analyst-review.csv", "reports/source-register.csv",
            ]

        state.update({
            "status": "completed",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "counts": {
                "raw_records": len(raw_records), "normalized_observations": len(normalized),
                "deduplicated_observations": len(deduplicated), "entities": len(entities),
                "relationships": len(relationships), "findings": len(findings),
            },
            "report_files": report_files,
        })
        write_json_atomic(state_path, state)
        write_json(run_dir / "run-summary.json", state)
        print("\nRun completed successfully.", flush=True)
        print(f"Output: {run_dir}", flush=True)
        print(f"Entities: {len(entities)} | Relationships: {len(relationships)} | Findings: {len(findings)}", flush=True)
        print(f"Executive report: {run_dir / 'reports' / 'executive-summary.md'}", flush=True)
        return run_dir
    except KeyboardInterrupt:
        state["status"] = "interrupted"
        state["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json_atomic(state_path, state)
        print("\nInterrupted. Completed stages are checkpointed; resume with --resume.", file=sys.stderr)
        raise
    except Exception as exc:
        state["status"] = "failed"
        state["failed_stage"] = state.get("current_stage")
        state["error"] = f"{type(exc).__name__}: {exc}"
        state["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_json_atomic(state_path, state)
        write_json(run_dir / "logs" / "failure.json", state)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FII sequential financial infrastructure intelligence runner")
    parser.add_argument("--config", default="examples/synthetic_engagement.json", help="Engagement JSON profile")
    parser.add_argument("--output-dir", help="Override the output root from the profile")
    parser.add_argument("--resume", metavar="RUN_ID", help="Resume an existing run by its run ID")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt (synthetic fixture only)")
    args = parser.parse_args(argv)
    try:
        run_engagement(args.config, yes=args.yes, output_dir=args.output_dir, resume_run_id=args.resume)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
