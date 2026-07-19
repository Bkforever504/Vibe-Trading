from __future__ import annotations

import pandas as pd

from research.liquid_universe_orb_replication import Variant, metrics, moving_block_bootstrap, replay


def _frame() -> pd.DataFrame:
    rows = []
    index = []
    for day_number, day in enumerate(pd.date_range("2026-01-02", periods=45, freq="B")):
        base = 100.0 + day_number * 0.1
        candles = [
            (base, base + 1.0, base - 0.2, base + 0.8, 1000 + day_number),
            (base + 0.8, base + 2.0, base + 0.7, base + 1.8, 900),
            (base + 1.8, base + 3.0, base + 1.7, base + 2.8, 900),
        ]
        for offset, candle in enumerate(candles):
            index.append(pd.Timestamp(day.date(), tz="America/New_York") + pd.Timedelta(hours=9, minutes=30 + 5 * offset))
            rows.append(candle)
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=index)


def test_paper_rule_enters_second_bar_in_first_bar_direction() -> None:
    trades = replay(_frame(), Variant("paper", "first_bar", 10.0), cost_bps_per_side=0)
    assert trades
    assert trades[-1]["direction"] == "long"
    assert trades[-1]["entry"] > trades[-1]["stop"]


def test_metrics_and_block_bootstrap_are_deterministic() -> None:
    values = [{"net_r": value} for value in (1.0, -1.0, 2.0, 1.0)]
    assert metrics(values)["expectancy_r"] == 0.75
    first = moving_block_bootstrap([1.0, -1.0, 2.0, 1.0], block=2, samples=100, seed=7)
    second = moving_block_bootstrap([1.0, -1.0, 2.0, 1.0], block=2, samples=100, seed=7)
    assert first == second
