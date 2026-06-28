"""
The Strat 2-1-2 pattern strategy (Rob Smith / rickyzcarroll).

Bar type classification:
  1  = Inside bar   (H < prev_H AND L > prev_L)
  2  = Directional Up   (H > prev_H AND L >= prev_L)
  -2 = Directional Down (L < prev_L AND H <= prev_H)
  3  = Outside bar  (H > prev_H AND L < prev_L)

2-1-2 Reversal Long:  bar[-2]=2D, bar[-1]=1, bar[0]=2U
2-1-2 Continuation Long: bar[-2]=2U, bar[-1]=1, bar[0]=2U

Entry: next bar open (avoids lookahead).
Stop:  inside bar low.
Target: entry + r_target * (entry - stop).
Exit intrabar: first bar where low<=stop (loss) or high>=target (win).
Max hold: 20 bars then exit at close.

Research-only. No live execution.
"""
from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd


PARAM_GRID = [
    {"pattern_mode": pm, "r_target": rt, "trend_filter": tf, "sma_window": 200}
    for pm, rt, tf in product(
        ["reversal", "continuation", "both"],
        [1.5, 2.0, 2.5, 3.0],
        [True, False],
    )
]


def _classify_bars(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    n = len(high)
    types = np.zeros(n, dtype=int)
    for i in range(1, n):
        broke_high = high[i] > high[i - 1]
        broke_low = low[i] < low[i - 1]
        if broke_high and broke_low:
            types[i] = 3
        elif broke_high:
            types[i] = 2
        elif broke_low:
            types[i] = -2
        else:
            types[i] = 1
    return types


def _sma(close: np.ndarray, window: int) -> np.ndarray:
    out = np.full(len(close), np.nan)
    for i in range(window - 1, len(close)):
        out[i] = close[i - window + 1 : i + 1].mean()
    return out


def _is_212_long(types: np.ndarray, i: int, pattern_mode: str) -> bool:
    if i < 2:
        return False
    t0, t1, t2 = types[i], types[i - 1], types[i - 2]
    if t1 != 1 or t0 != 2:
        return False
    if pattern_mode == "reversal":
        return t2 == -2
    if pattern_mode == "continuation":
        return t2 == 2
    # both
    return t2 in (2, -2)


MAX_HOLD = 20


def strategy(
    ohlcv: pd.DataFrame,
    pattern_mode: str = "reversal",
    r_target: float = 2.0,
    trend_filter: bool = True,
    sma_window: int = 200,
) -> pd.Series:
    high = ohlcv["high"].to_numpy(dtype=float)
    low = ohlcv["low"].to_numpy(dtype=float)
    close = ohlcv["close"].to_numpy(dtype=float)
    open_ = ohlcv["open"].to_numpy(dtype=float)
    n = len(close)

    types = _classify_bars(high, low)
    sma = _sma(close, sma_window) if trend_filter else None

    signals = np.zeros(n, dtype=int)
    i = 2

    while i < n - 1:
        if not _is_212_long(types, i, pattern_mode):
            i += 1
            continue

        if trend_filter and (np.isnan(sma[i]) or close[i] < sma[i]):
            i += 1
            continue

        entry_bar = i + 1
        if entry_bar >= n:
            break

        entry_price = open_[entry_bar]
        stop_price = low[i - 1]
        stop_dist = entry_price - stop_price

        if stop_dist <= 0:
            i += 1
            continue

        target_price = entry_price + r_target * stop_dist

        signals[entry_bar] = 1
        exit_bar = entry_bar + 1
        max_bar = min(entry_bar + MAX_HOLD, n)

        while exit_bar < max_bar:
            if low[exit_bar] <= stop_price or high[exit_bar] >= target_price:
                signals[exit_bar] = 0
                break
            signals[exit_bar] = 1
            exit_bar += 1
        else:
            if exit_bar < n:
                signals[exit_bar] = 0

        i = exit_bar + 1

    return pd.Series(signals, index=ohlcv.index, dtype=int)
