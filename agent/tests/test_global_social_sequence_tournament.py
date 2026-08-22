from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from research.global_social_sequence_tournament import (
    BONFERRONI_ALPHA,
    EFFECTIVE_ATTEMPTS,
    TRIAL_COUNT,
    _daily_trades,
    _opening_range,
    build_registry,
    simulate_intraday,
)


def _bars() -> pd.DataFrame:
    start = datetime(2026, 8, 18, 9, 30)
    rows = []
    for idx in range(20):
        rows.append({
            "dt": start + timedelta(minutes=5 * idx),
            "time": (start + timedelta(minutes=5 * idx)).strftime("%H:%M"),
            "open": 100.0,
            "high": 100.25,
            "low": 99.75,
            "close": 100.0,
            "volume": 100.0,
        })
    return pd.DataFrame(rows)


def test_registry_counts_all_markets_families_and_prior_attempts() -> None:
    registry = build_registry()
    assert TRIAL_COUNT == 106
    assert EFFECTIVE_ATTEMPTS == 909
    assert BONFERRONI_ALPHA == 0.05 / 909
    assert len(registry["trials"]) == 106
    assert len({row["trial_id"] for row in registry["trials"]}) == 106
    assert registry["execution_enabled"] is False
    assert registry["can_submit_orders"] is False


def test_opening_range_requires_break_then_completed_retest() -> None:
    bars = _bars()
    bars.loc[3, ["open", "high", "low", "close"]] = [100.0, 101.0, 100.0, 100.75]
    bars.loc[4, ["open", "high", "low", "close"]] = [100.75, 101.0, 100.20, 100.50]
    signal = _opening_range(bars, None)
    assert signal is not None
    signal_idx, side, stop = signal
    assert signal_idx == 4
    assert side == 1
    assert stop == 100.0


def test_intraday_execution_is_next_open_and_ambiguous_bar_is_stop_first() -> None:
    bars = _bars()
    bars.loc[5, ["open", "high", "low", "close"]] = [100.50, 103.0, 98.0, 100.5]
    gross = simulate_intraday(bars, (4, 1, 99.5), 2.0, "SPY")
    assert gross is not None
    assert round(gross, 2) == -99.5


def test_daily_signal_executes_on_next_open_not_signal_close() -> None:
    index = pd.date_range("2025-01-01", periods=240, freq="B")
    close = pd.Series(range(100, 340), index=index, dtype=float)
    frame = pd.DataFrame({
        "open": close + 1.0,
        "high": close + 2.0,
        "low": close - 2.0,
        "close": close,
        "volume": 1_000_000,
    })
    trades = _daily_trades(frame, "sma200_long_cash")
    assert len(trades) == 1
    entry_day, _ = trades[0]
    first_signal = (frame["close"] > frame["close"].rolling(200).mean()).idxmax()
    assert entry_day == frame.index[frame.index.get_loc(first_signal) + 1].date().isoformat()
