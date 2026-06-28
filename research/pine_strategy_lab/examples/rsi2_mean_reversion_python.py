"""
RSI-2 mean-reversion strategy (Connors RSI-2 system).

Source: handiko/RSI-2-Stock-Trading-Strategy-Pinescript (GitHub, GPL)
Community ref: research/pine_sources/strategy_candidates.md

Signal: 2-period RSI drops below threshold while close is above long-term EMA
        (pullback in an uptrend). Exit when close recovers above a short-term SMA.

Orthogonal to momentum rotation — fires in range-bound pullback regimes
where momentum rotation sits in cash. Research-only. No live execution.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


PARAM_GRID = [
    {"rsi_threshold": 5,  "trend_window": 200, "exit_sma": 5, "exit_mode": "sma"},
    {"rsi_threshold": 10, "trend_window": 200, "exit_sma": 5, "exit_mode": "sma"},
    {"rsi_threshold": 15, "trend_window": 200, "exit_sma": 5, "exit_mode": "sma"},
    {"rsi_threshold": 5,  "trend_window": 150, "exit_sma": 5, "exit_mode": "sma"},
    {"rsi_threshold": 10, "trend_window": 150, "exit_sma": 5, "exit_mode": "sma"},
    {"rsi_threshold": 15, "trend_window": 150, "exit_sma": 5, "exit_mode": "sma"},
    {"rsi_threshold": 5,  "trend_window": 200, "exit_sma": 3, "exit_mode": "sma"},
    {"rsi_threshold": 10, "trend_window": 200, "exit_sma": 3, "exit_mode": "sma"},
    {"rsi_threshold": 15, "trend_window": 200, "exit_sma": 3, "exit_mode": "sma"},
    {"rsi_threshold": 10, "trend_window": 200, "exit_sma": 10, "exit_mode": "sma"},
    {"rsi_threshold": 15, "trend_window": 200, "exit_sma": 10, "exit_mode": "sma"},
    {"rsi_threshold": 10, "trend_window": 150, "exit_sma": 10, "exit_mode": "sma"},
    {"rsi_threshold": 5,  "trend_window": 200, "exit_sma": 5, "exit_mode": "prior_high"},
    {"rsi_threshold": 10, "trend_window": 200, "exit_sma": 5, "exit_mode": "prior_high"},
    {"rsi_threshold": 15, "trend_window": 200, "exit_sma": 5, "exit_mode": "prior_high"},
    {"rsi_threshold": 10, "trend_window": 150, "exit_sma": 5, "exit_mode": "prior_high"},
    {"rsi_threshold": 15, "trend_window": 150, "exit_sma": 5, "exit_mode": "prior_high"},
]


def _rsi(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, float("nan"))
    return (100 - (100 / (1 + rs))).fillna(100.0)


def _ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False).mean()


def strategy(
    ohlcv: pd.DataFrame,
    rsi_threshold: int = 10,
    trend_window: int = 200,
    exit_sma: int = 5,
    exit_mode: str = "sma",
) -> pd.Series:
    close = ohlcv["close"]
    high = ohlcv["high"]
    rsi2 = _rsi(close, window=2)
    trend = _ema(close, span=trend_window)
    profit_target = close.rolling(exit_sma).mean()

    prices = close.to_numpy(dtype=float)
    highs = high.to_numpy(dtype=float)
    rsi_arr = rsi2.to_numpy(dtype=float)
    trend_arr = trend.to_numpy(dtype=float)
    target_arr = profit_target.to_numpy(dtype=float)
    n = len(prices)

    signals = np.zeros(n, dtype=int)
    in_trade = False
    warmup = trend_window + exit_sma

    for i in range(n):
        if i < warmup:
            signals[i] = 0
            continue
        above_trend = prices[i] > trend_arr[i]
        rsi_entry = rsi_arr[i] < rsi_threshold
        if exit_mode == "prior_high":
            above_target = i > 0 and prices[i] > highs[i - 1]
        else:
            above_target = prices[i] > target_arr[i]
        below_trend = prices[i] < trend_arr[i]

        if not in_trade and rsi_entry and above_trend:
            in_trade = True
        elif in_trade and (above_target or below_trend):
            in_trade = False
        signals[i] = 1 if in_trade else 0

    return pd.Series(signals, index=ohlcv.index, dtype=int)
