from __future__ import annotations

from research.trading_style_tournament_report import build_report


def test_report_keeps_execution_disabled_and_does_not_promote_failed_styles() -> None:
    report = build_report()
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["promotion_ready_style"] is None
    assert all(row["promotion_ready"] is False for row in report["styles"])


def test_monthly_swing_is_research_leader_and_scalps_are_negative() -> None:
    report = build_report()
    rows = {row["style"]: row for row in report["styles"]}
    assert report["most_profitable_research_style"] == "monthly_cross_sectional_swing_momentum"
    assert rows["monthly_cross_sectional_swing_momentum"]["stress_expectancy"] > 0
    assert rows["mes_ofi_momentum_scalp"]["stress_expectancy"] < 0
    assert rows["mes_ofi_reversal_scalp"]["stress_expectancy"] < 0
