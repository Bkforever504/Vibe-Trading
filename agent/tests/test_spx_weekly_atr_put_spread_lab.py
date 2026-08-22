from __future__ import annotations

from datetime import date, timedelta

import pytest

from research.spx_weekly_atr_put_spread_lab import (
    DailyBar,
    aggregate_daily_to_weekly,
    build_report,
    build_settlement_proxy_trades,
    round_half_up_to_increment,
    summarize,
    wilder_rma,
)


def _daily_weeks(count: int = 18) -> list[DailyBar]:
    monday = date(2025, 1, 6)
    rows: list[DailyBar] = []
    close = 5000.0
    for week in range(count):
        for offset in range(5):
            day = monday + timedelta(days=(week * 7) + offset)
            value = close + offset
            rows.append(DailyBar(day, value - 1, value + 5, value - 5, value))
        close += 10
    return rows


def test_rounding_is_half_up_not_python_bankers_rounding() -> None:
    assert round_half_up_to_increment(4992.5, 5.0) == 4995.0
    assert round_half_up_to_increment(4987.49, 5.0) == 4985.0


def test_wilder_rma_uses_sma_seed_then_recursive_update() -> None:
    values = [1.0] * 14 + [15.0]
    result = wilder_rma(values, 14)

    assert result[12] is None
    assert result[13] == pytest.approx(1.0)
    assert result[14] == pytest.approx(2.0)


def test_holiday_short_week_stays_in_friday_bucket() -> None:
    rows = [
        DailyBar(date(2025, 7, 1), 100, 102, 99, 101),
        DailyBar(date(2025, 7, 2), 101, 103, 100, 102),
        DailyBar(date(2025, 7, 3), 102, 104, 101, 103),
    ]
    weekly = aggregate_daily_to_weekly(rows)

    assert len(weekly) == 1
    assert weekly[0].week_ending == date(2025, 7, 4)
    assert weekly[0].last_session == date(2025, 7, 3)
    assert weekly[0].close == 103


def test_trade_uses_only_previous_completed_week_for_level() -> None:
    weekly = aggregate_daily_to_weekly(_daily_weeks())
    trades = build_settlement_proxy_trades(weekly)
    assert trades
    first = trades[0]
    prior = weekly[13]

    assert first.week_ending == weekly[14].week_ending.isoformat()
    assert first.prior_week_close == prior.close
    assert first.short_strike == round_half_up_to_increment(prior.close - first.prior_week_atr14, 5.0)


def test_settlement_payoff_caps_at_wing_width() -> None:
    weekly = aggregate_daily_to_weekly(_daily_weeks())
    base = build_settlement_proxy_trades(weekly)[0]
    altered = list(weekly)
    target = altered[14]
    altered[14] = target.__class__(
        week_ending=target.week_ending,
        first_session=target.first_session,
        last_session=target.last_session,
        open=target.open,
        high=target.high,
        low=target.low - 1000,
        close=base.long_strike - 10,
    )
    trade = build_settlement_proxy_trades(altered)[0]

    assert trade.settled_below_short is True
    assert trade.settled_through_long is True
    assert trade.intrinsic_loss_points == 50.0


def test_required_credit_uses_intrinsic_loss_and_commission() -> None:
    weekly = aggregate_daily_to_weekly(_daily_weeks())
    trades = build_settlement_proxy_trades(weekly)
    result = summarize(trades, credit_points=2.98, commission_dollars=2.64)
    expected = sum(row.intrinsic_loss_points for row in trades) / len(trades) + 0.0264

    assert result["required_average_gross_credit_points"] == pytest.approx(expected)


def test_report_excludes_the_entire_active_week() -> None:
    rows = _daily_weeks()
    active_friday = max(row.session_date for row in rows)
    report = build_report(rows, symbol="TEST", source="unit_test", as_of_date=active_friday)

    assert report["sample"]["last_trade"] < active_friday.isoformat()


def test_report_has_no_execution_or_promotion_authority() -> None:
    report = build_report(_daily_weeks(), symbol="TEST", source="unit_test")

    assert report["authority"] == "underlying_settlement_proxy_only_no_historical_option_quotes"
    assert report["promotion"] == {
        "status": "research_candidate_unverified",
        "execution_enabled": False,
        "can_submit_orders": False,
        "can_change_gates_or_sizing": False,
        "historical_spxw_quotes_required": True,
        "forward_shadow_weeks_required": 52,
    }
