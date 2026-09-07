from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import generate_dashboard as dashboard


ET = ZoneInfo("America/New_York")


def test_aplus_spotlight_hides_stale_or_prior_day_cards() -> None:
    now = datetime(2026, 8, 27, 10, 30, tzinfo=ET)
    setup = {"symbol": "CRM"}

    assert dashboard._current_aplus_setups(
        {
            "date": "2026-08-27",
            "generated_at": "2026-08-27T14:25:00Z",
            "setups": [setup],
        },
        now,
    ) == [setup]
    assert dashboard._current_aplus_setups(
        {
            "date": "2026-08-27",
            "generated_at": "2026-08-27T14:00:00Z",
            "setups": [setup],
        },
        now,
    ) == []
    assert dashboard._current_aplus_setups(
        {
            "date": "2026-08-26",
            "generated_at": "2026-08-27T14:25:00Z",
            "setups": [setup],
        },
        now,
    ) == []


def test_spotlight_card_displays_market_context_when_available() -> None:
    html = dashboard._render_spotlight_cards([
        {
            "symbol": "AAPL", "direction": "bullish", "setup": "opening_range_breakout",
            "score": 94.0, "entry": 200.0, "invalidation": 198.0, "target": 204.0,
            "risk_per_share": 2.0, "reward_per_share": 4.0,
            "market_context": {
                "sector_etf": "XLK", "sector_alignment": "supportive", "qqq_vs_spy_pct": 0.42,
            },
        }
    ], wrapper_cls="aplus")

    assert "XLK" in html
    assert "supportive" in html
    assert "QQQ-SPY +0.420%" in html


def test_dashboard_renders_spy_mapped_level_reaction_as_context_only() -> None:
    html = dashboard.render_spy_level_reaction({
        "spy_level_reaction": {
            "operational_health": "ok",
            "level_map": {"levels": [{"name": "previous_day_high", "price": 101.0}]},
            "summary": {"confirmed_reactions": 1, "extended_no_chase": 0},
            "spy0dte_feature_contract": {"early_session_cutoff_et": "11:15"},
            "gap_context": {"fill_bucket": "filled_within_30m"},
            "breadth_context": {"regime": "mixed"},
            "intermarket_context": {
                "qqq_vs_spy_pct": 0.24, "qqq_spy_regime": "qqq_leading_spy",
                "sector_leaders": [{"etf": "XLK", "vs_spy_pct": 0.31}],
            },
            "reactions": [{
                "level_name": "previous_day_high", "level": 101.0, "direction": "bearish",
                "status": "CONFIRMED_REACTION", "reaction_points": 0.52,
                "observed_at": "2026-08-28T09:45:00-04:00",
                "spy0dte_features": {
                    "touch_sequence": "first", "touch_count": 1,
                    "rsi_14_completed_5m": 27.4, "atr_normalized_approach_speed": -1.2,
                    "early_session_eligible": True,
                },
            }],
            "level_lifecycles": [{
                "level_name": "previous_day_high", "level": 101.0,
                "state": "FAILED_RETEST_FROM_BELOW", "touch_count": 2,
                "current_side": "below", "state_observed_at": "2026-08-28T09:45:00-04:00",
            }],
        }
    })

    assert "SPY Mapped-Level Reactions" in html
    assert "previous_day_high" in html
    assert "CONFIRMED_REACTION" in html
    assert "options-premium prediction" in html
    assert "filled_within_30m" in html
    assert "qqq_leading_spy" in html
    assert "SPY0DTE Features" in html
    assert "RSI(14)" in html
    assert "Independent completed-bar level lifecycle" in html
    assert "Level Lifecycle Context" in html
    assert "FAILED_RETEST_FROM_BELOW" in html


def test_dashboard_renders_orb_as_shadow_replay_not_alert() -> None:
    html = dashboard.render_spy_5m_0dte_orb({
        "spy_5m_0dte_orb": {
            "signal_count": 1,
            "resolved_option_quote_paths": 0,
            "promotion_blockers": ["licensed_opra_nbbo_or_equivalent_executable_quote_coverage_required"],
            "outcomes": [{
                "date": "2026-09-14", "direction": "call", "signal_bar_completed_at": "2026-09-14T09:36:00-04:00",
                "option_outcome": {"reason": "timestamped_option_bid_ask_required"},
            }],
        }
    })
    assert "SHADOW" in html
    assert "timestamped_option_bid_ask_required" in html
    assert "no rank, alert, sizing, or execution authority" in html


def test_dashboard_renders_confirmed_signal_as_simulated_paper_alert() -> None:
    html = dashboard.render_simulated_alert_feed({
        "simple_price_action_alerts": {
            "counts": {"CONFIRMED": 1, "WAIT": 1, "INVALID": 0},
            "signals": [{
                "state": "CONFIRMED", "symbol": "SPY", "direction": "LONG", "grade": "A-", "score": 82,
                "trigger": 650.0, "stop": 648.0, "target": 654.0,
                "bar_completed_at": "2026-09-02T10:05:00-04:00", "decisive_reason": "breakout_retest_hold",
            }],
        }
    })
    assert "Simulated real-time alert feed" in html
    assert "SHADOW ENTRY" in html
    assert "SPY" in html
    assert "no broker order is sent" in html


def test_governed_dashboard_scores_alerts_from_first_full_minute_after_discord() -> None:
    html = dashboard.render_governed_shadow_decision({
        "governed_alert": {"alerts_sent": 2, "dashboard_only": 5},
        "discord_chart_review": {
            "summary": {
                "delivered_trade_alerts": 12,
                "unique_trade_candidates": 8,
                "duplicate_trade_alerts": 4,
                "evaluated": 7,
                "positive_pct": 42.86,
                "median_r": -0.18,
                "status_counts": {"invalidated_before_entry": 3},
            },
            "chart_aligned_outcomes": [{"status": "scored", "latency_edge_decay_r": 0.4}],
            "bplus_to_aplus_nominations": {"nominations": [{"promotion_status": "human_review_required"}]},
            "alert_half_life_models": [{"status": "estimated"}],
        },
        "live_opportunity": {
            "event_time_intelligence": {"status": "observing", "symbols": {"QQQ": {}}, "hot_set": {"symbols": ["SPY", "QQQ", "DELL"]}},
            "discord_deadline_queue_shadow": {"selected": [{"candidate_id": "one"}]},
        },
    })

    assert "Post-Discord 1m Chart Review" in html
    assert "5 dashboard-only" in html
    assert "first full minute after delivery" in html
    assert "Invalid before entry" in html
    assert "not option-contract P&amp;L" in html
    assert "Signal-to-Chart Learning" in html
    assert "B+→A+ nominations" in html
    assert "human review only" in html
    assert "Event-Time Eyes" in html
    assert "revised bars" in html


def test_dashboard_renders_execution_readiness_without_promotion_authority() -> None:
    html = dashboard.render_execution_readiness({"execution_readiness": {"status": "NOT_READY", "criteria": [{"name": "SESSIONS", "status": "PENDING", "observed": 12, "required": 30, "days_remaining": 18}]}})
    assert "Live-Execution Readiness" in html
    assert "SESSIONS" in html
    assert "Automatic promotion" in html
    assert "cannot enable execution" in html


def test_dashboard_pins_named_liquid_focus_without_bypassing_gates() -> None:
    html = dashboard.render_session_focus({
        "intraday_radar": {
            "ranked_candidates": [{
                "symbol": "NVDA", "direction": "bullish", "grade": "B+", "score": 78.0, "price": 200.0,
                "confirmation_stage": "awaiting_completed_5m_confirmation",
                "hard_gates": {"completed_5m_structure": False, "underlying_spread": True},
                "trade_levels": {"confirmation_trigger": 201.0, "invalidation": 198.0, "target_2r": 207.0},
            }]
        }
    })
    assert "NVDA" in html and "GOOGL" in html and "AAPL" in html and "META" in html
    assert "completed 5m structure" in html
    assert "never bypasses" in html


def test_dashboard_renders_frozen_gap_outcome_slices_as_blocked_research() -> None:
    html = dashboard.render_spy_level_outcomes({
        "spy_level_outcomes": {
            "minimum_bucket_sample": 30,
            "summary": {
                "resolved_count": 2,
                "promotion_blockers": ["frozen_forward_sample_below_minimum"],
                "contract_feasibility": {"status": "unavailable", "reason": "quote_required"},
                "fixed_premium_proxy_plan": {"status": "non_executable_unvalidated"},
                "spy0dte_candidate_feature_slices": {"touch_sequence": [{"sample_count": 2}]},
                "gap_time_to_fill_slices": [{
                    "bucket": "filled_within_30m", "sample_count": 2, "win_rate": 0.5,
                    "mean_terminal_outcome_points": 0.12, "mean_mfe_points": 0.44, "mean_mae_points": -0.32,
                }],
            },
        }
    })

    assert "SPY Context Outcome Research" in html
    assert "filled_within_30m" in html
    assert "BLOCKED" in html
    assert "not option P&amp;L" in html
    assert "Contract Quotes" in html
    assert "non executable unvalidated" in html


def test_dashboard_overfit_guard_surfaces_a_failed_adversarial_audit() -> None:
    html = dashboard.render_overfit_guard({
        "adversarial_audit": {
            "summary": {"passed_count": 0, "blocked_count": 1},
            "subjects": [{
                "subject_id": "fresh-orb", "passed": False,
                "failed_checks": ["forward_expectancy_positive", "deflated_sharpe_passed"],
            }],
        },
        "elite_readiness": {"overall_score": 6.1, "status": "evidence_building"},
    })

    assert "Overfit Guard" in html
    assert "BLOCKED" in html
    assert "fresh-orb" in html
    assert "deflated sharpe passed" in html
    assert "no automatic promotion" in html


def test_flip_trade_stats_split_all_time_and_post_fix() -> None:
    trades = [
        {"status": "closed", "entry_date": "2026-06-23", "pnl": -11557.5},
        {"status": "closed", "entry_date": "2026-06-29", "pnl": 535.0},
        {"status": "closed", "entry_date": "2026-07-02", "pnl": 687.5},
    ]

    stats = dashboard.flip_trade_stats(trades)

    assert stats["total"] == 3
    assert stats["closed"] == 3
    assert stats["pnl"] == -10335.0
    assert stats["post_count"] == 2
    assert stats["post_pnl"] == 1222.5
    assert stats["post_win_rate"] == 1.0


def test_options_pnl_estimate_from_credit_close_reason() -> None:
    trade = {
        "net_credit": 0.52,
        "qty": 3,
        "closing_reason": "profit target hit: +55.8% of credit",
    }

    assert dashboard.parse_credit_pnl_estimate(trade) == 87.05


def test_chart_data_builds_cumulative_bot_series() -> None:
    model = {
        "flip_trades": [
            {"status": "closed", "entry_date": "2026-06-29", "exit_date": "2026-06-29", "pnl": 535},
            {"status": "closed", "entry_date": "2026-07-02", "exit_date": "2026-07-02", "pnl": 687.5},
        ],
        "options_state": {
            "trades": [
                {
                    "opened_at": "2026-06-29T14:45:09Z",
                    "closed_at": "2026-07-01T15:00:05Z",
                    "net_credit": 0.52,
                    "qty": 3,
                    "closing_reason": "profit target hit: +55.8% of credit",
                }
            ]
        },
        "hot": {
            "hot_instruments": [
                {"symbol": "TSLA", "hot_score": 14.55, "total_hypothetical_pnl": 11480, "best_shadow_return_pct": 1610.53}
            ]
        },
    }

    chart_data = dashboard.build_chart_data(model)

    assert chart_data["flipPnl"] == [
        {"time": "2026-06-29", "value": 535.0},
        {"time": "2026-07-02", "value": 1222.5},
    ]
    assert chart_data["iwmPnl"] == [{"time": "2026-07-01", "value": 87.05}]
    assert chart_data["hotRanked"][0]["symbol"] == "TSLA"


def test_render_loop_closure_shows_trade_skips_and_promotion_blockers() -> None:
    model = {
        "loop_closure": {
            "date": "2026-07-06",
            "summary": {
                "trade_explanation_count": 2,
                "no_trade_count": 1,
                "promotion_score_count": 2,
                "closed_trade_pnl": -175.0,
                "lesson_needed_count": 1,
                "entry_review_count": 1,
            },
            "trade_explanations": [
                {
                    "bot": "flip_bot",
                    "symbol": "SPY",
                    "strategy": "bull_trend",
                    "pnl": 67.5,
                    "exit_reason": "PROFIT PROTECT +17.3%",
                    "loop_state": "lesson_needed",
                    "lesson": "tighten profit-capture cadence",
                    "exit_quality": {"capture_efficiency": 0.262, "giveback_pct": 48.72},
                }
            ],
            "no_trade_explanations": [
                {
                    "bot": "iwm_options_bot",
                    "symbol": "IWM",
                    "strategy": "both",
                    "primary_reason": "underlying_exposure_cap",
                    "count": 2,
                    "explanation": "bot already had enough exposure",
                }
            ],
            "promotion_scoreboard": [
                {
                    "name": "Cheap Asymmetry Scanner",
                    "close_to_live_score": 82.0,
                    "promotion_state": "blocked",
                    "sample_count": 9,
                    "signal_count": 4,
                    "blockers": ["no_repeated_goal_matches"],
                }
            ],
            "next_day_gate": {
                "can_promote_scanner": False,
                "blockers": ["unresolved_high_severity_lessons"],
                "tomorrow_focus": "Resolve high-severity Flip lessons.",
            },
        }
    }

    html = dashboard.render_loop_closure(model)

    assert "Loop Closure" in html
    assert "tighten profit-capture cadence" in html
    assert "underlying_exposure_cap" in html
    assert "no_repeated_goal_matches" in html
    assert "Resolve high-severity Flip lessons." in html


def test_render_market_mastery_shows_catalysts_patterns_and_htf_alignment() -> None:
    model = {
        "market_catalyst": {
            "today": {
                "date": "2026-07-14",
                "max_impact": "high",
                "vetoes": ["new_short_premium_blocked", "size_down_required"],
                "events": [{"name": "CPI Release", "time_et": "08:30", "impact": "high"}],
            }
        },
        "candlestick_context": {
            "summary": {"bullish": 1, "bearish": 1, "neutral": 0},
            "items": [
                {
                    "symbol": "SPY",
                    "bias": "bullish",
                    "primary_signal": "bullish_engulfing_reclaim",
                    "allowed_playbooks": ["directional_long_call"],
                }
            ],
        },
        "higher_timeframe": {
            "summary": {"bullish": 1, "bearish": 0, "mixed": 0},
            "items": [
                {
                    "symbol": "SPY",
                    "primary_bias": "bullish",
                    "intraday_alignment": "aligned",
                    "allowed_playbooks": ["directional_long_call"],
                    "veto_reasons": [],
                }
            ],
        },
    }

    html = dashboard.render_market_mastery(model)

    assert "Market Mastery" in html
    assert "CPI Release" in html
    assert "new_short_premium_blocked" in html
    assert "bullish_engulfing_reclaim" in html
    assert "directional_long_call" in html
    assert "aligned" in html


def test_render_daily_edge_shows_targets_runners_exits_and_scanner_leaders() -> None:
    model = {
        "daily_edge": {
            "summary": {
                "precision_watch_count": 1,
                "runner_count": 1,
                "no_trade_explanation_count": 1,
                "poor_capture_count": 1,
                "flip_execution_symbol": "SPY",
                "flip_rolling_win_rate": 0.8,
                "flip_rolling_net_pnl": 2538.0,
            },
            "global_blockers": ["portfolio_kill_switch_active"],
            "morning_targets": [
                {
                    "symbol": "AAPL",
                    "lane": "precision_watch",
                    "score": 10,
                    "allowed_playbooks": ["directional_long_call"],
                    "reasons": ["cheap_goal_match", "htf_bullish_aligned"],
                    "blockers": [],
                }
            ],
            "runner_detection": [
                {"symbol": "AAPL", "state": "active_shadow_runner", "best_return_pct": 1483.0, "pattern": "bullish_engulfing_reclaim"}
            ],
            "no_trade_explanations": [
                {"symbol": "IWM", "primary_reason": "credit_to_risk_below_minimum", "why": "premium was not rich enough for the risk"}
            ],
            "exit_accountability": [
                {"symbol": "SPY", "verdict": "poor_capture", "giveback_pct": 49.0, "lesson": "tighten profit-capture cadence"}
            ],
            "scanner_leadership": [
                {"name": "Market Force Score", "recommended_use": "context_gate", "score": 91, "blockers": []}
            ],
        }
    }

    html = dashboard.render_daily_edge(model)

    assert "Daily Edge Orchestrator" in html
    assert "AAPL" in html
    assert "active_shadow_runner" in html
    assert "premium was not rich enough for the risk" in html
    assert "poor_capture" in html
    assert "Market Force Score" in html
    assert "80.0%" in html
    assert "$2,538.00" in html


def test_render_kronos_forecast_shows_shadow_context() -> None:
    model = {
        "kronos_forecast": {
            "summary": {"ok": 1, "bullish": 1, "bearish": 0, "unavailable": 0},
            "items": [
                {
                    "symbol": "SPY",
                    "status": "ok",
                    "forecast_direction": "bullish",
                    "forecast_return_pct": 1.2,
                    "max_drawdown_pct": -0.4,
                    "recommended_use": "shadow_context",
                }
            ],
        }
    }

    html = dashboard.render_kronos_forecast(model)

    assert "Kronos Market Forecaster" in html
    assert "SPY" in html
    assert "bullish" in html
    assert "shadow_context" in html


def test_shadow_health_displays_fail_closed_evidence_quarantine() -> None:
    html = dashboard.render_shadow_and_health({
        "health": {"summary": {"ok": 3, "stale": 0, "error": 0, "missing": 0}, "items": []},
        "shadow_audit": {
            "summary": {"performance_eligible_count": 2, "performance_quarantined_count": 24},
        },
    })

    assert "Performance Eligible" in html
    assert "Evidence Quarantined" in html
    assert ">24<" in html
    assert "cannot support performance or promotion claims" in html


def test_operational_gate_is_visibly_fail_closed() -> None:
    html = dashboard.render_operational_gate({
        "operational_gate": {
            "status": "observing",
            "operational_prerequisite_passed": False,
            "required_passing_sessions": 5,
            "passing_sessions_in_window": 2,
            "observed_sessions_in_window": 2,
            "current_session": {"session_date": "2026-08-31", "radar_coverage_clean": True, "signal_stack_clean": True},
            "blockers": ["Need 5 distinct passing sessions; observed=2."],
        }
    })
    assert "Operational Readiness Gate" in html
    assert "BLOCKED" in html
    assert "2/5" in html
    assert "no live authority" in html


def test_dashboard_html_renders_bot_trades_and_static_contract() -> None:
    model = {
        "generated_at": "2026-07-04 15:00:00 CDT",
        "bot_status": {
            "account": {"equity": 90795.87, "day_change": -197.0},
            "health": {"status": "error", "ok": 20, "stale": 15, "error": 2, "missing": 0},
            "market_force": {"classification": "bearish_lean", "score": -2.75, "confidence": 10},
            "exposure": {"posture": "cash_priority", "score": -4.25},
            "portfolio_concentration": {"risk_level": "normal", "gross_pct_equity": 3.258},
            "guard_blocks": {"alpaca": 173, "kalshi": 12},
        },
        "daily_eod": {"verdict": "action_required", "plain_english": {"headline": "Action required."}},
        "audit": {"passed": True, "registered_signal_count": 72, "issue_count": 0},
        "review": {"queue_count": 1, "by_reason": {"contracts_above_limit": 1}, "items": []},
        "position_sizing": {
            "configured_limits": {"max_contracts": 5, "max_risk_pct": 0.02},
            "candidate_sizing": {"risk_budget": 100},
            "post_config": {"max_contracts_seen": 5, "tail_bounds": {"empirical_tail_rate": 0}},
        },
        "grades": {
            "by_grade": {"B": 1, "F": 1},
            "by_ops_grade": {"A": 2},
            "promotion_ready_count": 0,
            "items": [
                {
                    "name": "Flip Bot",
                    "mode": "paper_or_live_alpaca",
                    "ops_grade": "B",
                    "grade": "F",
                    "warnings": ["all_time_includes_pre_config_artifact"],
                    "post_config": {"grade": "B"},
                },
                {
                    "name": "IWM Options Bot",
                    "mode": "paper_or_live_alpaca",
                    "ops_grade": "A",
                    "grade": "C",
                    "warnings": [],
                },
            ],
        },
        "health": {"summary": {"ok": 20, "stale": 15, "error": 2, "missing": 0}, "items": []},
        "hot": {"hot_instruments": []},
        "activity": [],
        "chart_data": {
            "accountEquity": [{"time": "2026-07-03", "value": 90795.87}],
            "flipPnl": [{"time": "2026-07-02", "value": 687.5}],
            "iwmPnl": [{"time": "2026-07-01", "value": 87.05}],
            "healthError": [{"time": "2026-07-03", "value": 2}],
            "healthStale": [{"time": "2026-07-03", "value": 15}],
            "opsA": [{"time": "2026-07-03", "value": 31}],
            "evidenceF": [{"time": "2026-07-03", "value": 27}],
            "hotRanked": [{"symbol": "TSLA", "hot_score": 14.55, "hypothetical_pnl": 11480.0}],
        },
        "positions": [],
        "positions_by_symbol": {},
        "flip_trades": [
            {
                "entry_date": "2026-07-02",
                "symbol": "SPY",
                "option_symbol": "SPY260702P00747000",
                "strategy": "bear_trend",
                "right": "PUT",
                "contracts": 5,
                "entry_price": 1.61,
                "exit_price": 2.985,
                "pnl": 687.5,
                "exit_reason": "PROFIT TARGET +85.4%",
                "status": "closed",
            }
        ],
        "options_state": {
            "trades": [
                {
                    "opened_at": "2026-06-29T14:45:09Z",
                    "label": "Put Spread [IWM]",
                    "legs": ["IWM260709P00289000", "IWM260709P00286000"],
                    "strategy": "put_spread",
                    "status": "closed",
                    "qty": 3,
                    "net_credit": 0.52,
                    "max_risk_per_contract": 248,
                    "closing_reason": "profit target hit: +55.8% of credit",
                    "candidate_confidence": {"score": 9},
                }
            ]
        },
        "loop_closure": {},
        "market_catalyst": {},
        "candlestick_context": {},
        "higher_timeframe": {},
        "daily_edge": {},
        "options_heatmap": {
            "symbol_count": 1,
            "ok_count": 1,
            "near_major_heat_zone_count": 1,
            "can_submit_orders": False,
            "results": [
                {
                    "symbol": "SPY",
                    "status": "ok",
                    "spot": 640.0,
                    "front_heat_state": "near_major_heat_zone",
                    "front_implied_move_pct": 0.85,
                    "front_put_call_open_interest_ratio": 1.2,
                    "nearest_heat_zone_below": {"strike": 638, "bias": "put_wall_support_proxy"},
                    "nearest_heat_zone_above": {"strike": 642, "bias": "call_wall_resistance_proxy"},
                    "gex_wall": {"strike": 640, "bias": "support"},
                    "condition_labels": ["spot_inside_heat_band"],
                    "top_heat_zones": [{"strike": 640}, {"strike": 642}],
                }
            ],
        },
    }

    html = dashboard.render_html(model)

    assert "Vibe Trading Control Room" in html
    assert "Daily Edge Orchestrator" in html
    assert "Market Mastery" in html
    assert "Options Liquidation Heat Map" in html
    assert "near_major_heat_zone" in html
    assert "No execution controls" in html
    assert "SPY260702P00747000" in html
    assert "Put Spread [IWM]" in html
    assert "$687.50" in html
    assert "$87.05 est." in html
    assert "lightweight-charts@5.2.0" in html
    assert 'id="chart-data"' in html
    assert "chart-account-equity" in html
    assert 'href="#daily-map"' in html
    assert 'id="daily-map"' in html
    assert "SHADOW SIMULATION ONLY · NO ORDERS" in html


def test_operational_run_evidence_requires_explicit_success_and_closed_breaker() -> None:
    current = datetime.now().astimezone().isoformat()
    rendered = dashboard.render_operational_runs({
        "operational_runs": {
            "schema_version": "run-envelope-v1",
            "status": "healthy",
            "summary": {"status": "healthy"},
            "components": [
                {
                    "run_id": "run-1",
                    "component": "intraday-radar",
                    "schema_version": "run-envelope-v1",
                    "status": "success",
                    "breaker_state": "CLOSED",
                    "finished_at": current,
                    "exit_code": 0,
                    "failure_class": None,
                    "last_success_at": current,
                    "data_as_of": current,
                    "freshness_seconds": 3,
                    "freshness_sla_seconds": 900,
                    "duration_ms": 1250,
                    "input_count": 40,
                    "output_count": 6,
                    "alerts_attempted": 2,
                    "alerts_delivered": 2,
                }
            ],
        }
    })
    assert "HEALTHY" in rendered
    assert "intraday-radar" in rendered
    assert "2/2" in rendered

    unknown = dashboard.render_operational_runs({"operational_runs": {}})
    assert "ATTENTION" in unknown
    assert "therefore not green" in unknown


def test_operational_run_evidence_escapes_failure_and_open_breaker_is_red() -> None:
    rendered = dashboard.render_operational_runs({
        "operational_runs": {
            "schema_version": "run-envelope-v1",
            "status": "healthy",
            "components": [{
                "component": "alert-delivery",
                "status": "timeout",
                "breaker": {"state": "OPEN"},
                "failure_class": "timeout",
                "error": "<script>alert('x')</script>",
                "next_action": "hold downstream alerts",
            }],
        }
    })
    assert "ATTENTION" in rendered
    assert "OPEN" in rendered
    assert "&lt;script&gt;" in rendered
    assert "<script>alert('x')</script>" not in rendered


def test_operational_run_evidence_requires_top_level_schema_and_consistent_status() -> None:
    current = datetime.now().astimezone().isoformat()
    component = {
        "schema_version": "run-envelope-v1", "component": "scanner", "status": "success",
        "breaker_state": "CLOSED", "finished_at": current, "data_as_of": current,
        "exit_code": 0, "failure_class": None, "freshness_sla_seconds": 900,
    }
    missing_schema = dashboard.render_operational_runs({
        "operational_runs": {"status": "healthy", "summary": {"status": "healthy"}, "components": [component]},
    })
    contradictory = dashboard.render_operational_runs({
        "operational_runs": {
            "schema_version": "run-envelope-v1", "status": "healthy",
            "summary": {"status": "attention"}, "components": [component],
        },
    })
    assert "ATTENTION" in missing_schema
    assert "ATTENTION" in contradictory


def test_daily_level_map_renders_fresh_shadow_confluence_without_proprietary_claims() -> None:
    current = datetime.now().astimezone().isoformat()
    rendered = dashboard.render_daily_level_map_shadow({
        "daily_level_map_shadow": {
            "schema_version": "daily-level-map-shadow-v1",
            "generated_at": current,
            "status": "healthy",
            "session_date": "2026-09-04",
            "freshness_sla_seconds": 900,
            "shadow_only": True,
            "execution_enabled": False,
            "can_submit_orders": False,
            "session_state": "rth",
            "coverage": {"requested": 2, "available": 2, "completed_3m_expected_now": True},
            "symbols": [
                {
                    "symbol": "SPY",
                    "daily_bias": "bullish",
                    "nearest_level": {
                        "price": 651.25,
                        "type": "prior_day_high",
                        "source": "market_data",
                        "provenance": "previous_completed_session",
                        "distance_points": 0.34,
                    },
                    "confirmation_3m": {
                        "state": "CONFIRMED",
                        "trigger": "3m close above 651.25 then hold",
                        "invalidation": 650.80,
                        "next_target": 652.50,
                        "bar_completed_at": current,
                    },
                },
                {
                    "symbol": "QQQ",
                    "daily_context": {"bias": "neutral"},
                    "nearest_level": {
                        "price": 584.10,
                        "type": "overnight_high",
                        "source": "market_data",
                        "provenance": "regularized_public_proxy",
                        "distance": 0.12,
                    },
                    "confirmation_3m": {
                        "state": "ARMED",
                        "trigger_price": 584.15,
                        "invalidation_rule": "3m close below 583.70",
                        "target_price": 585.00,
                        "observed_at": current,
                    },
                },
            ],
        }
    })
    assert "READY" in rendered
    assert "Daily Map &amp; 3m Confluence" in rendered
    assert "SPY" in rendered and "QQQ" in rendered
    assert "prior_day_high" in rendered
    assert "previous_completed_session" in rendered
    assert "CONFIRMED" in rendered and "ARMED" in rendered
    assert "3m close above 651.25 then hold" in rendered
    assert "SHADOW SIMULATION ONLY · NO ORDERS" in rendered
    assert "does not infer or reproduce proprietary formulas" in rendered


def test_daily_level_map_missing_malformed_or_stale_is_attention() -> None:
    missing = dashboard.render_daily_level_map_shadow({})
    assert "ATTENTION" in missing
    assert "unknown and therefore ATTENTION—not green" in missing

    stale = dashboard.render_daily_level_map_shadow({
        "daily_level_map_shadow": {
            "schema_version": "daily-level-map-shadow-v1",
            "generated_at": "2020-01-01T00:00:00+00:00",
            "status": "healthy",
            "freshness_sla_seconds": 900,
            "shadow_only": True,
            "execution_enabled": False,
            "can_submit_orders": False,
            "symbols": [{
                "symbol": "IWM",
                "daily_bias": "bearish",
                "nearest_level": {
                    "price": 231.5,
                    "type": "prior_day_low",
                    "source": "market_data",
                    "provenance": "previous_completed_session",
                },
                "confirmation_3m": {
                    "state": "WATCH",
                    "trigger": 231.4,
                    "invalidation": 232.0,
                    "next_target": 230.5,
                    "bar_completed_at": "2020-01-01T00:00:00+00:00",
                },
            }],
        }
    })
    malformed = dashboard.render_daily_level_map_shadow({
        "daily_level_map_shadow": {
            "schema_version": "daily-level-map-shadow-v1",
            "generated_at": datetime.now().astimezone().isoformat(),
            "status": "healthy",
            "symbols": [{"symbol": "SPY", "confirmation_3m": {"state": "CONFIRMED"}}],
        }
    })
    assert "ATTENTION" in stale and "STALE / UNKNOWN" in stale
    assert "ATTENTION" in malformed


def test_daily_level_map_premarket_is_ready_while_3m_is_explicitly_waiting() -> None:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rendered = dashboard.render_daily_level_map_shadow({
        "daily_level_map_shadow": {
            "schema_version": "daily-level-map-shadow-v1", "status": "ok", "generated_at": now,
            "freshness_sla_seconds": 900, "shadow_only": True, "execution_enabled": False,
            "can_submit_orders": False,
            "session_state": "premarket",
            "coverage": {"requested": 1, "available": 1, "completed_3m_expected_now": False},
            "symbols": [{
                "symbol": "SPY", "daily_bias": "BULLISH",
                "nearest_level": {"price": 650, "type": "premarket_high", "source": "completed_current_premarket_1m", "provenance": "reproducible_public_completed_bar", "distance_points": -0.2},
                "confirmation_3m": {"state": "PREMARKET", "trigger": 650, "bar_completed_at": now},
            }],
        }
    })
    assert "PREMARKET READY / 3M WAITING" in rendered
    assert "ATTENTION" not in rendered


def test_priority_universe_recall_separates_observation_from_execution_and_surfaces_debt() -> None:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rendered = dashboard.render_priority_universe_recall({
        "daily_move_coverage_review": {
            "schema_version": 5,
            "generated_at": now,
            "freshness_sla_seconds": 900,
            "execution_enabled": False,
            "can_submit_orders": False,
            "priority_universe_coverage": {
                "universe": ["SPY", "QQQ", "DELL"],
                "observation_coverage_pct": 66.67,
                "recall_pct": None,
                "recall_not_computable_reason": "provider_top_movers_do_not_supply_outcomes_for_omitted_priority_symbols",
                "symbols": [
                    {"symbol": "SPY", "evaluated": True, "outcome_status": "available_in_provider_top_movers", "coverage_debt": None},
                    {"symbol": "QQQ", "evaluated": True, "outcome_status": "unknown_not_in_provider_top_movers", "coverage_debt": None},
                    {"symbol": "DELL", "evaluated": False, "outcome_status": "unknown_not_in_provider_top_movers", "coverage_debt": "not_discovered"},
                ],
            },
            "moves": [{"symbol": "SPY", "stages": {"execution_qualified": False}, "risk_gate_status": "disqualified"}],
        }
    })

    assert "Priority-Universe Recall" in rendered
    assert "Observed / evaluated" in rendered
    assert "Execution-eligible" in rendered
    assert "DELL" in rendered and "not_discovered" in rendered
    assert "ATTENTION" in rendered
    assert "recall not computable" in rendered.lower()
    assert "No P/L or profitability is inferred" in rendered


def test_priority_universe_recall_missing_or_stale_is_attention() -> None:
    assert "ATTENTION" in dashboard.render_priority_universe_recall({})
    rendered = dashboard.render_priority_universe_recall({
        "daily_move_coverage_review": {
            "schema_version": 5,
            "generated_at": "2020-01-01T00:00:00Z",
            "freshness_sla_seconds": 60,
            "execution_enabled": False,
            "can_submit_orders": False,
            "priority_universe_coverage": {"universe": ["SPY"], "symbols": [{"symbol": "SPY", "evaluated": True}]},
        }
    })
    assert "ATTENTION" in rendered and "STALE" in rendered


def test_priority_alert_visibility_does_not_relabel_disqualified_observation() -> None:
    rendered = dashboard.render_simulated_alert_feed({
        "simple_price_action_alerts": {
            "counts": {"CONFIRMED": 0, "WAIT": 0, "INVALID": 1},
            "signals": [{
                "symbol": "DELL", "state": "INVALID", "direction": "LONG",
                "lane": "PRIORITY_FOCUS_SHADOW", "always_visible": True,
                "observation_visible": True, "execution_review_eligible": False,
                "execution_review_outcome": "do_not_take", "decisive_reason": "underlying_spread",
                "execution_enabled": False, "can_submit_orders": False,
            }],
        }
    })
    assert "DELL" in rendered
    assert "OBSERVE / DISQUALIFIED" in rendered
    assert "Observed" in rendered and "Execution-eligible" in rendered
    assert "NO" in rendered
    assert "no broker order is sent" in rendered


def test_persistent_swing_lifecycle_shows_state_age_transition_and_strict_eligibility() -> None:
    now = datetime.now(timezone.utc)
    changed = (now.replace(microsecond=0)).isoformat().replace("+00:00", "Z")
    rendered = dashboard.render_priority_swing_observation({
        "priority_swing_observation": {
            "schema_version": "priority-swing-observation-v1",
            "provider": "priority_swing_observation",
            "mode": "persistent_shadow_observation",
            "generated_at": changed,
            "freshness_sla_seconds": 900,
            "universe_source": "priority_swing_observation_v1_config",
            "priority_symbols": ["NVDA", "DELL"],
            "summary": {"symbols_requested": 2, "symbols_observed": 2, "errors": 0},
            "observations": [
                {
                    "symbol": "NVDA", "state": "ARMED", "previous_state": "WATCH",
                    "signal_date": "2026-09-04", "continuing_setup": True,
                    "validation_status": "unvalidated", "strict_execution_eligible": False,
                    "setup_family": "daily_trend_pullback", "trigger": 201.0, "invalidation": 194.0,
                    "completed_daily_evidence": {"status": "available", "latest_completed_date": "2026-09-04"},
                    "blockers": ["forward_sample_required"], "source_labels": ["daily_completed_bar"],
                    "execution_enabled": False, "can_submit_orders": False,
                },
                {
                    "symbol": "DELL", "state": "WATCH", "previous_state": "WATCH",
                    "signal_date": "2026-09-03", "continuing_setup": True,
                    "validation_status": "unvalidated", "strict_execution_eligible": False,
                    "setup_family": "daily_trend_pullback", "trigger": 140.0, "invalidation": 132.0,
                    "completed_daily_evidence": {"status": "available", "latest_completed_date": "2026-09-04"},
                    "blockers": ["confirmation_required"], "source_labels": ["daily_completed_bar"],
                    "execution_enabled": False, "can_submit_orders": False,
                },
            ],
            "transition_events": [],
            "execution_enabled": False,
            "can_submit_orders": False,
        },
        "priority_swing_events": [{
                "symbol": "NVDA", "previous_state": "WATCH", "state": "ARMED",
                "observed_at": changed,
        }],
    })
    assert "Persistent Swing Lifecycle" in rendered
    assert "NVDA" in rendered and "WATCH → ARMED" in rendered
    assert "State age" in rendered and "Last transition" in rendered
    assert "Execution-eligible" in rendered and "NO" in rendered
    assert "No P/L or profitability is inferred" in rendered
    assert "ATTENTION" not in rendered


def test_persistent_swing_lifecycle_missing_stale_or_bad_authority_is_attention() -> None:
    assert "ATTENTION" in dashboard.render_priority_swing_observation({})
    rendered = dashboard.render_priority_swing_observation({
        "priority_swing_observation": {
            "schema_version": "priority-swing-observation-v1", "provider": "priority_swing_observation",
            "generated_at": "2020-01-01T00:00:00Z", "freshness_sla_seconds": 60,
            "priority_symbols": ["SPY"], "observations": [], "transition_events": [],
            "execution_enabled": True, "can_submit_orders": False,
        }
    })
    assert "ATTENTION" in rendered and "STALE" in rendered
