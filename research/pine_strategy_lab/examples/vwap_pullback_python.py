"""
VWAP Pullback — Python translation of vwap_candidate.pine.
Manual translation. No lookahead. No repainting.

Signal: go long when close pulls back below VWAP then reclaims it
        while above EMA-50. Exit when price drops below EMA-50.
"""
from __future__ import annotations

import pandas as pd


def strategy(ohlcv: pd.DataFrame) -> pd.Series:
    close = ohlcv["close"]
    typical = (ohlcv["high"] + ohlcv["low"] + close) / 3
    cum_vol = ohlcv["volume"].cumsum()
    vwap = (typical * ohlcv["volume"]).cumsum() / cum_vol
    ema50 = close.ewm(span=50, adjust=False).mean()

    prev_below_vwap = close.shift(1) < vwap.shift(1)
    reclaim = (close > vwap) & prev_below_vwap
    above_trend = close > ema50

    signals = pd.Series(0, index=ohlcv.index, dtype=int)
    in_trade = False
    for i in range(len(ohlcv)):
        if not in_trade and reclaim.iloc[i] and above_trend.iloc[i]:
            in_trade = True
        elif in_trade and close.iloc[i] < ema50.iloc[i]:
            in_trade = False
        signals.iloc[i] = 1 if in_trade else 0
    return signals
