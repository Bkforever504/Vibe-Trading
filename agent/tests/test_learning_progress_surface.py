from __future__ import annotations

from datetime import datetime, timezone

from scripts.live_trading_cockpit import _learning_progress_surface


def test_learning_progress_joins_unique_grades_with_frozen_move_evidence() -> None:
    item = {
        "review_id": "pd-one",
        "symbol": "DIA",
        "outcome_review_status": "resolved",
        "outcome": {"outcome_r": 2.0, "won": True},
        "blockers": ["post_friction_reward_risk_below_1_5"],
        "geometry_complete": True,
    }
    reports = {
        "move_coverage": {
            "date": "2026-08-26",
            "summary": {
                "movers_audited": 100,
                "source_discovery_recall_pct": 100.0,
                "early_detection_count": 43,
                "late_detection_count": 57,
                "actionable_early_count": 0,
                "risk_gate_qualified_count": 0,
            },
        },
        "detection_scorecard": {
            "sessions": 3,
            "metrics": {
                "ground_truth_count": 196,
                "precision_at_10_mean": 0.0,
                "recall_at_10": 0.0,
                "root_cause_coverage": 1.0,
            },
        },
        "grade_calibration": {
            "eligible_outcomes": 0,
            "skipped_outcomes": 605,
            "buckets": [],
        },
        "aplus_review": {
            "date": "2026-08-25",
            "items": [item, {**item, "source": "duplicate_source"}],
        },
        "elite_readiness": {"overall_score": 6.8, "status": "evidence_building", "all_categories_verified_10": False},
    }

    result = _learning_progress_surface(
        reports,
        {},
        now=datetime(2026, 8, 26, 18, 0, tzinfo=timezone.utc),
    )

    assert result["broad_move_audit"]["early_detection_pct"] == 43.0
    assert result["broad_move_audit"]["actionable_early_pct"] == 0.0
    assert result["graded_trade_outcomes"]["unique_top_tier_setups"] == 1
    assert result["graded_trade_outcomes"]["resolved"] == 1
    assert result["graded_trade_outcomes"]["average_r"] == 2.0
    assert result["live_readiness"]["ready"] is False
    assert "rolling_precision_at_10_not_positive" in result["live_readiness"]["blockers"]
    assert "fewer_than_100_calibration_eligible_outcomes" in result["live_readiness"]["blockers"]
    assert result["evidence_readiness"]["overall_score"] == 6.8
    assert result["execution_enabled"] is False


def test_learning_progress_can_only_reach_human_review_after_every_gate() -> None:
    reports = {
        "move_coverage": {
            "date": "2026-08-25",
            "summary": {
                "movers_audited": 10,
                "source_discovery_recall_pct": 100.0,
                "early_detection_count": 8,
                "late_detection_count": 2,
                "actionable_early_count": 4,
                "risk_gate_qualified_count": 4,
            },
        },
        "detection_scorecard": {
            "sessions": 30,
            "metrics": {"ground_truth_count": 150, "precision_at_10_mean": 0.3, "recall_at_10": 0.4},
        },
        "grade_calibration": {
            "eligible_outcomes": 100,
            "skipped_outcomes": 0,
            "buckets": [{"probability": {"calibration_qualified": True}}],
        },
        "aplus_review": {
            "date": "2026-08-25",
            "items": [{
                "review_id": "pd-one", "outcome_review_status": "resolved",
                "outcome": {"outcome_r": 1.0}, "blockers": [], "geometry_complete": True,
            }],
        },
        "elite_readiness": {"overall_score": 10.0, "status": "verified", "all_categories_verified_10": True},
    }

    result = _learning_progress_surface(
        reports,
        {},
        now=datetime(2026, 8, 26, 18, 0, tzinfo=timezone.utc),
    )

    assert result["live_readiness"]["ready"] is True
    assert result["status"] == "qualified_for_human_live_review"
    assert result["can_submit_orders"] is False
