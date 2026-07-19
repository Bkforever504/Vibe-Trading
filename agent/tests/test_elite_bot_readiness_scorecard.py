from __future__ import annotations

from datetime import date

from scripts import elite_bot_readiness_scorecard as scorecard


def _sources(*, closed: int = 10, complete_exits: int = 0, promotion_count: int = 0) -> dict:
    tasks = [{"task": task, "aligned": True} for task in scorecard.AUTOMATION_TASKS]
    return {
        "health": {"summary": {"ok": 48, "stale": 0, "missing": 0, "error": 0}},
        "schedule": {"passed": True, "tasks": tasks},
        "execution_audit": {"passed": True},
        "reconciliation": {"reconciliation": {
            "status": "review_required", "entries_allowed": False,
            "unexplained_residual": {}, "closed_groups_still_open": [],
        }},
        "learning": {
            "rolling_actual": {
                "closed_count": closed, "window_start": "2026-06-29", "expectancy": 253.8,
                "profit_factor": 7.59, "payoff_ratio": 1.898, "win_rate": 0.8,
                "capture_sample_count": min(closed, 5), "net_pnl": 2538,
            },
            "next_learning_actions": ["review"], "scanner_readiness": {"promotion_ready_count": promotion_count},
        },
        "universe": {
            "execution_enabled": False, "can_submit_orders": False, "non_spy_execution_allowed": False,
            "rankings": [{"symbol": "SPY", "shadow_completed_count": 0, "shadow_trading_day_count": 0}],
            "execution_benchmark": {"symbol": "SPY", "options_liquidity_ok": True},
            "promotion_review_count": promotion_count, "shadow_challenger_count": 5,
        },
        "exit_quality": {
            "execution_enabled": False, "can_submit_orders": False, "closed_trade_count": closed,
            "complete_count": complete_exits, "trades": [],
        },
        "path_telemetry": {
            "execution_enabled": False, "can_submit_orders": False,
            "observed_complete_count": complete_exits, "synthetic_legacy_count": 0,
        },
        "risk_fail_closed": {
            "execution_enabled": False, "can_submit_orders": False,
            "passed": True, "case_count": 4,
        },
        "shadow": {"provider": "flip_shadow_pnl_evaluator"},
        "grades": {"provider": "signal_stack_grades"},
        "loop_closure": {"provider": "loop_closure_report"},
        "surface": {
            "provider": "options_surface_intelligence", "execution_enabled": False,
            "can_submit_orders": False, "institutional_flow_available": False, "ok_count": 8,
            "results": [{"symbol": "SPY", "status": "ok"}],
        },
        "ablation": {
            "provider": "flip_feature_ablation_report", "execution_enabled": False,
            "can_submit_orders": False, "feature_telemetry_trade_count": 0,
            "multiple_testing": {"all_observed_features_counted": True},
        },
        "trial_ledger": {
            "provider": "edge_trial_ledger", "execution_enabled": False,
            "can_submit_orders": False, "trial_count": 0, "trials": [],
            "multiple_testing": {"all_attempted_trials_counted": True},
        },
        "equity_curve": {
            "provider": "flip_equity_curve_report", "execution_enabled": False,
            "can_submit_orders": False,
            "summary": {"max_drawdown_dollars": -385.0, "account_equity_drawdown_available": False},
        },
    }


def test_small_sample_cannot_receive_unproven_tens() -> None:
    report = scorecard.build_report(_sources(), today=date(2026, 7, 13))
    by_name = {row["name"]: row for row in report["categories"]}

    assert by_name["Operational integrity"]["score"] == 10
    assert by_name["Risk controls"]["score"] == 10
    assert by_name["Entry quality"]["score"] <= 7
    assert by_name["Daily universe selection"]["score"] <= 5
    assert by_name["Exit quality"]["score"] <= 4
    assert by_name["Proven profitability"]["score"] <= 4
    assert by_name["Research validity"]["score"] <= 6
    assert report["all_categories_verified_10"] is False
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_missing_automation_cannot_score_autonomous_safety_ten() -> None:
    sources = _sources()
    sources["schedule"]["tasks"] = []

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    category = next(row for row in report["categories"] if row["name"] == "Autonomous safety")

    assert category["score"] < 10
    assert any("Align all required automation tasks" in blocker for blocker in category["blockers_to_10"])


def test_profitability_needs_drawdown_even_with_large_sample() -> None:
    sources = _sources(closed=250, complete_exits=60, promotion_count=1)
    sources["learning"]["rolling_actual"]["window_start"] = "2025-01-01"
    sources["universe"]["rankings"].append({"symbol": "QQQ", "shadow_completed_count": 60, "shadow_trading_day_count": 90})
    sources["equity_curve"] = {}

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    profitability = next(row for row in report["categories"] if row["name"] == "Proven profitability")

    assert profitability["evidence_cap"] == 9
    assert profitability["score"] <= 9
    assert any("maximum-drawdown" in blocker for blocker in profitability["blockers_to_10"])


def test_profitability_drawdown_unlocks_ten_only_after_large_durable_sample() -> None:
    sources = _sources(closed=250, complete_exits=60, promotion_count=1)
    sources["learning"]["rolling_actual"]["window_start"] = "2025-01-01"
    sources["universe"]["rankings"].append({"symbol": "QQQ", "shadow_completed_count": 60, "shadow_trading_day_count": 90})

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    profitability = next(row for row in report["categories"] if row["name"] == "Proven profitability")

    assert profitability["evidence_cap"] == 10
    assert profitability["score"] == 10
    assert not any("maximum-drawdown" in blocker for blocker in profitability["blockers_to_10"])


def test_exit_quality_uses_observed_path_telemetry_as_cross_check() -> None:
    sources = _sources(closed=60, complete_exits=40)
    sources["path_telemetry"]["observed_complete_count"] = 0

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    exit_quality = next(row for row in report["categories"] if row["name"] == "Exit quality")

    assert "complete_paths=0" in exit_quality["evidence"]
    assert any("exceeds observed path telemetry" in blocker for blocker in exit_quality["blockers_to_10"])
