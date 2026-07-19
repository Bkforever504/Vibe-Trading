"""Deterministic ICT-style macro setup evaluator for futures shadow research.

The social vocabulary is converted into testable OHLC rules. This module is
pure signal research: no broker client, orders, account mutation, or live gate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, time
from typing import Any, Literal
from zoneinfo import ZoneInfo

import pandas as pd

NY = ZoneInfo("America/New_York")
Direction = Literal["buy", "sell"]


@dataclass(frozen=True)
class IctMacroConfig:
    macro_windows: tuple[tuple[time, time], ...] = (
        (time(9, 50), time(10, 10)),
        (time(10, 50), time(11, 10)),
    )
    displacement_body_multiple: float = 1.5
    displacement_close_fraction: float = 0.70
    displacement_lookahead_bars: int = 3
    entry_lookahead_bars: int = 6
    max_trades_per_day: int = 1
    reward_risk: float = 2.0
    tick_size: float = 0.25


def _frame(bars: pd.DataFrame) -> pd.DataFrame:
    result = bars.copy()
    result.columns = [str(column).lower() for column in result.columns]
    required = ["open", "high", "low", "close"]
    if not all(column in result for column in required):
        return pd.DataFrame(columns=required)
    result.index = pd.to_datetime(result.index)
    if result.index.tz is None:
        result.index = result.index.tz_localize(NY)
    else:
        result.index = result.index.tz_convert(NY)
    return result.dropna(subset=required).sort_index()


def _inside_macro(timestamp: pd.Timestamp, config: IctMacroConfig) -> bool:
    value = timestamp.time().replace(tzinfo=None)
    return any(start <= value <= end for start, end in config.macro_windows)


def _median_prior_body(frame: pd.DataFrame, position: int, lookback: int = 20) -> float:
    prior = frame.iloc[max(0, position - lookback):position]
    if prior.empty:
        return 0.0
    return float((prior["close"] - prior["open"]).abs().median())


def _displacement(frame: pd.DataFrame, position: int, direction: Direction, config: IctMacroConfig) -> bool:
    row = frame.iloc[position]
    candle_range = float(row["high"] - row["low"])
    body = abs(float(row["close"] - row["open"]))
    baseline = _median_prior_body(frame, position)
    if candle_range <= 0 or baseline <= 0 or body < baseline * config.displacement_body_multiple:
        return False
    if direction == "buy":
        close_fraction = (float(row["close"]) - float(row["low"])) / candle_range
        return float(row["close"]) > float(row["open"]) and close_fraction >= config.displacement_close_fraction
    close_fraction = (float(row["high"]) - float(row["close"])) / candle_range
    return float(row["close"]) < float(row["open"]) and close_fraction >= config.displacement_close_fraction


def _fvg_at(frame: pd.DataFrame, position: int, direction: Direction) -> tuple[float, float] | None:
    if position < 2:
        return None
    current = frame.iloc[position]
    two_back = frame.iloc[position - 2]
    if direction == "buy" and float(current["low"]) > float(two_back["high"]):
        return float(two_back["high"]), float(current["low"])
    if direction == "sell" and float(current["high"]) < float(two_back["low"]):
        return float(current["high"]), float(two_back["low"])
    return None


def _opposite_candle_zone(frame: pd.DataFrame, start: int, end: int, direction: Direction) -> tuple[float, float] | None:
    for position in range(end, start - 1, -1):
        row = frame.iloc[position]
        opposite = (
            direction == "buy" and float(row["close"]) < float(row["open"])
            or direction == "sell" and float(row["close"]) > float(row["open"])
        )
        if opposite:
            return min(float(row["open"]), float(row["close"])), max(float(row["open"]), float(row["close"]))
    return None


def _accepted_retest(row: pd.Series, zone: tuple[float, float], direction: Direction) -> bool:
    bottom, top = zone
    midpoint = (bottom + top) / 2.0
    touched = float(row["low"]) <= top and float(row["high"]) >= bottom
    if direction == "buy":
        return touched and float(row["close"]) > midpoint
    return touched and float(row["close"]) < midpoint


def _session_target(levels: dict[str, float], direction: Direction, entry: float, modeled_target: float) -> tuple[str, float]:
    if direction == "buy":
        candidates = sorted(
            ((name, value) for name, value in levels.items() if "high" in name and value > entry),
            key=lambda item: item[1],
        )
        qualifying = [(name, value) for name, value in candidates if value >= modeled_target]
        return qualifying[0] if qualifying else ("modeled_2r", modeled_target)
    candidates = sorted(
        ((name, value) for name, value in levels.items() if "low" in name and value < entry),
        key=lambda item: item[1],
        reverse=True,
    )
    qualifying = [(name, value) for name, value in candidates if value <= modeled_target]
    return qualifying[0] if qualifying else ("modeled_2r", modeled_target)


def _base(status: str) -> dict[str, Any]:
    return {
        "strategy": "ict_macro_liquidity_sweep",
        "status": status,
        "mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "live_execution_allowed": False,
        "shadow_signal": False,
    }


def evaluate_macro_setup(
    bars: pd.DataFrame,
    *,
    levels: dict[str, float | None],
    config: IctMacroConfig | None = None,
    high_impact_news_veto: bool = False,
) -> dict[str, Any]:
    """Find the first valid macro-window sweep, displacement, and retest."""
    config = config or IctMacroConfig()
    frame = _frame(bars)
    valid_levels = {
        str(name): float(value)
        for name, value in levels.items()
        if value is not None and float(value) > 0
    }
    if high_impact_news_veto:
        return {**_base("blocked_high_impact_news"), "news_veto": True}
    if len(frame) < 8 or not valid_levels:
        return {**_base("insufficient_bars_or_levels"), "bar_count": len(frame)}

    prior_day_high = valid_levels.get("prior_day_high")
    prior_day_low = valid_levels.get("prior_day_low")
    dealing_midpoint = (
        (prior_day_high + prior_day_low) / 2.0
        if prior_day_high is not None and prior_day_low is not None
        else None
    )
    low_levels = {name: value for name, value in valid_levels.items() if "low" in name}
    high_levels = {name: value for name, value in valid_levels.items() if "high" in name}

    for sweep_pos in range(1, len(frame) - 3):
        timestamp = pd.Timestamp(frame.index[sweep_pos])
        if not _inside_macro(timestamp, config):
            continue
        sweep = frame.iloc[sweep_pos]
        candidates: list[tuple[Direction, str, float]] = []
        for name, level in low_levels.items():
            if float(sweep["low"]) < level and float(sweep["close"]) > level:
                candidates.append(("buy", name, level))
        for name, level in high_levels.items():
            if float(sweep["high"]) > level and float(sweep["close"]) < level:
                candidates.append(("sell", name, level))
        for direction, swept_name, swept_level in candidates:
            location_ok = (
                dealing_midpoint is None
                or direction == "buy" and float(sweep["close"]) <= dealing_midpoint
                or direction == "sell" and float(sweep["close"]) >= dealing_midpoint
            )
            if not location_ok:
                continue
            displacement_pos = next(
                (
                    position
                    for position in range(sweep_pos + 1, min(len(frame), sweep_pos + 1 + config.displacement_lookahead_bars))
                    if _displacement(frame, position, direction, config)
                ),
                None,
            )
            if displacement_pos is None:
                continue
            fvg_pos = next(
                (
                    position
                    for position in range(displacement_pos, min(len(frame), displacement_pos + 3))
                    if _fvg_at(frame, position, direction) is not None
                ),
                None,
            )
            entry_model = "ifvg_retest"
            zone = _fvg_at(frame, fvg_pos, direction) if fvg_pos is not None else None
            zone_formed_pos = fvg_pos
            if zone is None:
                entry_model = "breaker_block_retest"
                zone = _opposite_candle_zone(frame, sweep_pos, displacement_pos, direction)
                zone_formed_pos = displacement_pos
            if zone is None or zone_formed_pos is None:
                continue
            entry_pos = next(
                (
                    position
                    for position in range(zone_formed_pos + 1, min(len(frame), zone_formed_pos + 1 + config.entry_lookahead_bars))
                    if _accepted_retest(frame.iloc[position], zone, direction)
                ),
                None,
            )
            if entry_pos is None:
                continue
            entry_row = frame.iloc[entry_pos]
            entry = float(entry_row["close"])
            stop = (
                float(sweep["low"]) - config.tick_size
                if direction == "buy"
                else float(sweep["high"]) + config.tick_size
            )
            risk = abs(entry - stop)
            if risk <= 0:
                continue
            modeled_target = entry + config.reward_risk * risk if direction == "buy" else entry - config.reward_risk * risk
            target_name, target = _session_target(valid_levels, direction, entry, modeled_target)
            return {
                **_base("signal"),
                "shadow_signal": True,
                "direction": direction,
                "swept_level": swept_name,
                "swept_level_price": round(swept_level, 4),
                "sweep_at": timestamp.isoformat(),
                "sweep_extreme": round(float(sweep["low"] if direction == "buy" else sweep["high"]), 4),
                "displacement_at": pd.Timestamp(frame.index[displacement_pos]).isoformat(),
                "entry_model": entry_model,
                "entry_zone": {"bottom": round(zone[0], 4), "top": round(zone[1], 4)},
                "entry_at": pd.Timestamp(frame.index[entry_pos]).isoformat(),
                "entry": round(entry, 4),
                "stop": round(stop, 4),
                "target": round(target, 4),
                "target_source": target_name,
                "reward_risk": round(abs(target - entry) / risk, 3),
                "premium_discount_midpoint": round(dealing_midpoint, 4) if dealing_midpoint is not None else None,
                "premium_discount_location": "discount" if direction == "buy" else "premium",
                "macro_window_valid": True,
                "news_veto": False,
                "config": asdict(config),
            }
    return {**_base("no_complete_sequence"), "news_veto": False}


def build_session_levels(bars: pd.DataFrame, trading_day: date | None = None) -> dict[str, float | None]:
    """Build prior-RTH, overnight, Asia, and London liquidity levels."""
    frame = _frame(bars)
    if frame.empty:
        return {}
    trading_day = trading_day or frame.index.max().date()
    previous_dates = sorted({value for value in frame.index.date if value < trading_day})
    prior_date = previous_dates[-1] if previous_dates else None

    def subset(day: date, start: time, end: time) -> pd.DataFrame:
        values = frame[frame.index.date == day]
        return values.between_time(start.strftime("%H:%M"), end.strftime("%H:%M"))

    prior_rth = subset(prior_date, time(9, 30), time(16, 0)) if prior_date else pd.DataFrame()
    asia_parts = []
    overnight_parts = []
    if prior_date:
        asia_parts.append(subset(prior_date, time(20, 0), time(23, 59)))
        overnight_parts.append(subset(prior_date, time(18, 0), time(23, 59)))
    asia_parts.append(subset(trading_day, time(0, 0), time(2, 0)))
    overnight_parts.append(subset(trading_day, time(0, 0), time(9, 29)))
    asia = pd.concat(asia_parts) if asia_parts else pd.DataFrame()
    overnight = pd.concat(overnight_parts) if overnight_parts else pd.DataFrame()
    london = subset(trading_day, time(2, 0), time(5, 0))

    def high(values: pd.DataFrame) -> float | None:
        return float(values["high"].max()) if not values.empty else None

    def low(values: pd.DataFrame) -> float | None:
        return float(values["low"].min()) if not values.empty else None

    return {
        "prior_day_high": high(prior_rth),
        "prior_day_low": low(prior_rth),
        "overnight_high": high(overnight),
        "overnight_low": low(overnight),
        "asia_high": high(asia),
        "asia_low": low(asia),
        "london_high": high(london),
        "london_low": low(london),
    }
