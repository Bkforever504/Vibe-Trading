"""TQQQ/GLD or QQQ/GLD two-month rotation.

Source idea: Setup4Alpha, intake-007.

This strategy expects the sweep runner to merge GLD as `defensive_close`.
Signal=1 means hold the primary symbol. Signal=0 means the backtester rotates
flat periods into GLD through defensive_close.
"""
from __future__ import annotations

import pandas as pd


PARAM_GRID = [
    {"lookback_days": 40},
    {"lookback_days": 42},
    {"lookback_days": 63},
]


def strategy(ohlcv: pd.DataFrame, lookback_days: int = 42) -> pd.Series:
    if "defensive_close" not in ohlcv.columns:
        raise ValueError("tqqq_gld_rotation requires --defensive GLD")
    primary_ret = ohlcv["close"].pct_change(lookback_days)
    defensive_ret = ohlcv["defensive_close"].pct_change(lookback_days)
    return (primary_ret > defensive_ret).fillna(False).astype(int)
