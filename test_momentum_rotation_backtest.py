from __future__ import annotations

import pandas as pd
import pytest

from research.momentum_rotation_backtest import (
    _completed_trade_returns,
    _metrics_from_equity,
    _momentum_equity_curve,
    _momentum_signal,
)


def _toy_universe() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=8, freq="B")
    return pd.DataFrame(
        {
            "AAA": [100, 101, 103, 106, 110, 115, 121, 128],
            "BBB": [100, 100, 101, 103, 106, 110, 115, 121],
            "CCC": [100, 99, 98, 97, 96, 95, 94, 93],
        },
        index=idx,
    )


def test_momentum_signal_top_n_holds_equal_weight_tuple():
    universe = _toy_universe()

    signal = _momentum_signal(universe, lookback_days=2, rebalance_days=1, top_n=2)

    assert signal.iloc[0] is None
    assert signal.iloc[1] is None
    assert signal.iloc[2] == ("AAA", "BBB")
    assert "CCC" not in signal.iloc[2]


def test_momentum_signal_goes_cash_when_all_momentum_negative():
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    universe = pd.DataFrame(
        {
            "AAA": [100, 99, 98, 97, 96],
            "BBB": [100, 99.5, 99, 98.5, 98],
        },
        index=idx,
    )

    signal = _momentum_signal(universe, lookback_days=2, rebalance_days=1, top_n=2)

    assert signal.iloc[2:].isna().all()


def test_momentum_equity_curve_equal_weights_selected_assets():
    universe = _toy_universe()
    signal = pd.Series(
        [None, ("AAA", "BBB"), ("AAA", "BBB"), ("AAA", "BBB"), ("AAA", "BBB"), ("AAA", "BBB"), ("AAA", "BBB"), ("AAA", "BBB")],
        index=universe.index,
        dtype=object,
    )

    eq = _momentum_equity_curve(universe, signal, slippage_pct=0.0, commission_pct=0.0)
    asset_returns = universe.pct_change().fillna(0)
    expected_bar_2 = 1 + (asset_returns["AAA"].iloc[2] + asset_returns["BBB"].iloc[2]) / 2

    assert eq.iloc[2] == pytest.approx(expected_bar_2)


def test_completed_trade_returns_count_basket_switches():
    universe = _toy_universe()
    signal = pd.Series(
        [None, ("AAA", "BBB"), ("AAA", "BBB"), ("AAA",), ("AAA",), None, ("BBB",), ("BBB",)],
        index=universe.index,
        dtype=object,
    )
    eq = _momentum_equity_curve(universe, signal, slippage_pct=0.0, commission_pct=0.0)

    trades = _completed_trade_returns(eq, signal)

    assert len(trades) == 3


def test_metrics_time_in_market_counts_baskets_as_in_market():
    universe = _toy_universe()
    signal = pd.Series([None, ("AAA", "BBB"), ("AAA", "BBB"), None, None, ("BBB",), ("BBB",), None], index=universe.index, dtype=object)
    eq = _momentum_equity_curve(universe, signal, slippage_pct=0.0, commission_pct=0.0)

    metrics = _metrics_from_equity(eq, signal)

    assert metrics["time_in_market_pct"] > 0
    assert metrics["trade_count"] == 2
