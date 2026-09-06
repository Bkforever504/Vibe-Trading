# SPDX-License-Identifier: MPL-2.0
"""Completed-bar CISD lifecycle detector for shadow research.

Concept and detection rules are derived from cephxs / CISD [base] by cephxs
and fstarcapital. This module has no notification, broker, or order authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass
class PendingCISD:
    direction: str
    level: float
    pivot_price: float
    pivot_index: int
    start_index: int
    origin_index: int
    end_close: float
    run_extreme: float
    atr: float


@dataclass
class ConfirmedCISD:
    direction: str
    level: float
    pivot_price: float
    pivot_index: int
    confirmation_index: int
    run_extreme: float
    atr: float
    retest_seen: bool = False


def _number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bar_{field}_invalid") from exc
    if result != result:
        raise ValueError(f"bar_{field}_invalid")
    return result


def normalize_bars(bars: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for position, raw in enumerate(bars):
        row = {
            "timestamp": str(raw.get("timestamp") or raw.get("bar_completed_at") or ""),
            "open": _number(raw.get("open"), "open"),
            "high": _number(raw.get("high"), "high"),
            "low": _number(raw.get("low"), "low"),
            "close": _number(raw.get("close"), "close"),
        }
        if not row["timestamp"]:
            raise ValueError("bar_timestamp_missing")
        if row["low"] > min(row["open"], row["close"]) or row["high"] < max(row["open"], row["close"]):
            raise ValueError("bar_ohlc_invalid")
        if row["low"] > row["high"]:
            raise ValueError("bar_ohlc_invalid")
        if normalized and row["timestamp"] <= normalized[-1]["timestamp"]:
            raise ValueError("bar_timestamps_not_strictly_increasing")
        row["bar_index"] = position
        normalized.append(row)
    return normalized


def _true_ranges(bars: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for index, bar in enumerate(bars):
        previous_close = bars[index - 1]["close"] if index else bar["close"]
        values.append(max(bar["high"] - bar["low"], abs(bar["high"] - previous_close), abs(bar["low"] - previous_close)))
    return values


def _atr_at(true_ranges: list[float], index: int, period: int) -> float | None:
    if index + 1 < period:
        return None
    window = true_ranges[index + 1 - period : index + 1]
    return sum(window) / len(window)


def _pivot_kind(bars: list[dict[str, Any]], index: int) -> str | None:
    if index <= 0 or index >= len(bars) - 1:
        return None
    center, left, right = bars[index], bars[index - 1], bars[index + 1]
    is_high = center["high"] > left["high"] and center["high"] >= right["high"]
    is_low = center["low"] < left["low"] and center["low"] <= right["low"]
    if is_high and not is_low:
        return "HIGH"
    if is_low and not is_high:
        return "LOW"
    return None


def _stretch(
    bars: list[dict[str, Any]], pivot_index: int, direction: str, atr: float,
    atr_multiplier: float, max_scan: int,
) -> PendingCISD | None:
    bullish = direction == "LONG"
    wanted = (lambda bar: bar["close"] < bar["open"]) if bullish else (lambda bar: bar["close"] > bar["open"])
    end = None
    lower = max(-1, pivot_index - max_scan)
    for index in range(pivot_index, lower, -1):
        if wanted(bars[index]):
            end = index
            break
    if end is None:
        return None
    origin = end
    for index in range(end - 1, lower, -1):
        if not wanted(bars[index]):
            break
        origin = index
    level = bars[origin]["open"]
    stretch_size = abs(level - bars[end]["close"])
    if stretch_size < atr * atr_multiplier:
        return None
    span = bars[origin : pivot_index + 1]
    run_extreme = min(row["low"] for row in span) if bullish else max(row["high"] for row in span)
    pivot_price = bars[pivot_index]["low"] if bullish else bars[pivot_index]["high"]
    return PendingCISD(direction, level, pivot_price, pivot_index, pivot_index + 1, origin, bars[end]["close"], run_extreme, atr)


def _event(
    *, symbol: str, timeframe: str, state: str, previous_state: str, bar: Mapping[str, Any],
    setup: PendingCISD | ConfirmedCISD, reason: str, retest_ready: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "signal_id": "cisd_retest_shadow",
        "symbol": symbol,
        "timeframe": timeframe,
        "state": state,
        "previous_state": previous_state,
        "direction": setup.direction,
        "cisd_level": round(setup.level, 8),
        "pivot_price": round(setup.pivot_price, 8),
        "run_extreme": round(setup.run_extreme, 8),
        "atr": round(setup.atr, 8),
        "bar_index": int(bar["bar_index"]),
        "bar_completed_at": bar["timestamp"],
        "reason": reason,
        "retest_ready": retest_ready,
        "discord_shadow_candidate": bool(retest_ready),
        "execution_enabled": False,
        "can_submit_orders": False,
        "shadow_only": True,
    }


def detect_cisd_lifecycle(
    bars: Iterable[Mapping[str, Any]], *, symbol: str, timeframe: str,
    atr_period: int = 14, atr_multiplier: float = 0.5, pending_timeout_bars: int = 10,
    retest_tolerance_atr: float = 0.10, max_scan: int = 300,
) -> list[dict[str, Any]]:
    """Return deterministic lifecycle transitions using completed OHLCV-free bars."""
    data = normalize_bars(bars)
    if atr_period < 2 or pending_timeout_bars < 1 or atr_multiplier < 0:
        raise ValueError("invalid_cisd_configuration")
    true_ranges = _true_ranges(data)
    pending: dict[str, PendingCISD] = {}
    confirmed: dict[str, ConfirmedCISD] = {}
    events: list[dict[str, Any]] = []

    for index, bar in enumerate(data):
        # A length-one pivot becomes knowable only after this completed right-hand bar.
        pivot_index = index - 1
        kind = _pivot_kind(data, pivot_index) if index >= 2 else None
        if kind:
            direction = "SHORT" if kind == "HIGH" else "LONG"
            atr = _atr_at(true_ranges, pivot_index, atr_period)
            if atr is not None:
                candidate = _stretch(data, pivot_index, direction, atr, atr_multiplier, max_scan)
                if candidate is not None:
                    previous = pending.get(direction)
                    if previous is not None:
                        events.append(_event(
                            symbol=symbol, timeframe=timeframe, state="INVALIDATED", previous_state="ARMED",
                            bar=bar, setup=previous, reason="newest_same_direction_candidate_replaced_pending",
                        ))
                    pending[direction] = candidate
                    events.append(_event(
                        symbol=symbol, timeframe=timeframe, state="ARMED", previous_state="WATCH",
                        bar=bar, setup=candidate, reason="completed_pivot_and_atr_filtered_opposing_run",
                    ))

        for direction in list(pending):
            setup = pending[direction]
            if index - setup.start_index >= pending_timeout_bars:
                events.append(_event(
                    symbol=symbol, timeframe=timeframe, state="INVALIDATED", previous_state="ARMED",
                    bar=bar, setup=setup, reason="pending_confirmation_timeout",
                ))
                del pending[direction]
                continue
            opposing_extension = (
                direction == "LONG" and bar["close"] < bar["open"] and bar["close"] < setup.end_close
            ) or (
                direction == "SHORT" and bar["close"] > bar["open"] and bar["close"] > setup.end_close
            )
            if opposing_extension:
                setup.end_close = bar["close"]
                setup.run_extreme = min(setup.run_extreme, bar["low"]) if direction == "LONG" else max(setup.run_extreme, bar["high"])
            is_confirmed = bar["close"] > setup.level if direction == "LONG" else bar["close"] < setup.level
            if is_confirmed:
                live = ConfirmedCISD(
                    direction, setup.level, setup.pivot_price, setup.pivot_index, index,
                    setup.run_extreme, setup.atr,
                )
                confirmed[direction] = live
                events.append(_event(
                    symbol=symbol, timeframe=timeframe, state="CONFIRMED", previous_state="ARMED",
                    bar=bar, setup=live, reason="completed_bar_closed_through_cisd_level",
                ))
                del pending[direction]

        for direction in list(confirmed):
            setup = confirmed[direction]
            if index <= setup.confirmation_index:
                continue
            invalid = bar["low"] < setup.pivot_price if direction == "LONG" else bar["high"] > setup.pivot_price
            if invalid:
                events.append(_event(
                    symbol=symbol, timeframe=timeframe, state="INVALIDATED", previous_state="CONFIRMED",
                    bar=bar, setup=setup, reason="creation_pivot_breached",
                ))
                del confirmed[direction]
                continue
            tolerance = setup.atr * retest_tolerance_atr
            touched = bar["low"] <= setup.level + tolerance if direction == "LONG" else bar["high"] >= setup.level - tolerance
            held = bar["close"] > setup.level if direction == "LONG" else bar["close"] < setup.level
            if touched and held and not setup.retest_seen:
                setup.retest_seen = True
                events.append(_event(
                    symbol=symbol, timeframe=timeframe, state="CONFIRMED", previous_state="CONFIRMED",
                    bar=bar, setup=setup, reason="confirmed_level_retest_held", retest_ready=True,
                ))
    return events
