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


# --- Close cost quality caps ---

def _twin_base() -> dict:
    return {
        "earned_confidence": {"score": 7.0, "evidence_cap": 8.0, "blockers": []},
        "candidate_count": 10,
        "resolved_count": 15,
        "distinct_candidate_dates": 10,
        "entry_quote_coverage": 0.9,
        "mark_quote_coverage": 0.85,
        "close_cost_quality": {},
        "deflated_sharpe": {},
        "drawdown": {"max_consecutive_losses": 2},
    }


def test_high_close_friction_caps_counterfactual_at_four() -> None:
    sources = _sources()
    twin = _twin_base()
    twin["close_cost_quality"] = {"status": "high_close_friction", "avg_close_friction_pct_of_mid": 0.22}
    sources["options_twin"] = twin

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Counterfactual gate quality")

    assert cat["evidence_cap"] <= 4.0
    assert cat["score"] <= 4.0
    assert any("round-trip TCA" in b for b in cat["blockers_to_10"])


def test_watch_close_friction_caps_counterfactual_at_seven() -> None:
    sources = _sources()
    twin = _twin_base()
    twin["close_cost_quality"] = {"status": "watch_close_friction", "avg_close_friction_pct_of_mid": 0.09}
    sources["options_twin"] = twin

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Counterfactual gate quality")

    assert cat["evidence_cap"] <= 7.0
    assert any("5–15%" in b for b in cat["blockers_to_10"])


def test_ok_close_friction_does_not_add_cap() -> None:
    sources = _sources()
    twin = _twin_base()
    twin["close_cost_quality"] = {"status": "ok", "avg_close_friction_pct_of_mid": 0.02}
    sources["options_twin"] = twin

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Counterfactual gate quality")

    assert not any("round-trip TCA" in b for b in cat["blockers_to_10"])


# --- Deflated Sharpe caps ---

def test_negative_dsr_caps_counterfactual_at_three() -> None:
    sources = _sources()
    twin = _twin_base()
    twin["deflated_sharpe"] = {"status": "ok", "dsr": 0.35, "sr_per_trade": -0.5}
    sources["options_twin"] = twin

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Counterfactual gate quality")

    assert cat["evidence_cap"] <= 3.0
    assert any("probability of positive edge" in b for b in cat["blockers_to_10"])


def test_weak_dsr_caps_counterfactual_at_six() -> None:
    sources = _sources()
    twin = _twin_base()
    twin["deflated_sharpe"] = {"status": "ok", "dsr": 0.58, "sr_per_trade": 0.1}
    sources["options_twin"] = twin

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Counterfactual gate quality")

    assert cat["evidence_cap"] <= 6.0
    assert any("50–65%" in b for b in cat["blockers_to_10"])


def test_strong_dsr_does_not_add_cap() -> None:
    sources = _sources()
    twin = _twin_base()
    twin["deflated_sharpe"] = {"status": "ok", "dsr": 0.82, "sr_per_trade": 0.6}
    sources["options_twin"] = twin

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Counterfactual gate quality")

    assert not any("probability of positive edge" in b for b in cat["blockers_to_10"])


def test_insufficient_n_dsr_does_not_apply_cap() -> None:
    sources = _sources()
    twin = _twin_base()
    twin["deflated_sharpe"] = {"status": "insufficient_n", "dsr": None}
    sources["options_twin"] = twin

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Counterfactual gate quality")

    assert not any("probability of positive edge" in b for b in cat["blockers_to_10"])


# --- Drawdown streak cap ---

def test_high_consecutive_loss_rate_caps_counterfactual_at_five() -> None:
    sources = _sources()
    twin = _twin_base()
    twin["resolved_count"] = 12
    twin["drawdown"] = {"max_consecutive_losses": 5}
    sources["options_twin"] = twin

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Counterfactual gate quality")

    # 5/12 = 42% ≥ 30% threshold
    assert cat["evidence_cap"] <= 5.0
    assert any("consecutive losses" in b for b in cat["blockers_to_10"])


def test_low_consecutive_loss_rate_does_not_cap() -> None:
    sources = _sources()
    twin = _twin_base()
    twin["resolved_count"] = 30
    twin["drawdown"] = {"max_consecutive_losses": 4}
    sources["options_twin"] = twin

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Counterfactual gate quality")

    assert not any("consecutive losses" in b for b in cat["blockers_to_10"])


def test_missing_nbbo_curriculum_caps_counterfactual_at_four() -> None:
    sources = _sources()
    sources["options_twin"] = _twin_base()

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Counterfactual gate quality")

    assert cat["evidence_cap"] <= 4.0
    assert any("NBBO curriculum is missing" in b for b in cat["blockers_to_10"])


def test_failed_nbbo_curriculum_caps_counterfactual_at_four() -> None:
    sources = _sources()
    sources["options_twin"] = _twin_base()
    sources["options_nbbo_curriculum"] = {
        "status": "coverage_unavailable",
        "resolved_count": 0,
        "lifecycle_coverage": 0.0,
        "review_gate": {"passed": False},
    }

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Counterfactual gate quality")

    assert cat["evidence_cap"] <= 4.0
    assert any("locked-holdout review" in b for b in cat["blockers_to_10"])


def test_licensed_nbbo_history_replaces_stale_missing_history_blocker() -> None:
    sources = _sources()
    twin = _twin_base()
    twin["earned_confidence"]["blockers"] = [
        "OPRA NBBO history or equivalent executable quote evidence is required above 8/10."
    ]
    sources["options_twin"] = twin
    sources["options_nbbo_curriculum"] = {
        "status": "review_gate_failed",
        "resolved_count": 2,
        "lifecycle_coverage": 1.0,
        "accepted_nbbo_quote_count": 207_997,
        "review_gate": {"passed": False},
    }

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Counterfactual gate quality")

    assert cat["evidence_cap"] <= 4.0
    assert not any(blocker.startswith("OPRA NBBO history") for blocker in cat["blockers_to_10"])
    assert any("Forward shadow marks remain indicative" in blocker for blocker in cat["blockers_to_10"])


def test_missing_chronological_calibration_caps_mature_counterfactual_at_six() -> None:
    sources = _sources()
    twin = _twin_base()
    twin["resolved_count"] = 30
    twin["calibration"] = {"chronological_holdout": {"status": "insufficient_holdout"}}
    sources["options_twin"] = twin

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Counterfactual gate quality")

    assert cat["evidence_cap"] <= 6.0
    assert any("Chronological probability holdout" in b for b in cat["blockers_to_10"])


def test_negative_chronological_calibration_skill_caps_at_four() -> None:
    sources = _sources()
    twin = _twin_base()
    twin["resolved_count"] = 40
    twin["calibration"] = {
        "chronological_holdout": {
            "status": "ok",
            "brier_skill_vs_expanding_base_rate": -0.12,
        }
    }
    sources["options_twin"] = twin

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Counterfactual gate quality")

    assert cat["evidence_cap"] <= 4.0
    assert any("do not beat the expanding base rate" in b for b in cat["blockers_to_10"])


# --- Time-bucket Sortino cap on entry quality ---

def _bucket_row(sortino: float | None, completed: int = 15) -> dict:
    return {"completed_count": completed, "sortino_ratio": sortino, "expectancy_return_pct": 5.0}


def test_all_negative_sortino_buckets_reduce_entry_cap() -> None:
    sources = _sources(closed=50)
    sources["time_buckets"] = {
        "min_bucket_ranking_completed": 10,
        "shadow_selector_rankings": [_bucket_row(-0.8), _bucket_row(-0.3), _bucket_row(-1.2)],
    }
    sources["learning"]["rolling_actual"]["window_start"] = "2026-02-01"

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Entry quality")

    assert any("negative Sortino" in b for b in cat["blockers_to_10"])


def test_any_positive_sortino_bucket_does_not_add_blocker() -> None:
    sources = _sources(closed=50)
    sources["time_buckets"] = {
        "min_bucket_ranking_completed": 10,
        "shadow_selector_rankings": [_bucket_row(0.5), _bucket_row(-0.3)],
    }

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Entry quality")

    assert not any("negative Sortino" in b for b in cat["blockers_to_10"])


def test_empty_time_buckets_does_not_break_entry_scoring() -> None:
    sources = _sources()
    sources["time_buckets"] = {}

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Entry quality")

    assert cat["score"] >= 0
    assert report["execution_enabled"] is False


def test_no_robust_market_structure_cohort_caps_entry_at_six() -> None:
    sources = _sources(closed=150)
    sources["learning"]["rolling_actual"]["window_start"] = "2025-01-01"
    sources["time_buckets"] = {
        "market_structure_walk_forward": {
            "cohort_count": 29,
            "statistical_gate_ready_count": 0,
        },
    }

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Entry quality")

    assert cat["evidence_cap"] == 6.0
    assert "market_structure_cohorts=29" in cat["evidence"]
    assert any("No market-structure setup cohort passes" in b for b in cat["blockers_to_10"])


def test_robust_market_structure_cohort_adds_evidence_without_execution_authority() -> None:
    sources = _sources(closed=150)
    sources["learning"]["rolling_actual"]["window_start"] = "2025-01-01"
    sources["time_buckets"] = {
        "market_structure_walk_forward": {
            "cohort_count": 29,
            "statistical_gate_ready_count": 1,
        },
    }

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Entry quality")

    assert "market_structure_gate_ready=1" in cat["evidence"]
    assert not any("No market-structure setup cohort passes" in b for b in cat["blockers_to_10"])
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_failed_historical_scenario_curriculum_caps_entry_at_six() -> None:
    sources = _sources(closed=150)
    sources["learning"]["rolling_actual"]["window_start"] = "2025-01-01"
    sources["scenario_curriculum"] = {
        "execution_enabled": False,
        "can_submit_orders": False,
        "review_gate": {"passed": False},
        "walk_forward_summary": {"base": {"expectancy_bps": -2.74}},
        "locked_holdout": {"result": {"base": {"expectancy_bps": -2.80}}},
    }

    report = scorecard.build_report(sources, today=date(2026, 7, 13))
    cat = next(c for c in report["categories"] if c["name"] == "Entry quality")

    assert cat["evidence_cap"] == 6.0
    assert "scenario_curriculum_passed=False" in cat["evidence"]
    assert any("market-scenario curriculum failed" in blocker for blocker in cat["blockers_to_10"])
