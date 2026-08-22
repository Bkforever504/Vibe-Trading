from __future__ import annotations

import numpy as np
import pandas as pd

from research.commercial_indicator_proxy_lab import (
    FAMILIES,
    _kama,
    _supertrend_direction,
    family_direction,
    indicator_table,
)


def _base_table(rows: int = 2) -> pd.DataFrame:
    index = pd.date_range("2026-07-20 10:00", periods=rows, freq="5min")
    columns = {
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
        "volume": 100.0,
        "atr14": 1.0,
        "ema13": 100.0,
        "ema48": 100.0,
        "ema50": 100.0,
        "ema200": 100.0,
        "kama": 100.0,
        "supertrend": 0,
        "relative_volume": 1.0,
        "rsi": 50.0,
        "mfi": 50.0,
        "wt1": 0.0,
        "wt2": 0.0,
        "stoch_k": 50.0,
        "stoch_d": 50.0,
        "macd_histogram": 0.0,
        "adx": 25.0,
        "vwap": 100.0,
        "prior20_low": 99.0,
        "prior20_high": 101.0,
        "body_fraction": 0.5,
        "atr_median50": 1.0,
        "squeeze": False,
        "squeeze_momentum": 0.0,
    }
    return pd.DataFrame(columns, index=index)


def test_relative_volume_denominator_excludes_current_bar() -> None:
    index = pd.date_range("2026-07-20 09:30", periods=25, freq="5min")
    frame = pd.DataFrame(
        {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": np.linspace(100, 102, len(index)),
            "volume": [100.0] * 24 + [1_000.0],
        },
        index=index,
    )
    table = indicator_table(frame)
    assert table["relative_volume"].iloc[-1] == 10.0


def test_indicator_history_does_not_change_when_future_bar_is_appended() -> None:
    index = pd.date_range("2026-07-20 09:30", periods=80, freq="5min")
    frame = pd.DataFrame(
        {
            "open": np.linspace(100, 104, len(index)),
            "high": np.linspace(100.5, 104.5, len(index)),
            "low": np.linspace(99.5, 103.5, len(index)),
            "close": np.linspace(100.2, 104.2, len(index)),
            "volume": 100.0,
        },
        index=index,
    )
    before = indicator_table(frame)
    future = pd.DataFrame(
        [{"open": 200, "high": 250, "low": 150, "close": 225, "volume": 1_000_000}],
        index=[index[-1] + pd.Timedelta(minutes=5)],
    )
    after = indicator_table(pd.concat([frame, future]))
    pd.testing.assert_series_equal(before.iloc[-1], after.loc[index[-1]])


def test_liquidity_reclaim_requires_sweep_close_back_and_displacement() -> None:
    table = _base_table()
    table.iloc[-1, table.columns.get_loc("low")] = 98.5
    table.iloc[-1, table.columns.get_loc("close")] = 100.5
    table.iloc[-1, table.columns.get_loc("open")] = 99.0
    table.iloc[-1, table.columns.get_loc("prior20_low")] = 99.0
    table.iloc[-1, table.columns.get_loc("body_fraction")] = 0.75
    table.iloc[-1, table.columns.get_loc("relative_volume")] = 1.5
    assert family_direction(table, 1, "liquidity_structure_reclaim") == "long"
    table.iloc[-1, table.columns.get_loc("close")] = 98.8
    assert family_direction(table, 1, "liquidity_structure_reclaim") is None


def test_multi_oscillator_trigger_uses_completed_centerline_cross() -> None:
    table = _base_table()
    table.iloc[0, table.columns.get_loc("rsi")] = 49.0
    table.iloc[1, table.columns.get_loc("rsi")] = 51.0
    table.iloc[1, table.columns.get_loc("macd_histogram")] = 0.5
    table.iloc[1, table.columns.get_loc("stoch_k")] = 70.0
    table.iloc[1, table.columns.get_loc("stoch_d")] = 60.0
    table.iloc[1, table.columns.get_loc("close")] = 101.0
    table.iloc[1, table.columns.get_loc("ema50")] = 100.0
    assert family_direction(table, 1, "multi_oscillator_consensus") == "long"


def test_squeeze_release_requires_prior_squeeze_and_directional_release() -> None:
    table = _base_table()
    table.iloc[0, table.columns.get_loc("squeeze")] = True
    table.iloc[1, table.columns.get_loc("squeeze")] = False
    table.iloc[1, table.columns.get_loc("squeeze_momentum")] = 1.0
    table.iloc[1, table.columns.get_loc("close")] = 101.0
    table.iloc[1, table.columns.get_loc("ema50")] = 100.0
    assert family_direction(table, 1, "squeeze_release") == "long"


def test_kama_and_supertrend_preserve_input_index() -> None:
    index = pd.date_range("2026-07-20 09:30", periods=60, freq="5min")
    close = pd.Series(np.linspace(100, 110, len(index)), index=index)
    frame = pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100.0,
        },
        index=index,
    )
    assert _kama(close).index.equals(index)
    assert _supertrend_direction(frame).index.equals(index)


def test_family_list_is_frozen_to_preregistered_set() -> None:
    assert FAMILIES == (
        "adaptive_trend_pullback",
        "oscillator_money_flow",
        "liquidity_structure_reclaim",
        "multi_oscillator_consensus",
        "velocity_ema_ribbon",
        "squeeze_release",
    )
