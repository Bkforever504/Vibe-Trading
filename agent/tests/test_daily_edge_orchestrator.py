from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import daily_edge_orchestrator as edge


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_report_creates_morning_targets_and_runner_detection(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _write(
        reports / "candlestick-context.json",
        {
            "items": [
                {
                    "symbol": "AAPL",
                    "bias": "bullish",
                    "primary_signal": "bullish_engulfing_reclaim",
                    "allowed_playbooks": ["directional_long_call"],
                    "veto_reasons": [],
                }
            ]
        },
    )
    _write(
        reports / "higher-timeframe-market-map.json",
        {
            "items": [
                {
                    "symbol": "AAPL",
                    "primary_bias": "bullish",
                    "intraday_alignment": "aligned",
                    "allowed_playbooks": ["directional_long_call"],
                    "veto_reasons": [],
                }
            ]
        },
    )
    _write(reports / "market-catalyst-calendar.json", {"today": {"max_impact": "none", "vetoes": [], "events": []}})
    _write(
        reports / "options-liquidity-feasibility.json",
        {"results": [{"symbol": "AAPL", "verdict": "qualified", "score": 5, "flip_shadow_eligible": True}]},
    )
    _write(
        reports / "cheap-asymmetry-scanner.json",
        {
            "top_candidates": [
                {
                    "symbol": "AAPL",
                    "right": "CALL",
                    "option_symbol": "AAPL260707C00310000",
                    "cost_at_open": 19.0,
                    "best_return_pct": 1483.0,
                    "simulated_return_pct": 900.0,
                    "goal_match": True,
                    "quality_score": 10.0,
                }
            ]
        },
    )
    _write(
        reports / "shadow-consensus-gate.json",
        {
            "kill_switch": {"active": False},
            "decisions": [
                {
                    "symbol": "AAPL",
                    "recommendation": "size_down",
                    "options_playbook": "directional_long_call",
                    "blockers": [],
                    "reasons": ["market_mastery_call_playbook"],
                }
            ],
        },
    )

    report = edge.build_report(day="2026-07-07", report_dir=reports)

    target = report["morning_targets"][0]
    assert target["symbol"] == "AAPL"
    assert target["lane"] == "precision_watch"
    assert "cheap_goal_match" in target["reasons"]
    assert "htf_bullish_aligned" in target["reasons"]
    assert "directional_long_call" in target["allowed_playbooks"]
    runner = report["runner_detection"][0]
    assert runner["symbol"] == "AAPL"
    assert runner["state"] == "active_shadow_runner"
    assert runner["best_return_pct"] == 1483.0


def test_build_report_explains_no_trades_and_exit_accountability(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _write(reports / "candlestick-context.json", {"items": []})
    _write(reports / "higher-timeframe-market-map.json", {"items": []})
    _write(reports / "market-catalyst-calendar.json", {"today": {"max_impact": "high", "vetoes": ["size_down_required"]}})
    _write(reports / "options-liquidity-feasibility.json", {"results": []})
    _write(reports / "cheap-asymmetry-scanner.json", {"top_candidates": []})
    _write(reports / "shadow-consensus-gate.json", {"kill_switch": {"active": True}, "decisions": []})
    _write(
        reports / "loop-closure-report.json",
        {
            "trade_explanations": [
                {
                    "bot": "flip_bot",
                    "symbol": "SPY",
                    "pnl": 100.0,
                    "exit_reason": "PROFIT PROTECT +17%",
                    "exit_quality": {"best_pnl_pct": 66.0, "exit_return_pct": 17.0, "giveback_pct": 49.0, "capture_efficiency": 0.258},
                    "lesson": "tighten profit-capture cadence",
                }
            ],
            "no_trade_explanations": [
                {
                    "bot": "iwm_options_bot",
                    "symbol": "IWM",
                    "strategy": "put_spread",
                    "primary_reason": "credit_to_risk_below_minimum",
                    "explanation": "premium was not rich enough for the risk",
                }
            ],
        },
    )

    report = edge.build_report(day="2026-07-07", report_dir=reports)

    assert report["no_trade_explanations"][0]["why"] == "premium was not rich enough for the risk"
    exit_row = report["exit_accountability"][0]
    assert exit_row["symbol"] == "SPY"
    assert exit_row["verdict"] == "poor_capture"
    assert "tighten profit-capture cadence" in exit_row["lesson"]
    assert "portfolio_kill_switch_active" in report["global_blockers"]
    assert "high_impact_catalyst_day" in report["global_blockers"]


def test_scanner_leadership_ranks_ready_scanners_and_blocks_unproven_ones(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _write(reports / "candlestick-context.json", {"items": []})
    _write(reports / "higher-timeframe-market-map.json", {"items": []})
    _write(reports / "market-catalyst-calendar.json", {"today": {"max_impact": "none", "vetoes": []}})
    _write(reports / "options-liquidity-feasibility.json", {"results": []})
    _write(reports / "cheap-asymmetry-scanner.json", {"summary": {"goal_match_count": 2}, "top_candidates": []})
    _write(reports / "shadow-consensus-gate.json", {"kill_switch": {"active": False}, "decisions": []})
    _write(
        reports / "loop-closure-report.json",
        {
            "promotion_scoreboard": [
                {
                    "name": "Cheap Asymmetry Scanner",
                    "close_to_live_score": 82,
                    "promotion_state": "blocked",
                    "sample_count": 9,
                    "blockers": ["no_repeated_goal_matches"],
                },
                {
                    "name": "Market Force Score",
                    "close_to_live_score": 91,
                    "promotion_state": "context_ready",
                    "sample_count": 30,
                    "blockers": [],
                },
            ]
        },
    )
    _write(
        reports / "flip-bot-learning-report.json",
        {
            "selection_decision": {
                "execution_symbol": "SPY",
                "eligible_challengers": [],
                "non_spy_execution_allowed": False,
            },
            "rolling_actual": {"win_rate": 0.8, "net_pnl": 2538.0},
            "scanner_readiness": {
                "closest_to_use": [
                    {"name": "Options Liquidity Gate", "status": "gate_candidate", "use": "safety_gate", "reason": "reliable no-trade filter"}
                ]
            }
        },
    )

    report = edge.build_report(day="2026-07-07", report_dir=reports)

    leaders = {row["name"]: row for row in report["scanner_leadership"]}
    assert leaders["Market Force Score"]["recommended_use"] == "context_gate"
    assert leaders["Cheap Asymmetry Scanner"]["recommended_use"] == "shadow_only"
    assert report["flip_selection_decision"]["execution_symbol"] == "SPY"
    assert report["summary"]["flip_rolling_win_rate"] == 0.8
    assert report["summary"]["flip_rolling_net_pnl"] == 2538.0
    assert "no_repeated_goal_matches" in leaders["Cheap Asymmetry Scanner"]["blockers"]
    assert leaders["Options Liquidity Gate"]["recommended_use"] == "safety_gate"


def test_promising_not_ready_scanner_stays_shadow_only() -> None:
    assert edge._recommended_use("promising_not_ready", [], "Cheap Asymmetry Scanner") == "shadow_only"


def test_morning_targets_include_kronos_forecast_context(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    _write(reports / "candlestick-context.json", {"items": []})
    _write(reports / "higher-timeframe-market-map.json", {"items": []})
    _write(reports / "market-catalyst-calendar.json", {"today": {"max_impact": "none", "vetoes": []}})
    _write(reports / "options-liquidity-feasibility.json", {
        "results": [{"symbol": "NVDA", "verdict": "qualified", "score": 5, "flip_shadow_eligible": True}]
    })
    _write(reports / "cheap-asymmetry-scanner.json", {"top_candidates": []})
    _write(reports / "shadow-consensus-gate.json", {"kill_switch": {"active": False}, "decisions": []})
    _write(reports / "kronos-market-forecast.json", {
        "items": [
            {
                "symbol": "NVDA",
                "status": "ok",
                "forecast_direction": "bullish",
                "forecast_return_pct": 2.2,
                "confidence": 0.8,
            }
        ]
    })

    report = edge.build_report(day="2026-07-08", report_dir=reports)

    target = report["morning_targets"][0]
    assert target["symbol"] == "NVDA"
    assert "kronos_forecast_bullish" in target["reasons"]
    assert target["kronos_forecast"]["forecast_return_pct"] == 2.2
