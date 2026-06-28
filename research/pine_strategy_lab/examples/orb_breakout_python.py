"""
Opening-range breakout strategy family for Pine Strategy Lab sweeps.

Uses daily bars as a coarse proxy: previous N-bar high breakout with ATR stop.
For intraday ORB, swap the data source to 5m/15m bars before promoting.
"""
from __future__ import annotations

import pandas as pd


PARAM_GRID = [
    {"range_bars": 5, "atr_window": 14, "atr_mult": 1.5},
    {"range_bars": 10, "atr_window": 14, "atr_mult": 2.0},
    {"range_bars": 20, "atr_window": 14, "atr_mult": 2.0},
]


def strategy(
    ohlcv: pd.DataFrame,
    range_bars: int = 10,
    atr_window: int = 14,
    atr_mult: float = 2.0,
) -> pd.Series:
    high = ohlcv["high"]
    low = ohlcv["low"]
    close = ohlcv["close"]
    prev_close = close.shift(1)
    true_range = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = true_range.rolling(atr_window).mean()
    breakout_level = high.shift(1).rolling(range_bars).max()

    signals = pd.Series(0, index=ohlcv.index, dtype=int)
    in_trade = False
    stop = 0.0
    for i in range(len(ohlcv)):
        if not in_trade and close.iloc[i] > breakout_level.iloc[i]:
            in_trade = True
            stop = close.iloc[i] - (atr.iloc[i] * atr_mult)
        elif in_trade:
            stop = max(stop, close.iloc[i] - (atr.iloc[i] * atr_mult))
            if close.iloc[i] < stop:
                in_trade = False
        signals.iloc[i] = 1 if in_trade else 0
    return signals
