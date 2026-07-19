"""Point-in-time SPY Noise Area and VWAP signal evaluation.

The model follows the public methodology in SSRN 4824172: compare the current
session move with the average absolute move to the same clock time over prior
sessions, anchor the bands to today's open and the prior close, and require
price to confirm on the same side of VWAP. This module is pure and submits no
orders.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = {"Open", "High", "Low", "Close", "Volume"}


def _et_index(frame: pd.DataFrame) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(pd.to_datetime(frame.index))
    if index.tz is None:
        return index.tz_localize("America/New_York")
    return index.tz_convert("America/New_York")


def _regular_session(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty or not REQUIRED_COLUMNS.issubset(frame.columns):
        return pd.DataFrame(columns=sorted(REQUIRED_COLUMNS))
    result = frame.copy()
    result.index = _et_index(result)
    return result.between_time("09:30", "16:00", inclusive="left")


def _clock_minutes(value: datetime | pd.Timestamp) -> int:
    return int(value.hour) * 60 + int(value.minute)


def _completed_current_bars(frame: pd.DataFrame, now_et: datetime) -> pd.DataFrame:
    regular = _regular_session(frame)
    if regular.empty:
        return regular
    current = pd.Timestamp(now_et)
    if current.tzinfo is None:
        current = current.tz_localize("America/New_York")
    else:
        current = current.tz_convert("America/New_York")
    same_day = regular[regular.index.date == current.date()]
    return same_day.loc[same_day.index + pd.Timedelta(minutes=1) <= current]


def _historical_moves_to_clock(
    frame: pd.DataFrame,
    now_et: datetime,
    *,
    lookback_sessions: int,
) -> list[dict[str, Any]]:
    regular = _regular_session(frame)
    if regular.empty:
        return []
    current_date = pd.Timestamp(now_et).date()
    cutoff_minutes = _clock_minutes(now_et)
    rows: list[dict[str, Any]] = []
    for session_date, session in regular.groupby(regular.index.date):
        if session_date >= current_date:
            continue
        eligible = session[
            [_clock_minutes(timestamp) <= cutoff_minutes for timestamp in session.index]
        ]
        if eligible.empty:
            continue
        session_open = float(eligible["Open"].iloc[0])
        same_time_close = float(eligible["Close"].iloc[-1])
        if session_open <= 0 or same_time_close <= 0:
            continue
        rows.append({
            "date": str(session_date),
            "absolute_move_from_open": abs(same_time_close / session_open - 1.0),
            "bars": int(len(eligible)),
        })
    return rows[-max(1, int(lookback_sessions)):]


def evaluate_noise_area(
    current_bars: pd.DataFrame,
    historical_bars: pd.DataFrame,
    *,
    previous_close: float,
    now_et: datetime,
    lookback_sessions: int = 14,
    checkpoint_minutes: tuple[int, ...] = (0, 30),
    entry_start: time = time(10, 0),
    entry_end: time = time(13, 0),
) -> dict[str, Any]:
    """Return a point-in-time signal and full calculation provenance."""
    base = {
        "strategy": "noise_area_vwap",
        "status": "unavailable",
        "entry_ready": False,
        "direction": "neutral",
        "lookback_sessions_required": int(lookback_sessions),
        "checkpoint_minutes": list(checkpoint_minutes),
        "evaluated_at": pd.Timestamp(now_et).isoformat(),
        "can_submit_orders": False,
    }
    if now_et.time() < entry_start or now_et.time() > entry_end:
        return {**base, "status": "outside_entry_window"}
    if now_et.minute not in checkpoint_minutes:
        return {**base, "status": "not_scheduled_checkpoint"}

    current = _completed_current_bars(current_bars, now_et)
    if current.empty:
        return {**base, "status": "current_session_unavailable"}
    history = _historical_moves_to_clock(
        historical_bars,
        now_et,
        lookback_sessions=lookback_sessions,
    )
    if len(history) < lookback_sessions:
        return {
            **base,
            "status": "insufficient_prior_sessions",
            "lookback_sessions_observed": len(history),
        }
    if previous_close <= 0:
        return {**base, "status": "previous_close_unavailable"}

    session_open = float(current["Open"].iloc[0])
    close = float(current["Close"].iloc[-1])
    if session_open <= 0 or close <= 0:
        return {**base, "status": "invalid_current_prices"}
    typical = (current["High"] + current["Low"] + current["Close"]) / 3.0
    cumulative_volume = current["Volume"].fillna(0.0).cumsum()
    if float(cumulative_volume.iloc[-1]) <= 0:
        return {**base, "status": "current_volume_unavailable"}
    vwap = float((typical * current["Volume"].fillna(0.0)).cumsum().iloc[-1] / cumulative_volume.iloc[-1])

    noise_fraction = sum(row["absolute_move_from_open"] for row in history) / len(history)
    upper_anchor = max(session_open, float(previous_close))
    lower_anchor = min(session_open, float(previous_close))
    upper_band = upper_anchor * (1.0 + noise_fraction)
    lower_band = lower_anchor * (1.0 - noise_fraction)
    if close > upper_band and close > vwap:
        direction = "bull"
        structural_stop = max(upper_band, vwap)
    elif close < lower_band and close < vwap:
        direction = "bear"
        structural_stop = min(lower_band, vwap)
    else:
        direction = "neutral"
        structural_stop = None

    return {
        **base,
        "status": "entry_ready" if direction != "neutral" else "inside_noise_area_or_vwap_unconfirmed",
        "entry_ready": direction != "neutral",
        "direction": direction,
        "signal_score": 9.0 if direction != "neutral" else 0.0,
        "lookback_sessions_observed": len(history),
        "history_start": history[0]["date"],
        "history_end": history[-1]["date"],
        "session_open": round(session_open, 4),
        "previous_close": round(float(previous_close), 4),
        "close": round(close, 4),
        "vwap": round(vwap, 4),
        "noise_fraction": round(noise_fraction, 6),
        "upper_band": round(upper_band, 4),
        "lower_band": round(lower_band, 4),
        "structural_stop": round(structural_stop, 4) if structural_stop is not None else None,
        "current_bars_observed": int(len(current)),
        "formula_version": "ssrn_4824172_noise_area_v1",
    }
