from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.shadow_logger_audit import build_report


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_audit_distinguishes_resolved_context_and_derived_streams(tmp_path: Path) -> None:
    rows = [
        {"record_type": "signal", "timestamp": "2026-08-17T14:00:00Z"},
        {"record_type": "outcome", "timestamp": "2026-08-18T14:00:00Z", "outcome": "win"},
    ]
    _jsonl(tmp_path / "alpha_shadow_log.jsonl", rows)
    _jsonl(tmp_path / "beta_shadow_log.jsonl", [{"timestamp": "2026-08-18T15:00:00Z", "context": "trend"}])
    _jsonl(tmp_path / "flip_shadow_pnl_evaluation_log.jsonl", [{"generated_at": "2026-08-18T16:00:00Z"}])

    report = build_report(tmp_path, now=datetime(2026, 8, 18, 20, tzinfo=timezone.utc))
    by_name = {row["name"]: row for row in report["rows"]}

    assert report["summary"]["log_count"] == 3
    assert by_name["alpha_shadow_log.jsonl"]["resolved_count"] == 1
    assert by_name["alpha_shadow_log.jsonl"]["evidence_status"] == "collecting_resolved_outcomes"
    assert by_name["beta_shadow_log.jsonl"]["evidence_status"] == "context_only_no_resolved_outcomes"
    assert "forward_outcome_contract_missing_or_external" in by_name["beta_shadow_log.jsonl"]["issues"]
    assert by_name["flip_shadow_pnl_evaluation_log.jsonl"]["role"] == "derived_report_stream"


def test_audit_marks_old_daily_logger_stale(tmp_path: Path) -> None:
    _jsonl(tmp_path / "alpha_shadow_log.jsonl", [{"timestamp": "2026-08-10T14:00:00Z"}])

    report = build_report(tmp_path, now=datetime(2026, 8, 18, 20, tzinfo=timezone.utc))

    assert report["rows"][0]["freshness"] == "stale"
    assert "stale_log" in report["rows"][0]["issues"]


def test_audit_labels_large_forward_sample_without_claiming_edge(tmp_path: Path) -> None:
    rows = [
        {
            "record_type": "outcome",
            "timestamp": f"2026-07-{day:02d}T14:00:00Z",
            "outcome": "win" if day % 2 else "loss",
        }
        for day in range(1, 31)
    ]
    _jsonl(tmp_path / "alpha_shadow_log.jsonl", rows)

    report = build_report(tmp_path, now=datetime(2026, 8, 18, 20, tzinfo=timezone.utc))

    assert report["rows"][0]["evidence_status"] == "sample_size_review_ready"
    assert report["summary"]["sample_size_review_ready_count"] == 1
