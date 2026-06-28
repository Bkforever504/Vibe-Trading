"""
SMA momentum with defensive rotation for Pine Strategy Lab sweeps.

When close is above SMA: long the equity ETF.
When close is below SMA: rotate to the defensive asset (TLT or GLD).

The rotation asset is injected by the sweep runner via --defensive SYMBOL,
which merges 'defensive_close' into the OHLCV before the backtest runs.
Strategy logic is identical to plain SMA momentum — rotation is handled
transparently by the backtester's _equity_curve. Research-only.
"""
from __future__ import annotations

import pandas as pd


PARAM_GRID = [
    {"sma_window": 150},
    {"sma_window": 180},
    {"sma_window": 200},
    {"sma_window": 220},
]


def strategy(ohlcv: pd.DataFrame, sma_window: int = 200) -> pd.Series:
    close = ohlcv["close"]
    sma = close.rolling(sma_window).mean()

    signals = pd.Series(0, index=ohlcv.index, dtype=int)
    in_trade = False
    for i in range(len(ohlcv)):
        if not in_trade and close.iloc[i] > sma.iloc[i]:
            in_trade = True
        elif in_trade and close.iloc[i] <= sma.iloc[i]:
            in_trade = False
        signals.iloc[i] = 1 if in_trade else 0
    return signals
