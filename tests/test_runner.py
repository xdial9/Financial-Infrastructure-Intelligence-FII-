from __future__ import annotations

import json
from pathlib import Path

from fii.runner import run_engagement

ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_run_writes_expected_outputs(tmp_path):
    run_dir = run_engagement(
        ROOT / "examples" / "synthetic_engagement.json",
        yes=True,
        output_dir=tmp_path,
    )
    expected = [
        "raw/source-results.json",
        "normalized/observations.jsonl",
        "normalized/deduplicated-observations.json",
        "analysis/entities.json",
        "analysis/relationships.json",
        "analysis/findings.json",
        "reports/asset-inventory.csv",
        "reports/relationships.csv",
        "reports/analyst-review.csv",
        "reports/source-register.csv",
        "reports/executive-summary.md",
        "run-summary.json",
        "state/run-state.json",
    ]
    assert all((run_dir / path).is_file() for path in expected)
    summary = json.loads((run_dir / "run-summary.json").read_text())
    assert summary["status"] == "completed"
    assert summary["counts"]["raw_records"] == 4
    assert summary["counts"]["deduplicated_observations"] == 3
    report = (run_dir / "reports" / "executive-summary.md").read_text()
    assert "No live external sources were queried" in report


def test_resume_reuses_completed_run_without_overwriting(tmp_path):
    first = run_engagement(ROOT / "examples" / "synthetic_engagement.json", yes=True, output_dir=tmp_path)
    report_path = first / "reports" / "executive-summary.md"
    before = report_path.read_text()
    resumed = run_engagement(
        ROOT / "examples" / "synthetic_engagement.json",
        yes=True,
        output_dir=tmp_path,
        resume_run_id=first.name,
    )
    assert resumed == first
    assert report_path.read_text() == before
