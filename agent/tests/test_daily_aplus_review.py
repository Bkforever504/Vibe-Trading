from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.daily_aplus_review import build_report


NOW = datetime(2026, 8, 21, 23, 0, tzinfo=timezone.utc)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_every_top_tier_observation_is_enumerated_and_duplicate_snapshots_are_grouped(tmp_path: Path) -> None:
    radar = tmp_path / "radar.jsonl"
    _write_jsonl(radar, [
        {"date": "2026-08-21", "generated_at": "2026-08-21T15:00:00Z", "ranked_candidates": [
            {"candidate_id": "nvda-orb", "symbol": "NVDA", "setup": "opening_range_breakout", "direction": "bullish", "grade": "A+", "score": 94, "entry": 180, "stop": 178},
            {"candidate_id": "amd-watch", "symbol": "AMD", "setup": "watch", "direction": "bullish", "grade": "B", "score": 72},
        ]},
        {"date": "2026-08-21", "generated_at": "2026-08-21T16:00:00Z", "ranked_candidates": [
            {"candidate_id": "nvda-orb", "symbol": "NVDA", "setup": "opening_range_breakout", "direction": "bullish", "grade": "A+", "score": 96, "entry": 181, "stop": 179,
             "market_structure": {"timeframe_coverage": {"status": "complete_for_aplus_review", "missing_required": [], "frames": [{"timeframe": "5m", "status": "available"}]}}},
        ]},
    ])
    pattern = tmp_path / "patterns.jsonl"
    _write_jsonl(pattern, [{
        "date": "2026-08-21", "detection_id": "cisd-1", "symbol": "SPY", "pattern_id": "ict_cisd_universal_model",
        "direction": "bearish", "grade": "A", "score": 89, "trigger": 6500, "invalidation": 6510,
        "pattern_grade": {"rubric_version": "pattern_grade_v1"},
    }])

    report = build_report(
        day="2026-08-21",
        sources={"intraday_radar": radar, "pattern_grader": pattern},
        outcome_paths=[],
        now=NOW,
    )

    assert report["review_status"] == "complete"
    assert report["summary"]["top_tier_observation_count"] == 3
    assert report["summary"]["distinct_setup_count"] == 2
    assert report["summary"]["system_review_coverage_pct"] == 100.0
    nvda = next(row for row in report["items"] if row["symbol"] == "NVDA")
    assert nvda["observation_count"] == 2
    assert nvda["max_score"] == 96
    assert nvda["system_review_status"] == "reviewed"
    assert nvda["outcome_review_status"] == "pending"
    assert nvda["timeframe_coverage_status"] == "complete_for_aplus_review"
    assert nvda["missing_required_timeframes"] == []
    assert nvda["execution_enabled"] is False
    assert nvda["can_submit_orders"] is False


def test_missing_declared_source_fails_review_coverage_closed(tmp_path: Path) -> None:
    report = build_report(
        day="2026-08-21",
        sources={"missing_source": tmp_path / "missing.jsonl"},
        outcome_paths=[],
        now=NOW,
    )

    assert report["review_status"] == "attention_required"
    assert report["summary"]["source_coverage_pct"] == 0.0
    assert report["summary"]["system_review_coverage_pct"] == 0.0
    assert report["summary"]["overall_review_coverage_pct"] == 0.0
    assert report["source_inventory"][0]["status"] == "missing"
    assert report["source_inventory"][0]["freshness"] == "missing"
    assert report["source_inventory"][0]["last_modified_at"] is None
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_nested_market_structure_a_grade_is_reviewed_with_parent_symbol(tmp_path: Path) -> None:
    live = tmp_path / "live.json"
    live.write_text(json.dumps({
        "generated_at": "2026-08-21T15:35:00Z",
        "market_structure_watchlist": [{
            "symbol": "SPY",
            "grade": "A",
            "score": 89,
            "pattern_grade": {"rubric_version": "pattern_grade_v1", "final_score": 89},
            "best_setup": {
                "pattern_id": "ict_cisd_universal_model",
                "direction": "bullish",
                "trigger": 650.25,
                "invalidation": 648.75,
            },
            "timeframe_coverage": {"status": "complete_for_aplus_review", "missing_required": []},
        }],
    }), encoding="utf-8")

    report = build_report(
        day="2026-08-21",
        sources={"live_opportunity": live},
        outcome_paths=[],
        now=NOW,
    )

    assert report["summary"]["top_tier_observation_count"] == 1
    assert report["items"][0]["symbol"] == "SPY"
    assert report["items"][0]["setup"] == "ict_cisd_universal_model"
    assert report["items"][0]["geometry_complete"] is True


def test_declared_pattern_producer_failure_prevents_complete_review(tmp_path: Path) -> None:
    status = tmp_path / "pattern-grader-grades.json"
    status.write_text(json.dumps({
        "generated_at": "2026-08-21T15:35:00Z",
        "scan_reconciliation": {"producer_failure_count": 1, "denominator_reconciled": False},
        "latest_detections": [],
    }), encoding="utf-8")

    report = build_report(
        day="2026-08-21",
        sources={"pattern_grader_status": status},
        outcome_paths=[],
        now=NOW,
    )

    assert report["review_status"] == "attention_required"
    assert report["summary"]["source_coverage_pct"] == 0.0
    assert report["source_inventory"][0]["status"] == "producer_failed"


def test_matching_outcome_closes_review_followup(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    _write_jsonl(source, [{
        "date": "2026-08-21", "candidate_id": "plan-1", "symbol": "QQQ", "setup_family": "break_retest",
        "direction": "bullish", "grade": "A+", "decision_score": 95, "entry": 600, "invalidation": 597,
    }])
    outcomes = tmp_path / "outcomes.jsonl"
    _write_jsonl(outcomes, [{"plan_id": "plan-1", "outcome_r": 1.4, "resolved_at": "2026-08-21T20:00:00Z"}])

    report = build_report(
        day="2026-08-21",
        sources={"live_opportunity": source},
        outcome_paths=[outcomes],
        now=NOW,
    )

    assert report["summary"]["outcome_resolved_count"] == 1
    assert report["summary"]["outcome_followup_count"] == 0
    assert report["items"][0]["outcome_review_status"] == "resolved"
    assert report["items"][0]["outcome"]["outcome_r"] == 1.4


def test_scheduler_runs_two_weekday_reviews_before_loop_closure() -> None:
    repo = Path(__file__).resolve().parents[2]
    runner = (repo / "scripts" / "run_daily_aplus_review.ps1").read_text(encoding="utf-8")
    register = (repo / "scripts" / "register_daily_aplus_review_task.ps1").read_text(encoding="utf-8")

    assert "daily_aplus_review.py --print" in runner
    assert "[string]$PythonPath" in runner
    assert "$LASTEXITCODE" in runner
    assert "daily-aplus-review.log" in runner
    assert 'TaskName "DailyAPlusReview"' in register
    assert 'TaskPath "\\VibeTrade\\"' in register
    assert "5:45PM" in register
    assert "7:55PM" in register
    assert "Monday,Tuesday,Wednesday,Thursday,Friday" in register
    assert "RunLevel Limited" in register
    assert "Read-only; no orders" in register
    assert "sys.executable" in register
    assert '-PythonPath `"$pythonPath`"' in register


def test_unresolved_aplus_setup_is_carried_forward_and_reviewed_again() -> None:
    prior = {
        "date": "2026-08-20",
        "items": [{
            "review_id": "spy-cisd-1",
            "source": "pattern_grader",
            "symbol": "SPY",
            "setup": "ict_cisd_universal_model",
            "direction": "bearish",
            "grade": "A",
            "grade_basis": "canonical_highest_a",
            "score": 91,
            "detected_at": "2026-08-20T15:00:00Z",
            "first_detected_at": "2026-08-20T15:00:00Z",
            "last_detected_at": "2026-08-20T15:00:00Z",
            "observation_count": 1,
            "max_score": 91,
            "entry": 650,
            "invalidation": 652,
            "blockers": [],
            "geometry_complete": True,
            "system_review_status": "reviewed",
            "outcome_review_status": "pending",
            "outcome": {},
            "verdict": "reviewed_outcome_pending",
        }],
    }

    report = build_report(
        day="2026-08-21",
        sources={},
        outcome_paths=[],
        prior_reports=[prior],
        now=NOW,
    )

    assert report["summary"]["carried_followup_count"] == 1
    assert report["summary"]["outcome_followup_count"] == 1
    assert report["summary"]["system_reviewed_setup_count"] == 1
    assert report["items"][0]["is_carry_forward"] is True
    assert report["items"][0]["origin_date"] == "2026-08-20"
    assert report["items"][0]["system_review_status"] == "reviewed"


def test_later_resolved_snapshot_is_not_carried_forward() -> None:
    pending = {
        "date": "2026-08-19",
        "items": [{"source": "pattern_grader", "review_id": "done-1", "outcome_review_status": "pending"}],
    }
    resolved = {
        "date": "2026-08-20",
        "items": [{"source": "pattern_grader", "review_id": "done-1", "outcome_review_status": "resolved"}],
    }

    report = build_report(
        day="2026-08-21",
        sources={},
        outcome_paths=[],
        prior_reports=[pending, resolved],
        now=NOW,
    )

    assert report["summary"]["carried_followup_count"] == 0
    assert report["items"] == []
