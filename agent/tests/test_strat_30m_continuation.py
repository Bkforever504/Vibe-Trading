from datetime import datetime, timedelta

import pandas as pd

from strategies.strat_30m_continuation import classify_bar, evaluate_strat_30m


def _daily(previous_type="3"):
    rows = [
        {"open": 95, "high": 100, "low": 90, "close": 98, "volume": 1000},
        {"open": 98, "high": 102, "low": 92, "close": 101, "volume": 1000},
        {"open": 101, "high": 104, "low": 91 if previous_type == "3" else 93, "close": 103, "volume": 1000},
        {"open": 103, "high": 110, "low": 89, "close": 108, "volume": 1000},
    ]
    index = pd.date_range("2026-07-09", periods=4, freq="B")
    return pd.DataFrame(rows, index=index)


def _intraday(breakout=True):
    start = datetime(2026, 7, 15, 9, 30)
    rows = []
    for minute in range(91):
        close = 108.0 + minute * 0.01
        high = close + 0.10
        if breakout and minute >= 35:
            close = 111.0 + (minute - 35) * 0.02
            high = close + 0.10
        rows.append({"open": close - 0.03, "high": high, "low": close - 0.10, "close": close, "volume": 1000})
    return pd.DataFrame(rows, index=pd.DatetimeIndex([start + timedelta(minutes=i) for i in range(91)]))


def test_classifies_outside_bar():
    previous = pd.Series({"high": 100, "low": 90})
    current = pd.Series({"high": 101, "low": 89})
    assert classify_bar(current, previous) == "3"


def test_completed_30m_rebreak_creates_shadow_call_only():
    result = evaluate_strat_30m("GOOGL", _daily(), _intraday())
    assert result["shadow_signal"] is True
    assert result["shadow_direction"] == "call"
    assert result["trigger_at"].endswith("-04:00")
    assert result["authority"] == "shadow_challenger_only"
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False
    assert result["live_execution_allowed"] is False


def test_no_30m_break_means_no_signal():
    result = evaluate_strat_30m("GOOGL", _daily(), _intraday(breakout=False))
    assert result["shadow_signal"] is False
    assert result["shadow_direction"] is None


def test_waits_until_30m_range_is_complete():
    frame = _intraday().between_time("09:30", "09:50")
    result = evaluate_strat_30m("GOOGL", _daily(), frame)
    assert result["status"] == "waiting_for_completed_30m_range"
    assert result["execution_enabled"] is False
