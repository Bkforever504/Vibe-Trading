from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import flip_bot_learning_report as learning


def test_learning_report_flags_capture_gap_reentry_and_missed_asymmetry(tmp_path: Path) -> None:
    flip_trades = tmp_path / "flip-trades.json"
    postmortem = tmp_path / "closed-trade-postmortem.json"
    shadow = tmp_path / "flip-shadow-pnl-evaluator.json"
    asymmetry = tmp_path / "cheap-asymmetry-scanner.json"
    grades = tmp_path / "signal-stack-grades.json"
    grades.write_text(json.dumps({"promotion_ready_count": 0}), encoding="utf-8")

    flip_trades.write_text(
        json.dumps(
            [
                {
                    "id": "t1",
                    "symbol": "SPY",
                    "strategy": "bull_trend",
                    "right": "CALL",
                    "option_symbol": "SPY260706C00750000",
                    "entry_date": "2026-07-06T09:30:00-05:00",
                    "exit_date": "2026-07-06T10:30:00-05:00",
                    "entry_price": 0.78,
                    "exit_price": 0.915,
                    "best_pnl_pct": 66.03,
                    "pnl": 67.5,
                    "status": "closed",
                },
                {
                    "id": "t2",
                    "symbol": "SPY",
                    "strategy": "bull_trend",
                    "right": "CALL",
                    "option_symbol": "SPY260706C00751000",
                    "entry_date": "2026-07-06T11:00:00-05:00",
                    "exit_date": "2026-07-06T12:00:00-05:00",
                    "entry_price": 0.78,
                    "exit_price": 0.295,
                    "best_pnl_pct": -39.1,
                    "pnl": -242.5,
                    "status": "closed",
                },
            ]
        ),
        encoding="utf-8",
    )
    postmortem.write_text(
        json.dumps(
            {
                "date": "2026-07-06",
                "postmortems": [
                    {
                        "bot": "flip_bot",
                        "symbol": "SPY",
                        "pnl": 67.5,
                        "pnl_explanation": {
                            "exit_quality": {
                                "best_pnl_pct": 66.03,
                                "exit_return_pct": 17.31,
                                "giveback_pct": 48.72,
                                "capture_efficiency": 0.262,
                            }
                        },
                    },
                    {
                        "bot": "flip_bot",
                        "symbol": "SPY",
                        "pnl": -242.5,
                        "pnl_explanation": {"market_context": "bearish_lean"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    shadow.write_text(
        json.dumps(
            {
                "date": "2026-07-06",
                "top_trades": [
                    {
                        "symbol": "AAPL",
                        "right": "CALL",
                        "option_symbol": "AAPL260706C00312500",
                        "entry_price": 0.31,
                        "return_pct": 538.71,
                        "simulated_exit_return_pct": 129.03,
                        "capture_efficiency": 0.24,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    asymmetry.write_text(
        json.dumps(
            {
                "date": "2026-07-06",
                "top_candidates": [
                    {
                        "symbol": "AAPL",
                        "right": "CALL",
                        "option_symbol": "AAPL260706C00312500",
                        "cost_at_open": 31.0,
                        "best_return_pct": 538.71,
                        "simulated_return_pct": 129.03,
                        "goal_match": False,
                    }
                ],
                "summary": {"goal_match_count": 0},
            }
        ),
        encoding="utf-8",
    )

    report = learning.build_report(
        day="2026-07-06",
        flip_trades_path=flip_trades,
        postmortem_path=postmortem,
        shadow_path=shadow,
        asymmetry_path=asymmetry,
        grades_path=grades,
    )

    assert report["execution_enabled"] is False
    assert report["actual"]["closed_count"] == 2
    assert report["actual"]["net_pnl"] == -175.0
    assert report["rolling_actual"]["closed_count"] == 2
    assert report["rolling_actual"]["win_rate"] == 0.5
    assert report["rolling_actual"]["profit_factor"] == 0.28
    assert report["rolling_actual"]["avg_win"] == 67.5
    assert report["rolling_actual"]["avg_loss"] == 242.5
    assert report["rolling_actual"]["expectancy"] == -87.5
    assert report["rolling_actual"]["expectancy_status"] == "negative_or_unproven"
    assert report["rolling_actual"]["poor_capture_count"] == 1
    assert report["selection_decision"]["execution_symbol"] == "SPY"
    assert report["selection_decision"]["non_spy_execution_allowed"] is False
    lesson_types = {lesson["type"] for lesson in report["lessons"]}
    assert "negative_expectancy" in lesson_types
    assert "capture_gap" in lesson_types
    assert "same_day_reentry_loss" in lesson_types
    assert "missed_cheap_asymmetry" in lesson_types
    assert report["scanner_readiness"]["promotion_ready_count"] == 0
    assert report["scanner_readiness"]["closest_to_use"][0]["name"] == "Flip Shadow PnL Evaluator"


def test_loss_after_favorable_excursion_is_not_a_winner_capture_lesson() -> None:
    postmortems = [{
        "symbol": "SPY",
        "pnl_explanation": {"exit_quality": {
            "best_pnl_pct": 12.61, "exit_return_pct": -37.83,
            "exit_quality_classification": "stop_loss_after_favorable_excursion",
            "capture_efficiency": None, "giveback_pct": None,
            "favorable_excursion_surrendered_pct": 50.44,
        }},
    }]

    lessons = learning._capture_gap_lessons(postmortems)

    assert len(lessons) == 1
    assert lessons[0]["type"] == "stop_loss_after_favorable_excursion"
    assert lessons[0]["capture_efficiency"] is None
    assert "not winner-capture evidence" in lessons[0]["lesson"]
    assert "Winner faded" not in lessons[0]["lesson"]


def test_rolling_capture_metrics_exclude_losing_exit() -> None:
    trades = [{
        "id": "loss-after-green", "symbol": "SPY", "pnl": -37.83,
        "entry_price": 1.0, "exit_price": 0.6217, "best_pnl_pct": 12.61,
        "exit_reason": "STOP LOSS -37.8%",
    }]

    rolling = learning._rolling_quality_summary(trades, legacy_excluded=0)

    assert rolling["capture_sample_count"] == 0
    assert rolling["avg_capture_efficiency"] is None
    assert rolling["poor_capture_count"] == 0
    assert rolling["winner_to_loser_count"] == 1


def test_plain_fast_stop_becomes_canonical_entry_regime_lesson() -> None:
    postmortems = [{
        "trade_id": "fast-stop",
        "symbol": "SPY",
        "strategy": "bull_trend",
        "pnl": -119.0,
        "pnl_explanation": {
            "outcome": "loss",
            "primary_driver": "entry/regime failure: the option never moved favorably and hit stop within 10 minutes",
            "next_action": "require ORB/retest proof or cleaner regime",
            "exit_quality": {"exit_quality_classification": "stop_loss_no_favorable_excursion"},
        },
    }]

    lessons = learning._postmortem_outcome_lessons(postmortems)

    assert len(lessons) == 1
    assert lessons[0]["type"] == "entry_regime_failure"
    assert lessons[0]["status"] == "open"
    assert lessons[0]["requires_counterfactual"] is True
    assert lessons[0]["lesson"] == "require ORB/retest proof or cleaner regime"
