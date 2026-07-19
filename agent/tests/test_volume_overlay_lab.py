from __future__ import annotations

import pandas as pd

from research.volume_overlay_lab import FILTERS, _metrics, volume_features


def _frame() -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=40, freq="B")
    close = pd.Series(range(100, 140), index=index, dtype=float)
    return pd.DataFrame({"open": close, "high": close + 0.2, "low": close - 1, "close": close, "volume": range(1000, 1040)}, index=index)


def test_volume_features_are_point_in_time_and_finite_after_warmup() -> None:
    result = volume_features(_frame())
    assert pd.isna(result["rvol20"].iloc[19])
    assert result["rvol20"].iloc[20] > 1
    assert result["obv_slope5"].iloc[-1] > 0
    assert result["cmf20"].iloc[-1] > 0


def test_directional_filters_reverse_for_short_signals() -> None:
    row = volume_features(_frame()).iloc[-1]
    assert FILTERS["obv_direction"](row, 1)
    assert not FILTERS["obv_direction"](row, -1)


def test_metrics_deduct_round_trip_costs() -> None:
    result = _metrics([{"direction": 1, "raw_return": 0.01}], cost_bps_per_side=2)
    assert result["expectancy_bps"] == 96.0
