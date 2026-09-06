from __future__ import annotations

import pandas as pd

from research.daily_rsi2_200sma_hold_tournament import simulate


def test_rsi2_challenger_uses_closed_entry_and_ten_subsequent_session_timeout() -> None:
    closes = [100.0 + index * 0.1 for index in range(205)]
    closes.extend([120.0, 115.0, 110.0, 109.0, 109.2, 109.3, 109.4, 109.5, 109.6, 109.7])
    closes.extend([109.8] * 10)
    dates = pd.date_range("2025-01-01", periods=len(closes), freq="B", tz="UTC")
    frame = pd.DataFrame({"Close": closes}, index=dates)

    trades = simulate(frame)

    assert trades
    assert trades[0]["sessions_held"] <= 10
    assert trades[0]["entry_at"] < trades[0]["exit_at"]
