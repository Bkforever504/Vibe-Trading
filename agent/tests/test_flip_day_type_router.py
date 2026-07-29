from __future__ import annotations

from datetime import datetime

import pandas as pd

from strategies.flip_day_type_router import (
    DayTypeSignals,
    classify_day_type,
    classify_intraday_day_type,
)


def test_trend_day_requires_three_supporting_signals() -> None:
    result = classify_day_type(DayTypeSignals(
        overnight_futures_gap_pct=0.7,
        econ_calendar_high_impact=True,
        orb_range_pct=0.5,
        adx_5min=28.0,
    ), classification_time_et="2026-07-17T10:00:00-04:00")

    assert result.day_type == "trend"
    assert result.recommended_strategy == "orb_continuation"
    assert result.confidence == "high"
    assert result.can_submit_orders is False


def test_failed_extension_routes_to_reversal() -> None:
    result = classify_day_type(DayTypeSignals(
        extension_direction="bull",
        extension_fraction=1.8,
        extension_stalled_candles=3,
        reversal_confirmed=True,
        current_above_vwap=True,
    ))

    assert result.day_type == "failed_extension"
    assert result.recommended_strategy == "orb_extension_reversal"
    assert result.reversal_probability >= 0.8


def test_conflicting_or_incomplete_signals_stay_observe() -> None:
    result = classify_day_type(DayTypeSignals(
        overnight_futures_gap_pct=0.4,
        adx_5min=22.0,
        orb_range_pct=0.3,
        prior_session_tick_range=(-300, 300),
    ))

    assert result.day_type == "unknown"
    assert result.recommended_strategy == "observe"
    assert result.authority == "advisory_shadow_router"


def test_intraday_router_has_mature_adx_at_1000_et() -> None:
    index = pd.date_range("2026-07-17 09:30", periods=31, freq="1min")
    closes = [100.0 + 0.10 * position for position in range(len(index))]
    frame = pd.DataFrame({
        "open": closes,
        "high": [value + 0.10 for value in closes],
        "low": [value - 0.10 for value in closes],
        "close": closes,
        "volume": [1000.0] * len(index),
    }, index=index)

    result = classify_intraday_day_type(
        frame,
        prior_close=99.0,
        now_et=datetime(2026, 7, 17, 10, 0),
    )

    assert result.day_type == "trend"
    assert "adx_over_25" in result.signals_supporting
    assert result.can_submit_orders is False


def test_intraday_router_coerces_numeric_object_bars() -> None:
    index = pd.date_range("2026-07-17 09:30", periods=31, freq="1min")
    closes = [100.0 + 0.10 * position for position in range(len(index))]
    frame = pd.DataFrame({
        "open": [str(value) for value in closes],
        "high": [str(value + 0.10) for value in closes],
        "low": [str(value - 0.10) for value in closes],
        "close": [str(value) for value in closes],
        "volume": ["1000"] * len(index),
    }, index=index)

    result = classify_intraday_day_type(
        frame,
        prior_close=99.0,
        now_et=datetime(2026, 7, 17, 10, 0),
    )

    assert result.day_type == "trend"
    assert "adx_over_25" in result.signals_supporting


def test_intraday_router_handles_flat_zero_adx_intervals() -> None:
    index = pd.date_range("2026-07-17 09:30", periods=31, freq="1min")
    frame = pd.DataFrame({
        "open": ["100.0"] * len(index),
        "high": ["100.0"] * len(index),
        "low": ["100.0"] * len(index),
        "close": ["100.0"] * len(index),
        "volume": ["1000"] * len(index),
    }, index=index)

    result = classify_intraday_day_type(
        frame,
        prior_close=100.0,
        now_et=datetime(2026, 7, 17, 10, 0),
    )

    assert result.day_type == "unknown"
    assert result.recommended_strategy == "observe"
