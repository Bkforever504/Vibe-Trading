"""
SMA momentum strategy family for Pine Strategy Lab sweeps.

Classic long/cash trend-following rule: hold when close is above the moving
average, otherwise sit in cash. Research-only translation target.
"""
from __future__ import annotations

import pandas as pd


PARAM_GRID = [
    {"sma_window": 150},
    {"sma_window": 150, "vix_threshold": 30},
    {"sma_window": 180},
    {"sma_window": 180, "vix_threshold": 30},
    {"sma_window": 200},
    {"sma_window": 200, "vix_threshold": 30},
    {"sma_window": 220},
    {"sma_window": 220, "vix_threshold": 30},
]


def strategy(ohlcv: pd.DataFrame, sma_window: int = 200, vix_threshold: float | None = None) -> pd.Series:
    close = ohlcv["close"]
    sma = close.rolling(sma_window).mean()
    above_sma = close > sma
    risk_on = pd.Series(True, index=ohlcv.index)
    if vix_threshold is not None:
        if "vix_close" not in ohlcv.columns:
            raise ValueError("vix_threshold requires ohlcv['vix_close']; run sweep with --include-vix")
        risk_on = ohlcv["vix_close"].ffill() <= vix_threshold

    signals = pd.Series(0, index=ohlcv.index, dtype=int)
    in_trade = False
    for i in range(len(ohlcv)):
        if in_trade and not risk_on.iloc[i]:
            in_trade = False
        elif not in_trade and above_sma.iloc[i] and risk_on.iloc[i]:
            in_trade = True
        elif in_trade and not above_sma.iloc[i]:
            in_trade = False
        signals.iloc[i] = 1 if in_trade else 0
    return signals
