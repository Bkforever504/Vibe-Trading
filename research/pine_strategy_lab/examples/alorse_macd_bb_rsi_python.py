"""
Alorse MACD + BB + RSI strategy translation.

Source: Alorse/pinescript-strategies, strategies/momentum/MACD + BB + RSI.pine
License: repository scan found no explicit license in file; source repo is research input only.

Default source behavior:
- Long entries enabled.
- Short entries disabled.
- No stop loss or take profit.
- Entry: MACD crosses above signal, RSI < 50, close below BB basis.
- Exit: RSI > 70 and close above upper BB.

Research only. No live execution wiring.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


PARAM_GRID = [
    {"fast_length": 12, "slow_length": 26, "signal_length": 9, "bb_length": 20, "bb_mult": 2.0, "rsi_length": 14, "entry_rsi_max": 50, "exit_rsi_min": 70, "use_green_bar_filter": True},
    {"fast_length": 12, "slow_length": 26, "signal_length": 9, "bb_length": 20, "bb_mult": 2.0, "rsi_length": 14, "entry_rsi_max": 55, "exit_rsi_min": 70, "use_green_bar_filter": True},
    {"fast_length": 8, "slow_length": 21, "signal_length": 5, "bb_length": 20, "bb_mult": 2.0, "rsi_length": 14, "entry_rsi_max": 50, "exit_rsi_min": 70, "use_green_bar_filter": True},
    {"fast_length": 8, "slow_length": 21, "signal_length": 5, "bb_length": 20, "bb_mult": 2.0, "rsi_length": 10, "entry_rsi_max": 55, "exit_rsi_min": 70, "use_green_bar_filter": True},
    {"fast_length": 12, "slow_length": 26, "signal_length": 9, "bb_length": 20, "bb_mult": 2.0, "rsi_length": 14, "entry_rsi_max": 50, "exit_rsi_min": 65, "use_green_bar_filter": False},
]


def _ema(values: pd.Series, span: int) -> pd.Series:
    return values.ewm(span=span, adjust=False).mean()


def _rma(values: pd.Series, length: int) -> pd.Series:
    return values.ewm(alpha=1 / length, adjust=False).mean()


def _rsi(close: pd.Series, length: int) -> pd.Series:
    change = close.diff()
    up = _rma(change.clip(lower=0).fillna(0), length)
    down = _rma((-change.clip(upper=0)).fillna(0), length)
    rs = up / down.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    return rsi.mask(down == 0, 100).mask(up == 0, 0).fillna(50)


def _crossover(left: pd.Series, right: pd.Series) -> pd.Series:
    return ((left > right) & (left.shift(1) <= right.shift(1))).fillna(False)


def _crossunder(left: pd.Series, right: pd.Series) -> pd.Series:
    return ((left < right) & (left.shift(1) >= right.shift(1))).fillna(False)


def _green_bar_filter(close: pd.Series, below_lower: pd.Series, idx: int) -> bool:
    prior = below_lower.iloc[: idx + 1]
    hits = np.flatnonzero(prior.to_numpy(dtype=bool))
    if len(hits) == 0:
        return False
    long_bars = idx - int(hits[-1])
    if long_bars <= 1:
        return True

    green_bars = 0
    for bars_back in range(1, long_bars + 1):
        left = idx - bars_back
        right = idx - bars_back - 1
        if right < 0:
            break
        if close.iloc[left] > close.iloc[right]:
            green_bars += 1
    return green_bars >= long_bars / 2 - 1


def strategy(
    ohlcv: pd.DataFrame,
    fast_length: int = 12,
    slow_length: int = 26,
    signal_length: int = 9,
    bb_length: int = 20,
    bb_mult: float = 2.0,
    rsi_length: int = 14,
    entry_rsi_max: int = 50,
    exit_rsi_min: int = 70,
    use_green_bar_filter: bool = True,
    show_short: bool = False,
) -> pd.Series:
    close = ohlcv["close"]
    fast_ma = _ema(close, fast_length)
    slow_ma = _ema(close, slow_length)
    macd = fast_ma - slow_ma
    signal = _ema(macd, signal_length)

    basis = close.rolling(bb_length).mean()
    dev = close.rolling(bb_length).std(ddof=0) * bb_mult
    upper = basis + dev
    lower = basis - dev
    rsi = _rsi(close, rsi_length)

    entry_long = _crossover(macd, signal) & (rsi < entry_rsi_max) & (close < basis)
    exit_long = (rsi > exit_rsi_min) & (close > upper)
    entry_short = _crossunder(macd, signal) & (rsi > 50) & (close > basis)
    exit_short = (rsi < 31) & (close < lower)

    signals = np.zeros(len(close), dtype=int)
    position = 0
    for i in range(len(close)):
        long_ok = bool(entry_long.iloc[i])
        if long_ok and use_green_bar_filter:
            long_ok = _green_bar_filter(close, close < lower, i)

        if position > 0 and bool(exit_long.iloc[i]):
            position = 0
        elif position < 0 and bool(exit_short.iloc[i]):
            position = 0
        elif position == 0 and long_ok:
            position = 1
        elif show_short and position == 0 and bool(entry_short.iloc[i]):
            position = -1

        signals[i] = position

    return pd.Series(signals, index=ohlcv.index, dtype=int)
