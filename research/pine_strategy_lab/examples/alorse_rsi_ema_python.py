"""
Alorse RSI + EMA strategy translation.

Source: Alorse/pinescript-strategies, strategies/momentum/RSI + EMA.pine
License: MPL-2.0

Rules:
- Compute Wilder RSI on close.
- Trade only when fast MA is above slow MA.
- Long when RSI is below the oversold threshold.
- Short when RSI is above the overbought threshold.
- Keep the current position until the opposite threshold fires.

Research only. No live execution wiring.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


PARAM_GRID = [
    {"rsi_length": 14, "rsi_overbought": 70, "rsi_oversold": 30, "ma_length": 150, "ma2_length": 600},
    {"rsi_length": 14, "rsi_overbought": 65, "rsi_oversold": 35, "ma_length": 150, "ma2_length": 600},
    {"rsi_length": 14, "rsi_overbought": 70, "rsi_oversold": 30, "ma_length": 100, "ma2_length": 300},
    {"rsi_length": 14, "rsi_overbought": 65, "rsi_oversold": 35, "ma_length": 100, "ma2_length": 300},
    {"rsi_length": 10, "rsi_overbought": 70, "rsi_oversold": 30, "ma_length": 150, "ma2_length": 600},
    {"rsi_length": 10, "rsi_overbought": 65, "rsi_oversold": 35, "ma_length": 100, "ma2_length": 300},
]


def _rma(values: pd.Series, length: int) -> pd.Series:
    return values.ewm(alpha=1 / length, adjust=False).mean()


def _rsi(close: pd.Series, length: int) -> pd.Series:
    change = close.diff()
    up = _rma(change.clip(lower=0).fillna(0), length)
    down = _rma((-change.clip(upper=0)).fillna(0), length)
    rs = up / down.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    return rsi.mask(down == 0, 100).mask(up == 0, 0).fillna(50)


def _ma(close: pd.Series, length: int, ma_type: str = "EMA") -> pd.Series:
    if ma_type.upper() == "SMA":
        return close.rolling(length).mean()
    return close.ewm(span=length, adjust=False).mean()


def strategy(
    ohlcv: pd.DataFrame,
    rsi_length: int = 14,
    rsi_overbought: int = 70,
    rsi_oversold: int = 30,
    ma_length: int = 150,
    ma2_length: int = 600,
    ma_type: str = "EMA",
    ma2_type: str = "EMA",
) -> pd.Series:
    close = ohlcv["close"]
    rsi = _rsi(close, rsi_length)
    ma = _ma(close, ma_length, ma_type)
    ma2 = _ma(close, ma2_length, ma2_type)

    trend_on = (ma > ma2).fillna(False).to_numpy(dtype=bool)
    rsi_arr = rsi.to_numpy(dtype=float)
    signals = np.zeros(len(close), dtype=int)

    position = 0
    for i in range(len(close)):
        if trend_on[i] and rsi_arr[i] < rsi_oversold:
            position = 1
        elif trend_on[i] and rsi_arr[i] > rsi_overbought:
            position = -1
        signals[i] = position

    return pd.Series(signals, index=ohlcv.index, dtype=int)
