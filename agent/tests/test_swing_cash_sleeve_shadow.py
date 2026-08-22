from __future__ import annotations

from datetime import date

from scripts.swing_cash_sleeve_shadow import build_shadow_decision, completed_month_cutoff


def test_completed_month_cutoff_excludes_partial_current_month() -> None:
    assert str(completed_month_cutoff(date(2026, 8, 13)).date()) == "2026-07-31"


def test_shadow_decision_is_non_executable_and_blocks_concentration() -> None:
    candidates = [
        {
            "symbol": "NVDA",
            "price_trend": True,
            "period_return": 0.05,
            "momentum": 0.20,
        }
    ]
    context = {"breadth": 0.75, "features": {}, "spy_above_200": True}
    result = build_shadow_decision("2026-07-31", candidates, context)
    assert result["equity_exposure"] == 1.0
    assert result["maximum_position_weight"] == 1.0
    assert result["concentration_ok"] is False
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False
    assert "position_concentration_above_35pct" in result["blockers"]
