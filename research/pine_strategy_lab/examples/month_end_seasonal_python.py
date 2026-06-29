"""Month-end seasonal momentum/turn-of-month strategy.

Source idea: Quantpedia-style month-end effect, intake-006.

Rule: hold during the last N trading days of each month and first M trading
days of the next month. Research-only translation.
"""
from __future__ import annotations

import pandas as pd


PARAM_GRID = [
    {"last_days": 4, "first_days": 3},
    {"last_days": 5, "first_days": 3},
    {"last_days": 4, "first_days": 2},
    {"last_days": 5, "first_days": 2},
]


def strategy(ohlcv: pd.DataFrame, last_days: int = 4, first_days: int = 3) -> pd.Series:
    index = pd.DatetimeIndex(ohlcv.index)
    frame = pd.DataFrame(index=index)
    frame["month"] = index.to_period("M")
    frame["day_in_month"] = frame.groupby("month").cumcount() + 1
    frame["days_in_month"] = frame.groupby("month")["day_in_month"].transform("max")
    in_first = frame["day_in_month"] <= first_days
    in_last = frame["day_in_month"] > frame["days_in_month"] - last_days
    return (in_first | in_last).astype(int).reindex(ohlcv.index)
