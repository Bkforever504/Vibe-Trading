"""Seasonal best-six-months MACD-timed strategy.

Source idea: Hirsch/Stock Trader's Almanac best-six-months timing, intake-002.

Approximation used for research:
- Only consider entries in October/November.
- Enter after MACD line crosses above signal line.
- Hold through the favorable season.
- Exit after May/June when MACD crosses bearish, or force flat after exit month.

The rule is intentionally conservative and may reject due low trade count.
"""
from __future__ import annotations

import pandas as pd


PARAM_GRID = [
    {"entry_month": 10, "exit_month": 5},
    {"entry_month": 10, "exit_month": 6},
    {"entry_month": 11, "exit_month": 5},
    {"entry_month": 11, "exit_month": 6},
]


def _macd(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    fast = close.ewm(span=12, adjust=False).mean()
    slow = close.ewm(span=26, adjust=False).mean()
    line = fast - slow
    signal = line.ewm(span=9, adjust=False).mean()
    return line, signal


def _in_favorable_window(month: int, entry_month: int, exit_month: int) -> bool:
    if entry_month <= exit_month:
        return entry_month <= month <= exit_month
    return month >= entry_month or month <= exit_month


def strategy(ohlcv: pd.DataFrame, entry_month: int = 10, exit_month: int = 5) -> pd.Series:
    close = ohlcv["close"]
    macd_line, signal_line = _macd(close)
    bullish_cross = (macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))
    bearish_cross = (macd_line < signal_line) & (macd_line.shift(1) >= signal_line.shift(1))
    months = pd.DatetimeIndex(ohlcv.index).month

    signals = pd.Series(0, index=ohlcv.index, dtype=int)
    in_trade = False
    for i, month in enumerate(months):
        favorable = _in_favorable_window(int(month), entry_month, exit_month)
        if not in_trade and favorable and month in {entry_month, 11} and bool(bullish_cross.iloc[i]):
            in_trade = True
        elif in_trade and (not favorable or (int(month) in {exit_month, 6} and bool(bearish_cross.iloc[i]))):
            in_trade = False
        signals.iloc[i] = 1 if in_trade else 0
    return signals
