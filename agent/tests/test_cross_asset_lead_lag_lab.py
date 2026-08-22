from __future__ import annotations

import math

import pandas as pd

from research import cross_asset_lead_lag_lab as lab


def test_metrics_reports_positive_sample() -> None:
    result = lab._metrics([5.0, 4.0, -1.0, 3.0])
    assert result.trades == 4
    assert result.expectancy_dollars == 2.75
    assert result.profit_factor == 12.0
    assert result.one_sided_p is not None


def test_evaluate_delays_signal_one_full_bar_and_uses_executable_sides() -> None:
    index = pd.date_range("2026-07-01 14:00:00+00:00", periods=25, freq="5min")
    close = pd.Series([100.0] * 20 + [110.0] + [110.0] * 4, index=index)
    mes = pd.DataFrame(
        {"entry_ask": [6000.25], "entry_bid": [6000.0], "exit_ask": [6001.25], "exit_bid": [6001.0]},
        index=[index[20] + pd.Timedelta(minutes=5)],
    )
    rows = lab.evaluate(close, mes, relation=1)
    assert len(rows) == 1
    assert rows[0]["known_at"] == index[20].isoformat()
    assert rows[0]["entry_at"] == (index[20] + pd.Timedelta(minutes=5)).isoformat()
    assert math.isclose(rows[0]["base_pnl"], 1.27)


def test_frozen_hypothesis_count_and_alpha() -> None:
    assert lab.LEADERS == {"SPY": 1, "QQQ": 1, "HYG": 1, "TLT": -1, "^VIX": -1}
    assert lab.CORRECTED_ALPHA == 0.05 / 520
    assert lab.MIN_DEVELOPMENT_TRADES == 60

