from __future__ import annotations

from datetime import date, timedelta

import pytest

from research.milkman_strategy_suite import (
    CompressionBar,
    OptionQuote,
    bilbo_option_entry_gate,
    bilbo_option_exit,
    build_suite_report,
    daily_bilbo_entry,
    daily_bilbo_exit,
    first_five_compression_boxes,
    select_bilbo_option,
    spx_weekly_atr_candidate,
    swing_golden_gate_entry,
    swing_golden_gate_exit,
    swing_golden_gate_levels,
    zero_dte_pin_convergence_candidate,
)


def _bar(day: int, *, high: float, low: float, close: float, compression: bool, ema21: float = 100.0) -> CompressionBar:
    return CompressionBar(
        session_date=date(2026, 1, 1) + timedelta(days=day),
        open=close,
        high=high,
        low=low,
        close=close,
        compression=compression,
        ema21=ema21,
        ema50=99.0,
    )


def test_spx_candidate_requires_point_in_time_quotes() -> None:
    decision = spx_weekly_atr_candidate(5000.0, 100.0)
    assert decision["status"] == "blocked"
    assert decision["geometry"]["short_strike"] == 4900.0
    assert decision["can_submit_orders"] is False


def test_spx_candidate_uses_natural_credit_and_structural_max_loss() -> None:
    decision = spx_weekly_atr_candidate(5000.0, 100.0, short_bid=3.2, long_ask=0.3)
    assert decision["status"] == "shadow_candidate"
    assert decision["natural_credit_points"] == pytest.approx(2.9)
    assert decision["max_loss_dollars"] == pytest.approx(4710.0)


def test_first_five_box_ignores_later_compression_extremes() -> None:
    bars = [_bar(i, high=101 + i, low=99 - i, close=100, compression=True) for i in range(7)]
    bars.append(_bar(7, high=120, low=80, close=100, compression=False))
    box = first_five_compression_boxes(bars)[0]
    assert box.compression_bars == 5
    assert box.high == 105
    assert box.low == 95
    assert box.lock_index == 4


def test_daily_bilbo_entry_only_arms_after_box_lock() -> None:
    bars = [_bar(i, high=101, low=99, close=100, compression=True, ema21=99) for i in range(5)]
    bars.append(_bar(5, high=103, low=100, close=102, compression=False, ema21=99))
    box = first_five_compression_boxes(bars)[0]
    decision = daily_bilbo_entry(bars, box)
    assert decision["status"] == "shadow_candidate"
    assert decision["entry_date"] == bars[5].session_date.isoformat()


def test_daily_bilbo_cancels_ambiguous_same_bar_high_low_touch() -> None:
    bars = [_bar(i, high=101, low=99, close=100, compression=True, ema21=99) for i in range(5)]
    bars.append(_bar(5, high=102, low=98, close=101, compression=False, ema21=99))
    box = first_five_compression_boxes(bars)[0]
    decision = daily_bilbo_entry(bars, box)
    assert decision["status"] == "blocked"
    assert decision["conservative_same_bar_ordering"] is True


def test_daily_exit_ratchets_stop_and_is_gap_honest() -> None:
    decision = daily_bilbo_exit(
        current_open=95,
        current_low=94,
        current_close=96,
        prior_ema50=98,
        current_stop=97,
        box_high=101,
        sessions_since_entry=4,
        scratch_three_day=True,
    )
    assert decision == {
        "action": "shadow_exit",
        "reason": "initial_or_ema50_stop",
        "fill_price": 95.0,
        "next_stop": 98.0,
    }


def test_daily_exit_flattens_before_earnings() -> None:
    decision = daily_bilbo_exit(
        current_open=105,
        current_low=104,
        current_close=106,
        prior_ema50=100,
        current_stop=99,
        box_high=101,
        sessions_since_entry=5,
        scratch_three_day=True,
        earnings_next_session=True,
    )
    assert decision["reason"] == "flatten_before_earnings"
    assert decision["fill_price"] == 106


def test_bilbo_option_selects_nearest_28dte_then_target_strike() -> None:
    as_of = date(2026, 8, 14)
    quotes = [
        OptionQuote("TEST1", as_of + timedelta(days=27), 107.5, 4.9, 5.1),
        OptionQuote("TEST2", as_of + timedelta(days=30), 107.5, 4.9, 5.1),
        OptionQuote("TEST3", as_of + timedelta(days=27), 110.0, 4.9, 5.1),
    ]
    decision = select_bilbo_option(as_of=as_of, spot=100, daily_atr14=10, quotes=quotes)
    assert decision["contract"] == "TEST1"
    assert decision["modeled_entry_fill"] == pytest.approx(5.05)
    assert decision["can_submit_orders"] is False


def test_bilbo_option_rejects_wide_spread() -> None:
    as_of = date(2026, 8, 14)
    decision = select_bilbo_option(
        as_of=as_of,
        spot=100,
        daily_atr14=10,
        quotes=[OptionQuote("WIDE", as_of + timedelta(days=28), 107.5, 4.0, 6.0)],
    )
    assert decision["reason"] == "option_spread_above_5pct"


def test_bilbo_option_entry_requires_all_three_gates() -> None:
    decision = bilbo_option_entry_gate(
        confirmed_hour_close=102,
        box_high=101,
        signal_volume=900,
        same_clock_median_volume_20=1000,
        prior_daily_close=105,
        prior_daily_ema21=100,
        confirming_hour_et=12,
        weekday=2,
    )
    assert decision["eligible"] is False
    assert decision["gates"]["same_clock_volume_confirmation"] is False


def test_bilbo_option_entry_rejects_outside_published_hour_window() -> None:
    decision = bilbo_option_entry_gate(
        confirmed_hour_close=102,
        box_high=101,
        signal_volume=1000,
        same_clock_median_volume_20=1000,
        prior_daily_close=105,
        prior_daily_ema21=100,
        confirming_hour_et=16,
        weekday=2,
    )
    assert decision["eligible"] is False
    assert decision["gates"]["published_entry_window"] is False


def test_bilbo_option_exit_uses_underlying_trail_not_option_premium() -> None:
    decision = bilbo_option_exit(
        current_underlying_close_5m=103,
        box_low=95,
        entry_underlying=100,
        daily_atr14_at_entry=10,
        peak_underlying=112,
        trading_days_held=3,
    )
    assert decision["reason"] == "giveback_75pct_after_plus_1atr"
    assert decision["trail_level"] == pytest.approx(103.0)


def test_swing_golden_gate_geometry_and_gap_entry() -> None:
    levels = swing_golden_gate_levels(100, 20)
    assert levels.open_trigger == pytest.approx(92.36)
    assert levels.entry == pytest.approx(87.64)
    assert levels.target == pytest.approx(80)
    decision = swing_golden_gate_entry(
        levels=levels,
        gate_opened_above_prior_ema21=True,
        gate_was_opened=True,
        current_open=85,
        current_low=84,
    )
    assert decision["entry_price"] == 85


def test_swing_golden_gate_same_bar_exit_is_stop_first() -> None:
    levels = swing_golden_gate_levels(100, 20)
    decision = swing_golden_gate_exit(
        levels=levels,
        current_open=90,
        current_high=101,
        current_low=79,
        month_end=False,
        current_close=90,
    )
    assert decision["reason"] == "pivot_stop_stop_first_same_bar"


def test_zero_dte_pin_never_infers_unpublished_rules() -> None:
    decision = zero_dte_pin_convergence_candidate({"spot": 6000, "pin": 6000})
    assert decision["status"] == "blocked"
    assert decision["reason"] == "source_strategy_coming_soon_no_reproducible_specification"
    assert decision["supplied_context_fields"] == ["pin", "spot"]


def test_suite_has_no_execution_or_production_authority() -> None:
    report = build_suite_report()
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["can_change_production_gates_or_sizing"] is False
    assert set(report["candidates"]) == {
        "spx_weekly_atr",
        "daily_bilbo",
        "bilbo_options_v2",
        "swing_golden_gate",
        "zero_dte_pin",
    }
