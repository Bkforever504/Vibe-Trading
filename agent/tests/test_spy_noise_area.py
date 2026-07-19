from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from strategies.spy_noise_area import evaluate_noise_area


ET = ZoneInfo("America/New_York")


def _session(day: datetime, *, open_price: float, returns: list[float], volume: float = 1000.0) -> pd.DataFrame:
    index = pd.date_range(day.replace(hour=9, minute=30), periods=len(returns), freq="5min", tz=ET)
    closes = [open_price * (1.0 + value) for value in returns]
    return pd.DataFrame(
        {
            "Open": [open_price] + closes[:-1],
            "High": [value + 0.1 for value in closes],
            "Low": [value - 0.1 for value in closes],
            "Close": closes,
            "Volume": [volume] * len(closes),
        },
        index=index,
    )


def _history(end_day: datetime, sessions: int = 14, move: float = 0.002) -> pd.DataFrame:
    frames = []
    for offset in range(sessions, 0, -1):
        day = end_day - timedelta(days=offset)
        frames.append(_session(day, open_price=100.0, returns=[move] * 7))
    return pd.concat(frames)


def test_noise_area_bull_signal_requires_band_and_vwap_confirmation() -> None:
    now = datetime(2026, 7, 16, 10, 0, tzinfo=ET)
    history = _history(now)
    current = _session(now, open_price=100.0, returns=[0.0, 0.001, 0.002, 0.003, 0.004, 0.005, 0.006])

    result = evaluate_noise_area(current, history, previous_close=100.0, now_et=now)

    assert result["status"] == "entry_ready"
    assert result["direction"] == "bull"
    assert result["upper_band"] == 100.2
    assert result["close"] > result["vwap"]
    assert result["structural_stop"] == max(result["upper_band"], result["vwap"])
    assert result["lookback_sessions_observed"] == 14


def test_noise_area_bear_signal_uses_gap_adjusted_lower_anchor() -> None:
    now = datetime(2026, 7, 16, 10, 30, tzinfo=ET)
    history = _history(now, move=0.003)
    current = _session(now, open_price=99.0, returns=[0.0, -0.001, -0.002, -0.003, -0.004, -0.005, -0.006] * 2)

    result = evaluate_noise_area(current, history, previous_close=100.0, now_et=now)

    assert result["status"] == "entry_ready"
    assert result["direction"] == "bear"
    assert result["lower_band"] == 98.703
    assert result["structural_stop"] == min(result["lower_band"], result["vwap"])


def test_noise_area_stays_neutral_inside_band() -> None:
    now = datetime(2026, 7, 16, 10, 0, tzinfo=ET)
    history = _history(now, move=0.01)
    current = _session(now, open_price=100.0, returns=[0.0, 0.001, 0.002, 0.001, 0.002, 0.001, 0.002])

    result = evaluate_noise_area(current, history, previous_close=100.0, now_et=now)

    assert result["entry_ready"] is False
    assert result["direction"] == "neutral"
    assert result["status"] == "inside_noise_area_or_vwap_unconfirmed"


def test_noise_area_requires_checkpoint_and_full_history() -> None:
    off_checkpoint = datetime(2026, 7, 16, 10, 15, tzinfo=ET)
    current = _session(off_checkpoint, open_price=100.0, returns=[0.01] * 10)
    history = _history(off_checkpoint, sessions=13)

    result = evaluate_noise_area(current, history, previous_close=100.0, now_et=off_checkpoint)
    assert result["status"] == "not_scheduled_checkpoint"

    checkpoint = off_checkpoint.replace(minute=30)
    result = evaluate_noise_area(current, history, previous_close=100.0, now_et=checkpoint)
    assert result["status"] == "insufficient_prior_sessions"
    assert result["lookback_sessions_observed"] == 13


def test_noise_area_never_claims_order_authority() -> None:
    now = datetime(2026, 7, 16, 10, 0, tzinfo=ET)
    result = evaluate_noise_area(
        _session(now, open_price=100.0, returns=[0.01] * 7),
        _history(now),
        previous_close=100.0,
        now_et=now,
    )

    assert result["can_submit_orders"] is False
