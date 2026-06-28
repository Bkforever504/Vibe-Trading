"""
RSI mean-reversion strategy family for Pine Strategy Lab sweeps.

Research-only translation target. No live execution.
"""
from __future__ import annotations

import pandas as pd


PARAM_GRID = [
    {"window": 14, "entry": 30, "exit": 50},
    {"window": 14, "entry": 35, "exit": 55},
    {"window": 21, "entry": 35, "exit": 55},
]


def strategy(ohlcv: pd.DataFrame, window: int = 14, entry: int = 30, exit: int = 50) -> pd.Series:
    close = ohlcv["close"]
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))

    signals = pd.Series(0, index=ohlcv.index, dtype=int)
    in_trade = False
    for i in range(len(ohlcv)):
        if not in_trade and rsi.iloc[i] < entry:
            in_trade = True
        elif in_trade and rsi.iloc[i] > exit:
            in_trade = False
        signals.iloc[i] = 1 if in_trade else 0
    return signals
