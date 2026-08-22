"""Turn-of-month gate — returns True on last 2 + first 2 trading days of month.

Import and call is_turn_of_month() anywhere entry filtering is needed.
Documented positive SPY bias during this 4-day window (institutional rebalancing inflows).
"""
from __future__ import annotations
from datetime import date, timedelta


def _trading_days_in_month(year: int, month: int) -> list[date]:
    """Return all Mon-Fri dates in the given month (no holiday adjustment)."""
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1
    d = date(year, month, 1)
    end = date(next_year, next_month, 1)
    days = []
    while d < end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def is_turn_of_month(today: date | None = None, window: int = 2) -> bool:
    """True if today is within `window` trading days of month start or end."""
    today = today or date.today()
    month_days = _trading_days_in_month(today.year, today.month)
    if not month_days:
        return False
    first_n = set(month_days[:window])
    last_n = set(month_days[-window:])
    return today in first_n or today in last_n


def tom_context(today: date | None = None, window: int = 2) -> dict:
    today = today or date.today()
    in_window = is_turn_of_month(today, window)
    month_days = _trading_days_in_month(today.year, today.month)
    position = None
    if month_days:
        if today in set(month_days[:window]):
            position = "month_start"
        elif today in set(month_days[-window:]):
            position = "month_end"
    return {
        "in_tom_window": in_window,
        "position": position,
        "window_days": window,
        "note": "SPY +bias last2+first2 trading days; prefer call entries" if in_window else "outside_tom_window",
    }


if __name__ == "__main__":
    import json
    print(json.dumps(tom_context(), indent=2))
