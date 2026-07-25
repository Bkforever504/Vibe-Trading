from __future__ import annotations

import pandas as pd

from research.spy_first_touch_lab import (
    FirstTouchConfig,
    _event_passes,
    metrics,
    rsi,
    rth_session_dates,
)


def test_rsi_reaches_extremes_without_future_values() -> None:
    values = pd.Series(range(1, 22), dtype=float)
    result = rsi(values, period=14)
    assert result.iloc[12] != result.iloc[12]
    assert result.iloc[-1] == 100.0


def test_event_filter_requires_directional_rsi_and_approach() -> None:
    config = FirstTouchConfig(
        rsi_extreme=75,
        approach_minutes=3,
        min_approach_bps=3,
    )
    short = {
        "family": "prior_day",
        "side": "short",
        "rsi": 80.0,
        "approach_3": 5.0,
    }
    assert _event_passes(short, config)
    assert not _event_passes({**short, "approach_3": -5.0}, config)
    assert not _event_passes({**short, "rsi": 70.0}, config)


def test_level_family_isolated_from_all_variant() -> None:
    event = {
        "family": "whole",
        "side": "long",
        "rsi": 20.0,
        "approach_3": -5.0,
    }
    assert _event_passes(event, FirstTouchConfig(level_family="all"))
    assert not _event_passes(event, FirstTouchConfig(level_family="prior_day"))


def test_metrics_remove_largest_winner_for_outlier_audit() -> None:
    trades = [{"net_r": 1.5}, {"net_r": -1.0}, {"net_r": 10.0}]
    base = metrics(trades)
    trimmed = metrics(trades, remove_top_pct=0.01)
    assert base["expectancy_r"] > 0
    assert trimmed["trades"] == 2
    assert trimmed["expectancy_r"] == 0.25


def test_period_boundaries_use_all_rth_sessions_not_signal_dates() -> None:
    frame = pd.DataFrame(
        {"open": [1, 1], "high": [1, 1], "low": [1, 1], "close": [1, 1], "volume": [1, 1]},
        index=pd.DatetimeIndex(
            [
                pd.Timestamp("2026-07-20 09:30", tz="America/New_York"),
                pd.Timestamp("2026-07-21 09:30", tz="America/New_York"),
            ]
        ),
    )
    assert rth_session_dates(frame) == ["2026-07-20", "2026-07-21"]
