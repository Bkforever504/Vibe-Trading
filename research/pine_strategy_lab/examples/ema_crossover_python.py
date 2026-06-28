"""
EMA crossover strategy family for Pine Strategy Lab sweeps.

Research-only translation target. No live execution.
"""
from __future__ import annotations

import pandas as pd


PARAM_GRID = [
    {"fast": 9, "slow": 21},
    {"fast": 10, "slow": 30},
    {"fast": 20, "slow": 50},
]


def strategy(ohlcv: pd.DataFrame, fast: int = 9, slow: int = 21) -> pd.Series:
    close = ohlcv["close"]
    fast_ema = close.ewm(span=fast, adjust=False).mean()
    slow_ema = close.ewm(span=slow, adjust=False).mean()
    trend = fast_ema > slow_ema

    signals = pd.Series(0, index=ohlcv.index, dtype=int)
    in_trade = False
    for i in range(len(ohlcv)):
        if not in_trade and trend.iloc[i] and not trend.shift(1).fillna(False).iloc[i]:
            in_trade = True
        elif in_trade and not trend.iloc[i]:
            in_trade = False
        signals.iloc[i] = 1 if in_trade else 0
    return signals
