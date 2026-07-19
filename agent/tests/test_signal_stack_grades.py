from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import signal_stack_grades as grades


def test_grade_item_rewards_fresh_confident_mature_signal() -> None:
    item = {
        "name": "Test Shadow",
        "category": "shadow_strategy",
        "execution_mode": "shadow_only",
        "freshness": {"status": "fresh", "age_days": 0},
        "sample_count": 30,
        "signal_count": 10,
        "avg_confidence": 9.0,
        "bad_json_lines": 0,
        "blocked_count": 0,
        "total_pnl": None,
    }

    row = grades.grade_item(item)

    assert row["grade"] == "A"
    assert row["promotion_ready"] is True
    assert row["maturity_stage"] == "mature"


def test_grade_item_marks_low_sample_as_log_building() -> None:
    item = {
        "name": "New Scanner",
        "category": "context_scanner",
        "execution_mode": "read_only",
        "freshness": {"status": "fresh", "age_days": 0},
        "sample_count": 1,
        "signal_count": 0,
        "avg_confidence": None,
        "bad_json_lines": 0,
        "blocked_count": 0,
        "total_pnl": None,
    }

    row = grades.grade_item(item)

    assert row["promotion_ready"] is False
    assert row["maturity_stage"] == "log_building"
    assert "context_only" in row["warnings"]
    assert "not_enough_samples" in row["warnings"]


def test_grade_item_reports_post_config_performance() -> None:
    item = {
        "name": "Flip Bot",
        "category": "alpaca_options_execution",
        "execution_mode": "paper_or_live_alpaca",
        "freshness": {"status": "fresh", "age_days": 0},
        "sample_count": 8,
        "signal_count": 8,
        "avg_confidence": None,
        "bad_json_lines": 0,
        "blocked_count": 0,
        "total_pnl": -8702.0,
        "post_config": {
            "label": "post_risk_fix",
            "start_date": "2026-06-29",
            "sample_count": 7,
            "total_pnl": 2855.5,
            "win_rate": 1.0,
            "max_drawdown_dollars": 0.0,
        },
    }

    row = grades.grade_item(item)

    assert row["total_pnl"] == -8702.0
    assert row["post_config"]["total_pnl"] == 2855.5
    assert row["post_config"]["grade"] in {"B", "C"}
    assert "all_time_includes_pre_config_artifact" in row["warnings"]


def test_build_report_uses_leaderboard_items(monkeypatch) -> None:
    monkeypatch.setattr(
        grades.leaderboard,
        "build_leaderboard",
        lambda now: {
            "items": [
                {
                    "name": "A",
                    "category": "shadow_strategy",
                    "execution_mode": "shadow_only",
                    "freshness": {"status": "fresh"},
                    "sample_count": 30,
                    "signal_count": 10,
                    "avg_confidence": 9,
                    "bad_json_lines": 0,
                    "blocked_count": 0,
                    "total_pnl": None,
                },
                {
                    "name": "B",
                    "category": "context_scanner",
                    "execution_mode": "read_only",
                    "freshness": {"status": "missing"},
                    "sample_count": 0,
                    "signal_count": 0,
                    "avg_confidence": None,
                    "bad_json_lines": 0,
                    "blocked_count": 0,
                    "total_pnl": None,
                },
            ]
        },
    )

    report = grades.build_report(datetime(2026, 6, 30, tzinfo=timezone.utc))

    assert report["execution_enabled"] is False
    assert report["item_count"] == 2
    assert report["promotion_ready_count"] == 1
    assert report["by_grade"]["A"] == 1
