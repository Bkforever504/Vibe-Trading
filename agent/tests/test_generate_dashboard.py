from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import generate_dashboard as dashboard


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
    }

    html = dashboard.render_html(model)

    assert "Vibe Trading Control Room" in html
    assert "Daily Edge Orchestrator" in html
    assert "Market Mastery" in html
    assert "No execution controls" in html
    assert "SPY260702P00747000" in html
    assert "Put Spread [IWM]" in html
    assert "$687.50" in html
    assert "$87.05 est." in html
    assert "lightweight-charts@5.2.0" in html
    assert 'id="chart-data"' in html
    assert "chart-account-equity" in html
