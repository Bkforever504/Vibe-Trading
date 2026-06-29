"""Williams %R oversold bounce strategy.

Source idea: Larry Williams / QuantifiedStrategies style oversold bounce,
intake-008.

Rule: enter after Williams %R is extremely oversold, optionally requiring the
close to be above a long-term trend SMA. Exit on %R recovery or time stop.
Research-only translation.
"""
from __future__ import annotations

import pandas as pd


PARAM_GRID = [
    {"wr_window": 2, "entry_threshold": -90, "exit_threshold": -50, "max_hold": 5, "trend_window": 200},
    {"wr_window": 2, "entry_threshold": -95, "exit_threshold": -50, "max_hold": 5, "trend_window": 200},
    {"wr_window": 3, "entry_threshold": -90, "exit_threshold": -50, "max_hold": 5, "trend_window": 200},
    {"wr_window": 2, "entry_threshold": -90, "exit_threshold": -40, "max_hold": 7, "trend_window": 200},
    {"wr_window": 2, "entry_threshold": -90, "exit_threshold": -50, "max_hold": 5, "trend_window": 0},
]


def _williams_r(ohlcv: pd.DataFrame, window: int) -> pd.Series:
    highest = ohlcv["high"].rolling(window).max()
    lowest = ohlcv["low"].rolling(window).min()
    denom = (highest - lowest).replace(0, pd.NA)
    return -100 * (highest - ohlcv["close"]) / denom


def strategy(
    ohlcv: pd.DataFrame,
    wr_window: int = 2,
    entry_threshold: float = -90,
    exit_threshold: float = -50,
    max_hold: int = 5,
    trend_window: int = 200,
) -> pd.Series:
    close = ohlcv["close"]
    wr = _williams_r(ohlcv, wr_window)
    trend_ok = pd.Series(True, index=ohlcv.index)
    if trend_window and trend_window > 0:
        trend_ok = close > close.rolling(trend_window).mean()

    signals = pd.Series(0, index=ohlcv.index, dtype=int)
    in_trade = False
    hold = 0
    for i in range(len(ohlcv)):
        if not in_trade and bool(trend_ok.iloc[i]) and wr.iloc[i] <= entry_threshold:
            in_trade = True
            hold = 0
        elif in_trade:
            hold += 1
            if wr.iloc[i] >= exit_threshold or hold >= max_hold:
                in_trade = False
                hold = 0
        signals.iloc[i] = 1 if in_trade else 0
    return signals
