from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import shadow_consensus_gate as gate


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_report_keeps_shadow_advisor_non_executing(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    data = tmp_path / "data"
    _write(reports / "signal-stack-grades.json", {
        "promotion_ready_count": 0,
        "items": [
            {"name": "Flip Shadow Candidates", "promotion_ready": False, "sample_count": 429},
            {"name": "Adaptive Options", "promotion_ready": False, "sample_count": 7},
        ],
    })
    _write(reports / "market-force-score.json", {
        "classification": "bearish_lean",
        "confidence": 10.0,
    })
    _write(reports / "flip-shadow-pnl-evaluator.json", {
        "by_symbol": {
            "SPY": {"completed_count": 8, "win_rate": 0.625, "total_hypothetical_pnl": 1200.0, "avg_giveback_pct": 18.0},
            "QQQ": {"completed_count": 6, "win_rate": 0.50, "total_hypothetical_pnl": 1375.0, "avg_giveback_pct": 29.17},
            "NVDA": {"completed_count": 3, "win_rate": 0.0, "total_hypothetical_pnl": 0.0, "avg_giveback_pct": 51.97},
        },
    })
    _write(reports / "adaptive-options-shadow-playbook.json", {
        "rows": [
            {
                "symbol": "SPY",
                "selected_playbook": "long_put",
                "action": "shadow_watch_bearish_long_put",
                "condition_summary": {"tradeable": True, "primary_regime": "bearish_trend"},
                "explanation": {"blockers": []},
            },
            {
                "symbol": "QQQ",
                "selected_playbook": "none",
                "action": "stand_aside",
                "condition_summary": {"tradeable": False, "primary_regime": "bearish_trend"},
                "explanation": {"blockers": ["Options liquidity gate failed"]},
            },
        ],
    })
    _write(reports / "options-liquidity-feasibility.json", {
        "results": [
            {"symbol": "SPY", "verdict": "qualified", "score": 4, "flip_shadow_eligible": True},
            {"symbol": "QQQ", "verdict": "borderline", "score": 3, "flip_shadow_eligible": False},
            {"symbol": "NVDA", "verdict": "not_qualified", "score": 1, "flip_shadow_eligible": False},
        ]
    })

    report = gate.build_report(day="2026-07-07", report_dir=reports, data_dir=data)

    assert report["provider"] == "shadow_consensus_gate"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["promotion_ready_count"] == 0
    assert report["summary"]["approve"] == 0
    assert report["summary"]["size_down"] >= 1
    spy = next(row for row in report["decisions"] if row["symbol"] == "SPY")
    qqq = next(row for row in report["decisions"] if row["symbol"] == "QQQ")
    nvda = next(row for row in report["decisions"] if row["symbol"] == "NVDA")
    assert spy["recommendation"] == "size_down"
    assert "shadow_not_promotion_ready" in spy["blockers"]
    assert spy["options_playbook"] == "long_put"
    assert qqq["recommendation"] == "stand_aside"
    assert "options_liquidity_blocked" in qqq["blockers"]
    assert nvda["recommendation"] == "stand_aside"
    assert "weak_shadow_pnl_evidence" in nvda["blockers"]


def test_kill_switch_forces_stand_aside(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    data = tmp_path / "data"
    _write(reports / "signal-stack-grades.json", {"promotion_ready_count": 0, "items": []})
    _write(reports / "market-force-score.json", {"classification": "bullish", "confidence": 8.0})
    _write(reports / "flip-shadow-pnl-evaluator.json", {
        "by_symbol": {
            "AAPL": {"completed_count": 5, "win_rate": 0.8, "total_hypothetical_pnl": 900.0, "avg_giveback_pct": 10.0}
        }
    })
    _write(reports / "options-liquidity-feasibility.json", {
        "results": [{"symbol": "AAPL", "verdict": "qualified", "score": 4, "flip_shadow_eligible": True}]
    })
    _write(reports / "adaptive-options-shadow-playbook.json", {"rows": []})
    _write(data / "PORTFOLIO_KILL_SWITCH.json", {
        "status": "killed",
        "manual_reset_required": True,
        "reason": "max_daily_loss",
    })

    report = gate.build_report(
        day="2026-07-07",
        report_dir=reports,
        data_dir=data,
        kill_switch_path=data / "PORTFOLIO_KILL_SWITCH.json",
    )

    decision = report["decisions"][0]
    assert decision["symbol"] == "AAPL"
    assert decision["recommendation"] == "stand_aside"
    assert "portfolio_kill_switch_active" in decision["blockers"]
    assert report["summary"]["stand_aside"] == 1


def test_write_report_and_log_round_trip(tmp_path: Path) -> None:
    report_path = tmp_path / "reports" / "shadow-consensus-gate.json"
    log_path = tmp_path / "data" / "shadow_consensus_gate_log.jsonl"
    report = {
        "date": "2026-07-07",
        "provider": "shadow_consensus_gate",
        "execution_enabled": False,
        "decisions": [],
    }

    gate.write_report(report, report_path, log_path)

    assert json.loads(report_path.read_text(encoding="utf-8")) == report
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert rows == [report]


def test_market_mastery_reports_block_short_premium_and_select_call_playbook(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    data = tmp_path / "data"
    _write(reports / "signal-stack-grades.json", {
        "promotion_ready_count": 1,
        "items": [{"name": "Flip Shadow Candidates", "promotion_ready": True}],
    })
    _write(reports / "market-force-score.json", {"classification": "bullish", "confidence": 9.0})
    _write(reports / "flip-shadow-pnl-evaluator.json", {
        "by_symbol": {
            "SPY": {
                "completed_count": 12,
                "win_rate": 0.67,
                "total_hypothetical_pnl": 2200.0,
                "avg_giveback_pct": 12.0,
            }
        }
    })
    _write(reports / "options-liquidity-feasibility.json", {
        "results": [{"symbol": "SPY", "verdict": "qualified", "score": 5, "flip_shadow_eligible": True}]
    })
    _write(reports / "adaptive-options-shadow-playbook.json", {"rows": []})
    _write(reports / "candlestick-context.json", {
        "items": [
            {
                "symbol": "SPY",
                "bias": "bullish",
                "primary_signal": "bullish_engulfing_reclaim",
                "allowed_playbooks": ["directional_long_call"],
                "veto_reasons": [],
            }
        ]
    })
    _write(reports / "higher-timeframe-market-map.json", {
        "items": [
            {
                "symbol": "SPY",
                "primary_bias": "bullish",
                "intraday_alignment": "aligned",
                "allowed_playbooks": ["directional_long_call"],
                "veto_reasons": [],
            }
        ]
    })
    _write(reports / "market-catalyst-calendar.json", {
        "today": {
            "date": "2026-07-14",
            "max_impact": "high",
            "vetoes": ["new_short_premium_blocked", "size_down_required"],
            "allowed_playbooks": ["stand_aside", "directional_long_post_confirmation"],
            "events": [{"name": "CPI Release", "impact": "high", "time_et": "08:30"}],
        }
    })

    report = gate.build_report(day="2026-07-14", report_dir=reports, data_dir=data)

    spy = next(row for row in report["decisions"] if row["symbol"] == "SPY")
    assert spy["options_playbook"] == "directional_long_call"
    assert "candlestick_bullish_engulfing_reclaim" in spy["reasons"]
    assert "higher_timeframe_bullish_aligned" in spy["reasons"]
    assert "catalyst_new_short_premium_blocked" in spy["blockers"]
    assert "short_premium" not in spy["permitted_actions"]


def test_kronos_forecast_is_context_not_execution_authority(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    data = tmp_path / "data"
    _write(reports / "signal-stack-grades.json", {"promotion_ready_count": 0, "items": []})
    _write(reports / "market-force-score.json", {"classification": "bullish", "confidence": 8.0})
    _write(reports / "flip-shadow-pnl-evaluator.json", {
        "by_symbol": {
            "SPY": {
                "completed_count": 8,
                "win_rate": 0.7,
                "total_hypothetical_pnl": 1200.0,
                "avg_giveback_pct": 12.0,
            }
        }
    })
    _write(reports / "options-liquidity-feasibility.json", {
        "results": [{"symbol": "SPY", "verdict": "qualified", "score": 5, "flip_shadow_eligible": True}]
    })
    _write(reports / "adaptive-options-shadow-playbook.json", {
        "rows": [
            {
                "symbol": "SPY",
                "selected_playbook": "directional_long_call",
                "action": "shadow_watch_bullish_long_call",
                "condition_summary": {"tradeable": True},
                "explanation": {"blockers": []},
            }
        ]
    })
    _write(reports / "kronos-market-forecast.json", {
        "items": [
            {
                "symbol": "SPY",
                "status": "ok",
                "forecast_direction": "bearish",
                "forecast_return_pct": -1.4,
                "confidence": 0.7,
                "recommended_use": "shadow_context",
            }
        ]
    })

    report = gate.build_report(day="2026-07-08", report_dir=reports, data_dir=data)

    spy = next(row for row in report["decisions"] if row["symbol"] == "SPY")
    assert spy["recommendation"] == "stand_aside"
    assert "kronos_forecast_bearish" in spy["reasons"]
    assert "kronos_conflicts_with_bullish_playbook" in spy["blockers"]
    assert "shadow_not_promotion_ready" in spy["blockers"]
