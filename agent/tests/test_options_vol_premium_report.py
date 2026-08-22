from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.options_vol_premium_report import (
    build_report,
    capture_entry_snapshot,
    dte_bucket,
    ewma_realized_vol_pct,
)


def _prices(count: int = 90) -> list[float]:
    values = [100.0]
    for index in range(1, count):
        values.append(values[-1] * (1.006 if index % 2 == 0 else 0.996))
    return values


def test_capture_uses_same_expiry_nearest_half_delta_iv_and_net_friction() -> None:
    expiry = date(2026, 8, 21)
    chain = [
        {"symbol": "SPY-C", "expiry": "2026-08-21", "right": "C", "delta": 0.49, "implied_volatility": 0.24},
        {"symbol": "SPY-P", "expiry": "2026-08-21", "right": "P", "delta": -0.51, "implied_volatility": 0.26},
        {"symbol": "SPY-OTHER", "expiry": "2026-09-18", "right": "C", "delta": 0.50, "implied_volatility": 0.90},
    ]
    selected = [
        {"bid": 2.0, "ask": 2.1, "ratio_qty": 1},
        {"bid": 0.9, "ask": 1.0, "ratio_qty": 1},
    ]

    snapshot = capture_entry_snapshot(
        symbol="SPY",
        expiry=expiry,
        selected_legs=selected,
        chain_legs=chain,
        vix_at_entry=18.0,
        as_of=date(2026, 8, 2),
        closes=_prices(),
        macro_events=[
            {"date": "2026-08-12", "name": "CPI", "impact": "high"},
            {"date": "2026-08-21", "name": "Calendar coverage marker", "impact": "none"},
        ],
        earnings_dates=[date(2026, 8, 18)],
    )

    assert snapshot["atm_iv_annualized_pct"] == pytest.approx(25.0)
    assert snapshot["dte_calendar_days"] == 19
    assert snapshot["dte_bucket"] == "15-30"
    assert snapshot["rv_forecast_annualized_pct"] is not None
    assert snapshot["spread_friction_vol_pct"] > 0
    assert snapshot["spread_friction_method"] == (
        "proxy_sum_leg_bid_ask_width_over_spot_annualized_sqrt252_over_dte"
    )
    assert snapshot["net_vol_premium_ex_event_pct"] < snapshot["gross_vol_premium_pct"]
    assert snapshot["macro_events_within_horizon"][0]["name"] == "CPI"
    assert snapshot["earnings_within_horizon"] is True
    assert snapshot["fomc_within_horizon"] is False
    assert snapshot["event_flags_available"] is True
    assert snapshot["event_risk_premium_pct"] is None
    assert snapshot["net_vol_premium_after_event_pct"] is None
    assert snapshot["gate_changed"] is False


def test_missing_atm_iv_is_explicit_and_does_not_invent_edge() -> None:
    snapshot = capture_entry_snapshot(
        symbol="IWM",
        expiry=date(2026, 8, 21),
        selected_legs=[],
        chain_legs=[],
        as_of=date(2026, 8, 2),
        closes=_prices(),
    )
    assert snapshot["status"] == "atm_iv_unavailable"
    assert snapshot["gross_vol_premium_pct"] is None


def test_macro_event_flag_is_unknown_beyond_calendar_coverage() -> None:
    snapshot = capture_entry_snapshot(
        symbol="SPY",
        expiry=date(2026, 9, 18),
        selected_legs=[{"bid": 1.0, "ask": 1.1}],
        chain_legs=[
            {"symbol": "SPY-C", "expiry": "2026-09-18", "right": "C", "delta": 0.5, "implied_volatility": 0.2}
        ],
        as_of=date(2026, 8, 2),
        closes=_prices(),
        macro_events=[{"date": "2026-08-12", "name": "CPI", "impact": "high"}],
        earnings_dates=[],
    )

    assert snapshot["macro_event_data_complete"] is False
    assert snapshot["fomc_within_horizon"] is None
    assert snapshot["event_flags_available"] is False


def test_report_joins_outcomes_and_refuses_small_sample_claim() -> None:
    records = [
        {
            "type": "candidate",
            "candidate_id": "c1",
            "created_at": "2026-08-02T15:00:00Z",
            "strategy": "put_spread",
            "volatility_edge": {
                "dte_bucket": "8-14",
                "dte_calendar_days": 12,
                "atm_iv_annualized_pct": 24.0,
                "rv_forecast_annualized_pct": 18.0,
                "spread_friction_vol_pct": 0.5,
                "gross_vol_premium_pct": 6.0,
                "net_vol_premium_ex_event_pct": 5.5,
                "event_risk_premium_pct": None,
                "net_vol_premium_after_event_pct": None,
                "event_data_complete": False,
                "vix_at_entry": 17.0,
            },
        },
        {"type": "outcome", "candidate_id": "c1", "reason": "profit_target_50pct_credit", "win": True, "pnl_before_fees": 50.0},
    ]
    report = build_report(records, now=datetime(2026, 8, 2, tzinfo=timezone.utc))

    assert report["instrumented_candidate_count"] == 1
    assert report["resolved_count"] == 1
    assert report["rows"][0]["outcome"] == "profit_target_50pct_credit"
    assert report["cohorts"][0]["status"] == "insufficient_resolved_n"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_ewma_and_dte_bucket_boundaries() -> None:
    assert ewma_realized_vol_pct(_prices()) is not None
    assert ewma_realized_vol_pct([100.0] * 20) is None
    assert dte_bucket(7) == "0-7"
    assert dte_bucket(14) == "8-14"
    assert dte_bucket(45) == "31-45"


def test_macro_coverage_end_is_explicit_not_inferred_from_missing_events() -> None:
    snapshot = capture_entry_snapshot(
        symbol="SPY",
        expiry=date(2026, 9, 18),
        selected_legs=[{"bid": 1.0, "ask": 1.1}],
        chain_legs=[
            {"symbol": "SPY-P", "expiry": "2026-09-18", "right": "P", "delta": -0.5, "implied_volatility": 0.2}
        ],
        as_of=date(2026, 8, 17),
        closes=_prices(),
        macro_events=[],
        macro_coverage_end=date(2026, 9, 30),
        earnings_dates=[],
    )

    assert snapshot["macro_event_data_complete"] is True
    assert snapshot["fomc_within_horizon"] is False


def test_existing_shadow_task_runner_generates_vol_premium_report() -> None:
    root = Path(__file__).resolve().parents[2]
    runner = (root / "scripts" / "run_options_shadow_twin.ps1").read_text(encoding="utf-8")

    assert '"scripts/options_shadow_twin.py"' in runner
    assert '"scripts/options_vol_premium_report.py"' in runner
    assert '$failedSteps += "options_vol_premium_report"' in runner
    assert "if ($failedSteps.Count -gt 0)" in runner


def test_option_chain_preserves_broker_implied_volatility() -> None:
    from strategies import iwm_options_bot as bot

    expiry = date.today().replace(year=date.today().year + 1)
    occ = f"IWM{expiry.strftime('%y%m%d')}P00200000"

    class FakeClient:
        @staticmethod
        def get_option_chain(_request):
            return {
                occ: SimpleNamespace(
                    greeks=SimpleNamespace(delta=-0.49),
                    latest_quote=SimpleNamespace(bid_price=2.0, ask_price=2.1),
                    implied_volatility=0.245,
                )
            }

    bot._JOURNAL_OPTION_CHAINS.clear()
    legs = bot._fetch_chain(FakeClient(), "IWM", 1, 500, "put")

    assert legs[0].implied_volatility == pytest.approx(0.245)
    cached = bot._JOURNAL_OPTION_CHAINS[("IWM", expiry.isoformat())][0]
    assert cached["implied_volatility"] == pytest.approx(0.245)
