from __future__ import annotations

import pandas as pd

from research.green_day_htf_ltf_lab import (
    asof_states,
    bracket_outcome,
    build_htf_table,
    direction_matches,
    fresh_pullback,
    ltf_signal,
    variant_allows,
)


def _trend_frame(direction: str, periods: int = 60) -> pd.DataFrame:
    index = pd.date_range("2026-01-02 09:30", periods=periods, freq="1min", tz="America/New_York")
    step = 0.03 if direction == "bull" else -0.03
    close = [100 + step * i for i in range(periods)]
    frame = pd.DataFrame({
        "open": close,
        "high": [value + 0.04 for value in close],
        "low": [value - 0.04 for value in close],
        "close": close,
        "volume": 1000.0,
    }, index=index)
    return frame


def test_htf_asof_excludes_current_session() -> None:
    index = pd.bdate_range("2025-01-01", periods=80)
    frame = pd.DataFrame({"close": range(100, 180)}, index=index)
    table = build_htf_table(frame)
    state = asof_states(table, index[-1].date())
    assert state["daily"] == table["daily"].iloc[-2]


def test_alignment_variants_fail_closed_on_mixed() -> None:
    states = {"daily": "bullish", "weekly": "mixed", "monthly": "bullish"}
    assert variant_allows("daily_aligned", states, "bull")
    assert not variant_allows("daily_weekly_aligned", states, "bull")
    assert variant_allows("daily_weekly_nonopposed", states, "bull")
    assert not variant_allows("all_three_aligned", states, "bull")


def test_direction_match() -> None:
    assert direction_matches("bullish", "bull")
    assert direction_matches("bearish", "bear")
    assert not direction_matches("mixed", "bull")


def test_fresh_pullback_requires_touch_and_confirmation() -> None:
    frame = _trend_frame("bull")
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3
    frame["vwap"] = (typical * frame["volume"]).cumsum() / frame["volume"].cumsum()
    frame["ema50"] = frame["close"].ewm(span=50, adjust=False).mean()
    frame.iloc[-3, frame.columns.get_loc("low")] = min(frame["vwap"].iloc[-3], frame["ema50"].iloc[-3])
    frame.iloc[-1, frame.columns.get_loc("open")] = frame["close"].iloc[-1] - 0.01
    assert fresh_pullback(frame, "bull")


def test_ltf_signal_requires_full_nine_points() -> None:
    frame = _trend_frame("bull")
    # Force a recent trend-support touch while retaining the final confirmation.
    preliminary = frame.copy()
    typical = (preliminary["high"] + preliminary["low"] + preliminary["close"]) / 3
    preliminary["vwap"] = (typical * preliminary["volume"]).cumsum() / preliminary["volume"].cumsum()
    preliminary["ema50"] = preliminary["close"].ewm(span=50, adjust=False).mean()
    frame.iloc[-3, frame.columns.get_loc("low")] = min(preliminary["vwap"].iloc[-3], preliminary["ema50"].iloc[-3])
    signal = ltf_signal(frame)
    assert signal is not None
    assert signal["direction"] == "bull"
    assert signal["score"] == 9


def test_bracket_is_conservative_when_both_hit() -> None:
    frame = pd.DataFrame([{"high": 101.0, "low": 99.0, "close": 100.5}])
    assert bracket_outcome(frame, 100.0, "bull") < 0
