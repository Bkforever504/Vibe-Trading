"""Pure The Strat + 30-minute continuation shadow evaluator."""
from __future__ import annotations

import math
from typing import Any

import pandas as pd


def classify_bar(current: pd.Series, previous: pd.Series) -> str:
    broke_high = float(current["high"]) > float(previous["high"])
    broke_low = float(current["low"]) < float(previous["low"])
    if broke_high and broke_low:
        return "3"
    if broke_high:
        return "2U"
    if broke_low:
        return "2D"
    return "1"


def _ensure_et(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    index = pd.to_datetime(result.index)
    if index.tz is None:
        index = index.tz_localize("America/New_York")
    else:
        index = index.tz_convert("America/New_York")
    result.index = index
    result.columns = [str(column).lower() for column in result.columns]
    return result


def evaluate_intraday_212_reversal(intraday: pd.DataFrame) -> dict[str, Any]:
    """Evaluate a 30m 2-1 setup and the first completed lower-timeframe break."""
    rth = _ensure_et(intraday).between_time("09:30", "15:59")
    if rth.empty:
        return {"status": "waiting_for_completed_30m_bars", "shadow_signal": False}
    grouped = rth.resample(
        "30min", origin="start_day", offset="9h30min", label="left", closed="left"
    )
    bars = grouped.agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    counts = grouped["close"].count()
    spacing = rth.index.to_series().diff().dropna().dt.total_seconds().div(60)
    base_minutes = float(spacing.median()) if not spacing.empty else 30.0
    expected_rows = max(1, math.ceil(30.0 / max(base_minutes, 1.0)))
    bars = bars[counts >= expected_rows].dropna()
    if len(bars) < 3:
        return {"status": "waiting_for_completed_30m_bars", "shadow_signal": False, "completed_30m_bars": len(bars)}

    direction = None
    entry = stop = target = None
    trigger = None
    sequence: list[str] = []
    # Search newest-to-oldest for a completed directional bar + completed
    # inside bar. The trigger is the first subsequently completed source bar
    # that crosses the inside range, so the counterfactual entry is causal.
    for position in range(len(bars) - 1, 1, -1):
        reference, directional, inside = bars.iloc[position - 2], bars.iloc[position - 1], bars.iloc[position]
        directional_type = classify_bar(directional, reference)
        if classify_bar(inside, directional) != "1" or directional_type not in {"2U", "2D"}:
            continue
        eligible_after = inside.name + pd.Timedelta(minutes=30)
        future = rth[rth.index >= eligible_after]
        if directional_type == "2U":
            crossed = future[future["low"] < float(inside["low"])]
            if not crossed.empty:
                direction, trigger = "put", crossed.iloc[0]
                entry, stop, target = float(trigger["close"]), float(inside["high"]), float(directional["low"])
                sequence = ["2U", "1", "2D"]
        else:
            crossed = future[future["high"] > float(inside["high"])]
            if not crossed.empty:
                direction, trigger = "call", crossed.iloc[0]
                entry, stop, target = float(trigger["close"]), float(inside["low"]), float(directional["high"])
                sequence = ["2D", "1", "2U"]
        if direction:
            break
    trigger_time = trigger.name + pd.Timedelta(minutes=base_minutes) if trigger is not None else None
    extended = bool(direction == "put" and entry is not None and target is not None and entry <= target) or bool(
        direction == "call" and entry is not None and target is not None and entry >= target
    )
    risk = abs(entry - stop) if entry is not None and stop is not None else None
    reward = abs(target - entry) if entry is not None and target is not None else None
    return {
        "schema_version": 1,
        "status": "extended_no_chase" if extended else "confirmed" if direction else "no_pattern",
        "pattern": "30m_2_1_2_reversal" if direction else None,
        "sequence": sequence,
        "shadow_signal": direction is not None and not extended,
        "shadow_direction": direction,
        "trigger_bar_at": trigger.name.isoformat() if trigger is not None else None,
        "trigger_at": trigger_time.isoformat() if trigger_time is not None else None,
        "decision_available_at": trigger_time.isoformat() if trigger_time is not None else None,
        "counterfactual": {
            "entry_underlying": round(entry, 4) if entry is not None else None,
            "stop_underlying": round(stop, 4) if stop is not None else None,
            "first_level_target": round(target, 4) if target is not None else None,
            "risk_points": round(risk, 4) if risk is not None else None,
            "reward_points": round(reward, 4) if reward is not None else None,
            "reward_risk": round(reward / risk, 3) if risk and reward is not None else None,
            "horizon_minutes": 60,
        },
        "bar_basis": "completed_directional_and_inside_30m_bars_then_first_completed_source_bar_cross",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _period_open(daily: pd.DataFrame, current_day: pd.Timestamp, period: str, day_open: float) -> float:
    dates = pd.to_datetime(daily.index)
    if dates.tz is not None:
        dates = dates.tz_convert("America/New_York").tz_localize(None)
    if period == "week":
        current_period = current_day.tz_localize(None).to_period("W-FRI")
        mask = dates.to_period("W-FRI") == current_period
    else:
        current_period = current_day.tz_localize(None).to_period("M")
        mask = dates.to_period("M") == current_period
    rows = daily.loc[mask]
    return float(rows.iloc[0]["open"]) if not rows.empty else day_open


def _prior_week_levels(daily: pd.DataFrame, current_day: pd.Timestamp) -> tuple[float | None, float | None]:
    dates = pd.to_datetime(daily.index)
    if dates.tz is not None:
        dates = dates.tz_convert("America/New_York").tz_localize(None)
    current_period = current_day.tz_localize(None).to_period("W-FRI")
    periods = dates.to_period("W-FRI")
    previous_periods = sorted({period for period in periods if period < current_period})
    if not previous_periods:
        return None, None
    rows = daily.loc[periods == previous_periods[-1]]
    return float(rows["high"].max()), float(rows["low"].min())


def evaluate_strat_30m(symbol: str, daily: pd.DataFrame, intraday: pd.DataFrame) -> dict[str, Any]:
    if len(daily) < 4:
        raise ValueError("at least four completed daily bars are required")
    rth = _ensure_et(intraday).between_time("09:30", "15:59")
    if rth.empty:
        raise ValueError("regular-session intraday bars are unavailable")
    opening = rth.between_time("09:30", "09:59")
    post = rth.between_time("10:00", "15:59")
    if opening.empty or post.empty:
        return {
            "symbol": symbol.upper(),
            "status": "waiting_for_completed_30m_range",
            "execution_enabled": False,
            "can_submit_orders": False,
        }

    daily = daily.copy()
    daily.columns = [str(column).lower() for column in daily.columns]
    previous = daily.iloc[-1]
    previous_two = daily.iloc[-2]
    previous_three = daily.iloc[-3]
    previous_type = classify_bar(previous, previous_two)
    previous_two_type = classify_bar(previous_two, previous_three)
    double_outside = previous_type == "3" and previous_two_type == "3"

    current_day = rth.index[-1]
    day_open = float(opening.iloc[0]["open"])
    week_open = _period_open(daily, current_day, "week", day_open)
    month_open = _period_open(daily, current_day, "month", day_open)
    prior_week_high, prior_week_low = _prior_week_levels(daily, current_day)
    prior_day_high = float(previous["high"])
    prior_day_low = float(previous["low"])
    opening_high = float(opening["high"].max())
    opening_low = float(opening["low"].min())

    long_rows = post[(post["high"] > opening_high) & (post["high"] > prior_day_high)]
    short_rows = post[(post["low"] < opening_low) & (post["low"] < prior_day_low)]
    long_trigger = long_rows.iloc[0] if not long_rows.empty else None
    short_trigger = short_rows.iloc[0] if not short_rows.empty else None
    long_at = long_rows.index[0] if not long_rows.empty else None
    short_at = short_rows.index[0] if not short_rows.empty else None

    long_close = float(long_trigger["close"]) if long_trigger is not None else None
    short_close = float(short_trigger["close"]) if short_trigger is not None else None
    ftfc_green = bool(long_close is not None and long_close > day_open and long_close > week_open and long_close > month_open)
    ftfc_red = bool(short_close is not None and short_close < day_open and short_close < week_open and short_close < month_open)

    long_pattern = {
        "1": "inside_2u",
        "3": "outside_continuation",
        "2D": "failed_2d_reversal",
        "2U": "directional_continuation",
    }[previous_type]
    short_pattern = {
        "1": "inside_2d",
        "3": "outside_continuation",
        "2U": "failed_2u_reversal",
        "2D": "directional_continuation",
    }[previous_type]

    direction = None
    trigger_at = None
    entry = None
    stop = None
    target = None
    pattern = None
    if ftfc_green and long_at is not None:
        direction, trigger_at, entry, stop, pattern = "call", long_at, long_close, opening_low, long_pattern
        target = prior_week_high if prior_week_high is not None and prior_week_high > entry else None
    elif ftfc_red and short_at is not None:
        direction, trigger_at, entry, stop, pattern = "put", short_at, short_close, opening_high, short_pattern
        target = prior_week_low if prior_week_low is not None and prior_week_low < entry else None

    return {
        "schema_version": 1,
        "symbol": symbol.upper(),
        "status": "ok",
        "date": current_day.date().isoformat(),
        "previous_daily_type": previous_type,
        "previous_two_daily_type": previous_two_type,
        "double_outside_daily": double_outside,
        "pattern": pattern,
        "ftfc": {
            "green": ftfc_green,
            "red": ftfc_red,
            "day_open": round(day_open, 4),
            "week_open": round(week_open, 4),
            "month_open": round(month_open, 4),
        },
        "levels": {
            "prior_day_high": round(prior_day_high, 4),
            "prior_day_low": round(prior_day_low, 4),
            "prior_week_high": round(prior_week_high, 4) if prior_week_high is not None else None,
            "prior_week_low": round(prior_week_low, 4) if prior_week_low is not None else None,
            "opening_30m_high": round(opening_high, 4),
            "opening_30m_low": round(opening_low, 4),
        },
        "shadow_signal": direction is not None,
        "shadow_direction": direction,
        "trigger_at": trigger_at.isoformat() if trigger_at is not None else None,
        "counterfactual": {
            "entry_underlying": round(entry, 4) if entry is not None else None,
            "stop_underlying": round(stop, 4) if stop is not None else None,
            "first_level_target": round(target, 4) if target is not None else None,
            "horizon_minutes": 60,
        },
        "authority": "shadow_challenger_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "live_execution_allowed": False,
        "notes": [
            "Trigger uses a completed 30-minute opening range; it does not chase the opening candle.",
            "Gamma levels are not included unless a provenance-qualified point-in-time source is available.",
            "Social-media percentage returns are not treated as verified performance evidence.",
        ],
        "intraday_212_reversal": evaluate_intraday_212_reversal(intraday),
    }
