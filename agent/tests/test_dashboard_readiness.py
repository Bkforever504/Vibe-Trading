from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.dashboard_readiness import build_readiness


NOW = datetime(2026, 8, 24, 21, 0, tzinfo=timezone.utc)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_readiness_separates_installed_runtime_and_evidence(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    reports = tmp_path / "reports"
    for relative in (
        "scripts/pattern_grader_scanner.py",
        "scripts/build_move_ground_truth.py",
        "scripts/detection_scorecard.py",
        "scripts/grade_probability_service.py",
        "scripts/daily_aplus_review.py",
        "scripts/options_feed_qualification.py",
        "scripts/manual_execution_quality.py",
        "scripts/broker_fill_observer.py",
        "scripts/run_dashboard_evidence_chain.ps1",
        "scripts/run_move_universe_ground_truth.ps1",
        "frontend/src/components/trading/SystemReadinessGate.tsx",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ready", encoding="utf-8")

    _write(reports / "pattern-grader-grades.json", {
        "generated_at": "2026-08-24T20:59:00Z",
        "scan_reconciliation": {"denominator_reconciled": True, "producer_failure_count": 0},
    })
    _write(reports / "move-ground-truth-summary.json", {
        "generated_at": "2026-08-24T20:59:00Z", "metrics_qualified": True, "producer_healthy": True,
    })
    _write(reports / "detection-scorecard-rolling.json", {
        "generated_at": "2026-08-24T20:59:00Z",
        "pattern_coverage": {"opportunity_coverage": {"metrics_qualified": True}},
    })
    _write(reports / "daily-aplus-review.json", {
        "timestamp": "2026-08-24T20:59:00Z", "review_status": "complete",
        "summary": {"overall_review_coverage_pct": 100.0},
    })
    _write(reports / "options-feed-qualification.json", {
        "generated_at": "2026-08-24T20:59:58Z", "status": "context_only",
    })
    _write(reports / "manual-execution-quality.json", {
        "generated_at": "2026-08-24T20:59:00Z", "status": "awaiting_observations",
    })
    _write(reports / "broker-fill-observer.json", {
        "generated_at": "2026-08-24T20:59:00Z", "status": "no_fills",
    })
    _write(reports / "grade-probability-calibration.json", {
        "generated_at": "2026-08-24T20:59:00Z",
        "eligible_outcomes": 12,
        "buckets": [{"probability": {"status": "not_calibrated", "independent_dates": 4}}],
    })

    result = build_readiness(root=root, report_dir=reports, now=NOW)

    assert result["build"]["percent"] == 100.0
    assert result["build"]["status"] == "installed"
    assert result["runtime"]["percent"] == 100.0
    assert result["runtime"]["status"] == "operational"
    assert result["evidence"]["status"] == "collecting"
    assert result["evidence"]["ranking_qualified_bucket_count"] == 0
    assert result["evidence"]["eligible_outcomes"] == 12
    assert result["evidence"]["independent_dates"] == 4
    assert result["ready_for_manual_review"] is True
    assert result["probability_claims_qualified"] is False
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False


def test_runtime_fails_closed_without_independent_move_denominator(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    reports = tmp_path / "reports"
    (root / "scripts").mkdir(parents=True)
    _write(reports / "move-ground-truth-summary.json", {
        "generated_at": "2026-08-24T20:59:00Z", "metrics_qualified": False, "producer_healthy": False,
    })

    result = build_readiness(root=root, report_dir=reports, now=NOW)

    move_gate = next(row for row in result["runtime"]["gates"] if row["id"] == "move_ground_truth")
    assert move_gate["ready"] is False
    assert result["runtime"]["status"] == "attention_required"
    assert result["ready_for_manual_review"] is False
