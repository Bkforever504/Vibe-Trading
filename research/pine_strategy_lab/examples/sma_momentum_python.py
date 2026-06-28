"""
SMA momentum strategy family with ATR trailing stop for Pine Strategy Lab sweeps.

Classic long/cash trend-following rule: hold when close is above the moving
average, exit early when price drops more than atr_mult * ATR(14) below the
rolling highest close since entry. Research-only translation target.
"""
from __future__ import annotations

import pandas as pd


PARAM_GRID = [
    {"sma_window": 150, "atr_mult": 2.0},
    {"sma_window": 150, "atr_mult": 3.0},
    {"sma_window": 180, "atr_mult": 2.0},
    {"sma_window": 180, "atr_mult": 3.0},
    {"sma_window": 200, "atr_mult": 2.0},
    {"sma_window": 200, "atr_mult": 3.0},
    {"sma_window": 220, "atr_mult": 2.0},
    {"sma_window": 220, "atr_mult": 3.0},
]


def _atr(ohlcv: pd.DataFrame, window: int = 14) -> pd.Series:
    high = ohlcv["high"]
    low = ohlcv["low"]
    prev_close = ohlcv["close"].shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window).mean()


def strategy(
    ohlcv: pd.DataFrame,
    sma_window: int = 200,
    atr_mult: float = 2.0,
    atr_window: int = 14,
    vix_threshold: float | None = None,
) -> pd.Series:
    close = ohlcv["close"]
    sma = close.rolling(sma_window).mean()
    above_sma = close > sma
    atr = _atr(ohlcv, atr_window)
    risk_on = pd.Series(True, index=ohlcv.index)
    if vix_threshold is not None:
        if "vix_close" not in ohlcv.columns:
            raise ValueError("vix_threshold requires ohlcv['vix_close']; run sweep with --include-vix")
        risk_on = ohlcv["vix_close"].ffill() <= vix_threshold

    signals = pd.Series(0, index=ohlcv.index, dtype=int)
    in_trade = False
    highest_close = float("-inf")
    trail_stop = float("-inf")

    for i in range(len(ohlcv)):
        c = close.iloc[i]
        atr_val = atr.iloc[i]

        if in_trade and not risk_on.iloc[i]:
            in_trade = False
            highest_close = float("-inf")
            trail_stop = float("-inf")
        elif not in_trade and above_sma.iloc[i] and risk_on.iloc[i] and not pd.isna(atr_val):
            in_trade = True
            highest_close = c
            trail_stop = highest_close - atr_mult * atr_val
        elif in_trade:
            if not pd.isna(atr_val):
                highest_close = max(highest_close, c)
                trail_stop = highest_close - atr_mult * atr_val
            if c < trail_stop or not above_sma.iloc[i]:
                in_trade = False
                highest_close = float("-inf")
                trail_stop = float("-inf")

        signals.iloc[i] = 1 if in_trade else 0

    return signals
