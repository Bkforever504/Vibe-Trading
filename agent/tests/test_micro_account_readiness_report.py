from scripts import micro_account_readiness_report as report
from scripts.momentum_shadow_logger import micro_account_plan


def test_micro_account_plan_uses_half_cash_and_fractional_shares() -> None:
    plan = micro_account_plan(["XLK", "IWM"], {"XLK": 250.0, "IWM": 125.0})
    assert plan["target_gross_exposure"] == 500.0
    assert plan["cash_reserve"] == 500.0
    assert plan["allocations"]["XLK"]["target_notional"] == 250.0
    assert plan["allocations"]["XLK"]["fractional_shares"] == 1.0
    assert plan["can_submit_orders"] is False


def test_micro_account_report_rejects_observed_spy_contract_granularity() -> None:
    trades = [
        {"status": "closed", "entry_date": "2026-06-29", "entry_price": 1.0, "contracts": 5, "pnl": 100.0, "strategy": "bull_trend"},
        {"status": "closed", "entry_date": "2026-07-01", "entry_price": 0.70, "contracts": 5, "pnl": -50.0, "strategy": "bear_trend"},
    ]
    public_lab = {"strategies": [{
        "strategy": "micro_account_50pct_dual_momentum_50pct_cash",
        "forward_2025_plus": {"total_return_pct": 20.0, "max_drawdown_pct": 7.0},
    }]}
    result = report.build_report(trades, public_lab)
    assert result["risk_policy"]["max_risk_dollars"] == 20.0
    assert result["flip_options_lane"]["full_premium_fit_count_at_risk_budget"] == 0
    assert result["flip_options_lane"]["planned_30pct_stop_fit_count_at_risk_budget"] == 0
    assert result["flip_options_lane"]["status"] == "paper_observation_only"
    assert result["fractional_momentum_lane"]["status"] == "isolated_virtual_paper_active"
    assert result["readiness"]["live_ready"] is False
