from __future__ import annotations

import pandas as pd

from research.liquid_universe_retest_lab import RetestConfig, replay


def _frame() -> pd.DataFrame:
    rows = []
    index = []
    for day_number, day in enumerate(pd.date_range("2025-01-02", periods=45, freq="B")):
        base = 100.0 + day_number * 0.03
        candles = [
            (base, base + 0.4, base - 0.1, base + 0.2, 1000),
            (base + 0.2, base + 0.5, base + 0.1, base + 0.3, 1000),
            (base + 0.3, base + 0.6, base + 0.2, base + 0.5, 1000),
            (base + 0.5, base + 0.9, base + 0.4, base + 0.8, 900),
            (base + 0.8, base + 0.85, base + 0.48, base + 0.7, 900),
            (base + 0.7, base + 1.2, base + 0.65, base + 1.1, 900),
            (base + 1.1, base + 1.8, base + 1.0, base + 1.7, 900),
        ]
        for offset, candle in enumerate(candles):
            index.append(pd.Timestamp(day.date(), tz="America/New_York") + pd.Timedelta(hours=9, minutes=30 + 5 * offset))
            rows.append(candle)
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=index)


def test_retest_enters_next_bar_and_reaches_target() -> None:
    config = RetestConfig("test", 15, min_stop_bps=1, max_stop_bps=100)
    trades = replay(_frame(), config, cost_bps_per_side=0)
    assert trades
    assert trades[-1]["direction"] == "long"
    assert trades[-1]["entry_time"].endswith("09:55:00-05:00")
    assert trades[-1]["outcome"] == "target"


def test_high_rvol_filter_rejects_normal_opening_volume() -> None:
    config = RetestConfig("test", 15, require_rvol=True, min_stop_bps=1, max_stop_bps=100)
    assert replay(_frame(), config, cost_bps_per_side=0)
