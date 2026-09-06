"""Single source of truth for guaranteed shadow-observation coverage.

Membership reserves data collection and audit visibility only.  It does not
grant ranking, sizing, alert, execution, or order authority.
"""
from __future__ import annotations


CORE_INDEXES = ("SPY", "QQQ", "IWM")
MAGNIFICENT_SEVEN = ("AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA")
PRIORITY_FOCUS_UNIVERSE = (*CORE_INDEXES, *MAGNIFICENT_SEVEN, "DELL")

assert len(PRIORITY_FOCUS_UNIVERSE) == len(set(PRIORITY_FOCUS_UNIVERSE))

