from __future__ import annotations

import json

from scripts.kalshi_weather_performance_report import build_report


def test_performance_scores_profit_drawdown_and_calibration(tmp_path) -> None:
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "positions": [{"city": "Boston"}],
        "closed_positions": [
            {"promotion_grade": True, "city": "New York", "target_date": "2026-07-15", "pnl_dollars": 0.68, "risk_dollars": 0.32, "entry_fair_probability": 0.80, "entry_price": 0.60, "won": True, "exit_reason": "kalshi_finalized_yes"},
            {"promotion_grade": True, "city": "Chicago", "target_date": "2026-07-15", "pnl_dollars": -0.42, "risk_dollars": 0.42, "entry_fair_probability": 0.30, "entry_price": 0.30, "won": False, "exit_reason": "kalshi_finalized_no"},
            {"promotion_grade": False, "city": "Miami", "target_date": "2026-07-15", "pnl_dollars": 10.0, "risk_dollars": 1.0, "won": True, "exit_reason": "manual"},
        ],
    }), encoding="utf-8")

    report = build_report(state)

    assert report["promotion_grade_closed_count"] == 2
    assert report["metrics"]["net_pnl_dollars"] == 0.26
    assert report["metrics"]["profit_factor"] == 1.619
    assert report["metrics"]["max_drawdown_dollars"] == 0.42
    assert report["calibration"]["model_brier_score"] == 0.065
    assert report["calibration"]["market_brier_score"] == 0.125
    assert report["calibration"]["brier_skill_vs_market"] == 0.06
    assert report["distinct_city_days"] == 2


def test_performance_never_enables_execution(tmp_path) -> None:
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")
    report = build_report(state)
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
