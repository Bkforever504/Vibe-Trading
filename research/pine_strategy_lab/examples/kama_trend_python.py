"""
KAMA (Kaufman Adaptive Moving Average) trend-following strategy.

Translated from everget/ehlers_mesa_adaptive_moving_averages.pine (GPL-3.0).
Source: research/pine_sources/everget-tradingview-pinescript-indicators/movings/kaufman_adaptive_moving_average.pine

Signal: long when close > KAMA AND KAMA slope is positive.
Exit:   close < KAMA OR KAMA slope turns negative.

Efficiency Ratio adapts smoothing: high ER (trending) → fast EMA alpha,
low ER (choppy) → slow EMA alpha. Avoids whipsaw in ranging markets.
Research-only. No live execution.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


PARAM_GRID = [
    {"length": 10, "fast_length": 2, "slow_length": 20, "slope_lookback": 3},
    {"length": 10, "fast_length": 2, "slow_length": 30, "slope_lookback": 3},
    {"length": 14, "fast_length": 2, "slow_length": 20, "slope_lookback": 3},
    {"length": 14, "fast_length": 2, "slow_length": 30, "slope_lookback": 3},
    {"length": 14, "fast_length": 2, "slow_length": 20, "slope_lookback": 5},
    {"length": 14, "fast_length": 2, "slow_length": 30, "slope_lookback": 5},
    {"length": 20, "fast_length": 2, "slow_length": 20, "slope_lookback": 3},
    {"length": 20, "fast_length": 2, "slow_length": 30, "slope_lookback": 3},
    {"length": 20, "fast_length": 2, "slow_length": 30, "slope_lookback": 5},
    {"length": 14, "fast_length": 3, "slow_length": 20, "slope_lookback": 3},
    {"length": 14, "fast_length": 3, "slow_length": 30, "slope_lookback": 3},
    {"length": 14, "fast_length": 3, "slow_length": 30, "slope_lookback": 5},
]


def _kama(close: pd.Series, length: int, fast_length: int, slow_length: int) -> np.ndarray:
    fast_alpha = 2.0 / (fast_length + 1)
    slow_alpha = 2.0 / (slow_length + 1)
    prices = close.to_numpy(dtype=float)
    n = len(prices)
    kama = prices.copy()

    for i in range(1, n):
        if i < length:
            kama[i] = kama[i - 1]
            continue
        direction = abs(prices[i] - prices[i - length])
        volatility = float(np.sum(np.abs(np.diff(prices[i - length: i + 1]))))
        er = direction / volatility if volatility > 0.0 else 0.0
        alpha = (er * (fast_alpha - slow_alpha) + slow_alpha) ** 2
        kama[i] = alpha * prices[i] + (1 - alpha) * kama[i - 1]

    return kama


def strategy(
    ohlcv: pd.DataFrame,
    length: int = 14,
    fast_length: int = 2,
    slow_length: int = 30,
    slope_lookback: int = 3,
) -> pd.Series:
    close = ohlcv["close"]
    kama = _kama(close, length, fast_length, slow_length)
    prices = close.to_numpy(dtype=float)
    n = len(prices)

    signals = np.zeros(n, dtype=int)
    in_trade = False
    warmup = max(length, slope_lookback)

    for i in range(n):
        if i < warmup:
            signals[i] = 0
            continue
        kama_up = kama[i] > kama[i - slope_lookback]
        long_ok = prices[i] > kama[i] and kama_up
        exit_ok = prices[i] < kama[i] or not kama_up
        if not in_trade and long_ok:
            in_trade = True
        elif in_trade and exit_ok:
            in_trade = False
        signals[i] = 1 if in_trade else 0

    return pd.Series(signals, index=ohlcv.index, dtype=int)
