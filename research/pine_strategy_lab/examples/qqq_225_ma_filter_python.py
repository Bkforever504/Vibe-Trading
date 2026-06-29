"""QQQ 225-day moving-average filter.

Source idea: QuantifiedStrategies swing-trading article, intake-001.

Rule: long when the daily close is above a 225-day simple moving average,
flat when it closes below. Research-only translation for the Pine Strategy
Lab. No broker execution.
"""
from __future__ import annotations

import pandas as pd


PARAM_GRID = [
    {"sma_window": 200},
    {"sma_window": 225},
    {"sma_window": 250},
]


def strategy(ohlcv: pd.DataFrame, sma_window: int = 225) -> pd.Series:
    close = ohlcv["close"]
    sma = close.rolling(sma_window).mean()
    return (close > sma).fillna(False).astype(int)
