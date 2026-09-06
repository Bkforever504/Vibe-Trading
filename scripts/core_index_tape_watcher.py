#!/usr/bin/env python3
"""Fast completed-1m SPY/QQQ/IWM tape watcher (shadow alerts only).

This process is intentionally separate from the market-wide scanner. It gives
the priority indexes a one-minute observation lane that cannot be delayed by
full-universe discovery, research enrichment, or five-minute confirmation.
It never selects an option contract, submits an order, or weakens the existing
five-minute confirmation and execution gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import governed_shadow_alert
from agent.observability.trace_context import new_trace_id
from scripts.premarket_opportunity_radar import _credentials
from scripts.priority_focus_universe import CORE_INDEXES


MARKET_TZ = ZoneInfo("America/New_York")
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "core-index-tape-watcher.json"
STATE_PATH = VIBE_HOME / "state" / "core-index-tape-watcher.json"
EVENT_PATH = VIBE_HOME / "data" / "core_index_tape_events.jsonl"
DELIVERY_EVENT_PATH = VIBE_HOME / "data" / "core_index_tape_delivery_events.jsonl"
CORE_SYMBOLS = tuple(CORE_INDEXES)
ARM_WINDOW_BPS = 5.0
ARM_LAST_MINUTE_BPS = 1.5
SHOCK_MINUTE_BPS = 8.0
REVERSAL_EXTENSION_BPS = 20.0
REVERSAL_DRAWDOWN_BPS = 6.0
REVERSAL_PERSIST_DRAWDOWN_BPS = 8.0
REVERSAL_VOLUME_RATIO = 1.25
REVERSAL_FAST_WINDOW = 5
REVERSAL_EXTREME_MAX_AGE_MINUTES = 20
REVERSAL_RECLAIM_BPS = 2.0
REVERSAL_NEW_EXTREME_BPS = 5.0
REVERSAL_COOLDOWN_MINUTES = 30
MAX_FRESHNESS_SECONDS = 90.0
MAX_ALERT_AGE_SECONDS = 90.0
ALERTABLE_STATES = frozenset({"ARMED", "CONFIRMED", "INVALIDATED"})
NYSE_HOLIDAYS_2026 = frozenset({
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
})


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _utc(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def completed_minute_bars(rows: Iterable[Mapping[str, Any]], now_et: datetime) -> list[dict[str, Any]]:
    """Normalize rows and reject any minute that was incomplete at decision time."""
    now_utc = now_et.astimezone(timezone.utc)
    completed: list[dict[str, Any]] = []
    for source in rows:
        started = _utc(source.get("t"))
        values = {key: _finite(source.get(key)) for key in ("o", "h", "l", "c", "v")}
        if started is None or any(value is None for value in values.values()):
            continue
        if (started.second or started.microsecond or values["v"] < 0
                or min(values[key] for key in ("o", "h", "l", "c")) <= 0
                or values["h"] < max(values["o"], values["c"])
                or values["l"] > min(values["o"], values["c"])
                or started.astimezone(MARKET_TZ).date() != now_et.astimezone(MARKET_TZ).date()
                or not wall_time(9, 30) <= started.astimezone(MARKET_TZ).time() < wall_time(16)):
            continue
        if started + timedelta(minutes=1) > now_utc:
            continue
        completed.append({"t": started.isoformat().replace("+00:00", "Z"), **values})
    unique = {str(row["t"]): row for row in completed}
    return [unique[key] for key in sorted(unique)]


def _vwap(rows: list[dict[str, Any]]) -> float | None:
    volume = sum(float(row["v"]) for row in rows)
    if volume <= 0:
        return None
    return sum(float(row["c"]) * float(row["v"]) for row in rows) / volume


def _rolling_reversal(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect an extended-market rollover/bounce without requiring session-VWAP loss.

    The trigger is deliberately causal: a meaningful session extension must
    already exist, price must retreat from that extreme, and the latest close
    must cross the short rolling VWAP.  Relative volume or a larger drawdown
    is required so ordinary one-minute noise does not create a reversal alert.
    """
    if len(rows) < REVERSAL_FAST_WINDOW:
        return {"direction": None}
    if any(_utc(right["t"]) - _utc(left["t"]) != timedelta(minutes=1)
           for left, right in zip(rows[-REVERSAL_FAST_WINDOW:], rows[-REVERSAL_FAST_WINDOW + 1:])):
        return {"direction": None}
    close = float(rows[-1]["c"])
    session_open = float(rows[0]["o"])
    high_row = max(rows, key=lambda row: float(row["h"]))
    low_row = min(rows, key=lambda row: float(row["l"]))
    session_high = float(high_row["h"])
    session_low = float(low_row["l"])
    latest_at = _utc(rows[-1]["t"])
    high_at = _utc(high_row["t"])
    low_at = _utc(low_row["t"])
    high_age = (latest_at - high_at).total_seconds() / 60.0 if latest_at and high_at else math.inf
    low_age = (latest_at - low_at).total_seconds() / 60.0 if latest_at and low_at else math.inf
    fast_rows = rows[-REVERSAL_FAST_WINDOW:]
    fast_vwap = _vwap(fast_rows)
    reference = median(float(row["v"]) for row in rows[:-1][-10:]) if rows[:-1] else 0.0
    volume_ratio = float(rows[-1]["v"]) / reference if reference > 0 else 0.0
    up_extension = (session_high / session_open - 1.0) * 10_000.0
    down_extension = (session_open / session_low - 1.0) * 10_000.0
    drawdown = (session_high / close - 1.0) * 10_000.0
    rebound = (close / session_low - 1.0) * 10_000.0
    bearish = bool(
        fast_vwap is not None
        and up_extension >= REVERSAL_EXTENSION_BPS
        and drawdown >= REVERSAL_DRAWDOWN_BPS
        and 0 <= high_age <= REVERSAL_EXTREME_MAX_AGE_MINUTES
        and close < fast_vwap
        and (volume_ratio >= REVERSAL_VOLUME_RATIO or drawdown >= REVERSAL_PERSIST_DRAWDOWN_BPS)
    )
    bullish = bool(
        fast_vwap is not None
        and down_extension >= REVERSAL_EXTENSION_BPS
        and rebound >= REVERSAL_DRAWDOWN_BPS
        and 0 <= low_age <= REVERSAL_EXTREME_MAX_AGE_MINUTES
        and close > fast_vwap
        and (volume_ratio >= REVERSAL_VOLUME_RATIO or rebound >= REVERSAL_PERSIST_DRAWDOWN_BPS)
    )
    direction = "SHORT" if bearish and not bullish else "LONG" if bullish and not bearish else None
    extreme_at = high_row["t"] if direction == "SHORT" else low_row["t"] if direction == "LONG" else None
    extreme = session_high if direction == "SHORT" else session_low if direction == "LONG" else None
    return {
        "direction": direction,
        "reversal_id": f"{direction}|{extreme_at}" if direction and extreme_at else None,
        "extreme_at": extreme_at,
        "extreme": extreme,
        "session_high": session_high,
        "session_low": session_low,
        "fast_vwap": fast_vwap,
        "extension_bps": up_extension if direction == "SHORT" else down_extension if direction == "LONG" else 0.0,
        "extreme_reversal_bps": drawdown if direction == "SHORT" else rebound if direction == "LONG" else 0.0,
        "volume_ratio": volume_ratio,
    }


def build_observation(
    symbol: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    now_et: datetime,
    previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    session_date = now_et.astimezone(MARKET_TZ).date().isoformat()
    if previous and str(previous.get("session_date") or "") != session_date:
        previous = None
    completed = completed_minute_bars(rows, now_et)
    base = {
        "symbol": symbol.upper(),
        "session_date": session_date,
        "source": "alpaca_completed_1m_bars",
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    def unavailable(reason: str, quality: str) -> dict[str, Any]:
        return {
            **dict(previous or {}),
            **base,
            "state": str((previous or {}).get("state") or "WATCH"),
            "previous_state": str((previous or {}).get("state") or "NONE"),
            "direction": str((previous or {}).get("direction") or "NONE"),
            "reason": reason,
            "data_status": quality,
            "bar_completed_at": (previous or {}).get("bar_completed_at"),
            "detection_latency_seconds": (
                max(0.0, (now_et.astimezone(timezone.utc) - _utc(previous["bar_completed_at"])).total_seconds())
                if previous and _utc(previous.get("bar_completed_at")) else None
            ),
            "alertable": False,
            "transition": False,
        }

    if len(completed) < 2:
        return unavailable("requires_two_completed_1m_bars", "missing")

    last, prior = completed[-1], completed[-2]
    completed_at = (_utc(last["t"]) + timedelta(minutes=1)) if _utc(last["t"]) else None
    if (now_et.astimezone(timezone.utc) - completed_at).total_seconds() > MAX_FRESHNESS_SECONDS:
        return unavailable("latest_completed_bar_is_stale", "stale")
    recent = completed[-3:]
    if any(_utc(right["t"]) - _utc(left["t"]) != timedelta(minutes=1)
           for left, right in zip(recent, recent[1:])):
        return unavailable("nonconsecutive_completed_bars", "gap")
    prior_completed_at = _utc((previous or {}).get("bar_completed_at"))
    if prior_completed_at and completed_at <= prior_completed_at:
        return unavailable("completed_bar_already_observed" if completed_at == prior_completed_at else "out_of_order_completed_bar", "unchanged" if completed_at == prior_completed_at else "out_of_order")
    consecutive_observation = not prior_completed_at or completed_at - prior_completed_at == timedelta(minutes=1)
    session_open = float(completed[0]["o"])
    close = float(last["c"])
    one_minute_bps = (close / float(prior["c"]) - 1.0) * 10_000.0
    window = completed[-3:]
    window_return_bps = (close / float(window[0]["o"]) - 1.0) * 10_000.0
    session_return_bps = (close / session_open - 1.0) * 10_000.0
    vwap = _vwap(completed)
    reversal = _rolling_reversal(completed)
    reversal_direction = str(reversal.get("direction") or "NONE")
    reversal_id = str(reversal.get("reversal_id") or "")
    consumed_reversal_ids = {
        str(value) for value in (previous or {}).get("consumed_reversal_ids") or [] if str(value)
    }
    prior_active_reversal_id = str((previous or {}).get("active_reversal_id") or "")
    prior_pending_reversal_id = str((previous or {}).get("pending_reversal_id") or "")
    cooldown_until = _utc((previous or {}).get("reversal_cooldown_until"))
    last_reversal_direction = str((previous or {}).get("last_reversal_direction") or "NONE")
    last_reversal_extreme = _finite((previous or {}).get("last_reversal_extreme"))
    candidate_extreme = _finite(reversal.get("extreme"))
    candidate_breaks_extreme = bool(
        candidate_extreme is not None
        and last_reversal_extreme is not None
        and reversal_direction == last_reversal_direction
        and (
            (reversal_direction == "SHORT" and candidate_extreme >= last_reversal_extreme * (1.0 + REVERSAL_NEW_EXTREME_BPS / 10_000.0))
            or (reversal_direction == "LONG" and candidate_extreme <= last_reversal_extreme * (1.0 - REVERSAL_NEW_EXTREME_BPS / 10_000.0))
        )
    )
    candidate_is_continuation = reversal_id in {prior_active_reversal_id, prior_pending_reversal_id}
    candidate_suppressed = bool(
        reversal_id
        and not candidate_is_continuation
        and (
            reversal_id in consumed_reversal_ids
            or (cooldown_until and now_et.astimezone(timezone.utc) < cooldown_until and not candidate_breaks_extreme)
        )
    )
    if candidate_suppressed:
        reversal_direction = "NONE"
        reversal_id = ""
    direction = reversal_direction if reversal_direction != "NONE" else ("LONG" if window_return_bps > 0 else "SHORT")
    aligned_with_vwap = bool(vwap is not None and (close > vwap if direction == "LONG" else close < vwap))
    aligned_closes = sum(
        1
        for row in window[-2:]
        if (float(row["c"]) > float(row["o"]) if direction == "LONG" else float(row["c"]) < float(row["o"]))
    ) == 2
    shock = abs(one_minute_bps) >= SHOCK_MINUTE_BPS and ((one_minute_bps > 0) == (direction == "LONG"))
    persistent = bool(
        aligned_closes
        and abs(window_return_bps) >= ARM_WINDOW_BPS
        and abs(one_minute_bps) >= ARM_LAST_MINUTE_BPS
    )
    reversal_pressure = reversal_direction != "NONE"
    pressure = bool(reversal_pressure or (aligned_with_vwap and (shock or persistent)))
    prior_state = str((previous or {}).get("state") or "NONE")
    prior_direction = str((previous or {}).get("direction") or "NONE")
    prior_pressure_mode = str((previous or {}).get("pressure_mode") or "velocity")
    prior_bar = str((previous or {}).get("bar_completed_at") or "")
    new_completed_bar = bool(completed_at and completed_at.isoformat().replace("+00:00", "Z") != prior_bar)
    previous_active = prior_state in {"ARMED", "CONFIRMED"}
    crossed_vwap = bool(
        previous_active
        and prior_pressure_mode != "rolling_reversal"
        and vwap is not None
        and ((prior_direction == "LONG" and close < vwap) or (prior_direction == "SHORT" and close > vwap))
    )
    prior_extreme = _finite((previous or {}).get("reversal_extreme"))
    reversal_failed = bool(
        previous_active
        and prior_pressure_mode == "rolling_reversal"
        and prior_extreme is not None
        and (
            (prior_direction == "SHORT" and close >= prior_extreme * (1.0 - REVERSAL_RECLAIM_BPS / 10_000.0))
            or (prior_direction == "LONG" and close <= prior_extreme * (1.0 + REVERSAL_RECLAIM_BPS / 10_000.0))
        )
    )
    opposite_pressure = pressure and previous_active and direction != prior_direction
    velocity_direction = "LONG" if window_return_bps > 0 else "SHORT"
    opposite_velocity = bool(
        previous_active and velocity_direction != prior_direction and vwap is not None
        and (close > vwap if velocity_direction == "LONG" else close < vwap)
        and ((abs(one_minute_bps) >= SHOCK_MINUTE_BPS and ((one_minute_bps > 0) == (velocity_direction == "LONG")))
             or (abs(window_return_bps) >= ARM_WINDOW_BPS and abs(one_minute_bps) >= ARM_LAST_MINUTE_BPS
                 and all((row["c"] > row["o"] if velocity_direction == "LONG" else row["c"] < row["o"]) for row in window[-2:])))
    )
    active_started_at = _utc((previous or {}).get("active_started_at")) or prior_completed_at
    reversal_expired = bool(prior_state == "ARMED" and prior_pressure_mode == "rolling_reversal"
                            and active_started_at and completed_at - active_started_at > timedelta(minutes=REVERSAL_EXTREME_MAX_AGE_MINUTES))
    favorable_follow_through = bool(
        previous_active
        and prior_pressure_mode == "rolling_reversal"
        and new_completed_bar
        and consecutive_observation
        and (
            (prior_direction == "SHORT" and close < float(prior["c"]) and float(last["h"]) < float(prior["h"]))
            or (prior_direction == "LONG" and close > float(prior["c"]) and float(last["l"]) > float(prior["l"]))
        )
    )

    if reversal_failed:
        state = "INVALIDATED"
        direction = prior_direction
        reason = "rolling_reversal_extreme_reclaimed"
    elif previous_active and prior_pressure_mode == "rolling_reversal" and (opposite_pressure or opposite_velocity or reversal_expired):
        state = "INVALIDATED"
        direction = prior_direction
        reason = "rolling_reversal_confirmation_expired" if reversal_expired else "opposite_one_minute_pressure"
    elif previous_active and prior_pressure_mode == "rolling_reversal" and favorable_follow_through:
        state = "CONFIRMED"
        direction = prior_direction
        reason = "rolling_reversal_lower_high_follow_through" if direction == "SHORT" else "rolling_reversal_higher_low_follow_through"
    elif previous_active and prior_pressure_mode == "rolling_reversal":
        state = prior_state
        direction = prior_direction
        reason = "rolling_reversal_waiting_for_follow_through"
    elif crossed_vwap or opposite_pressure:
        state = "INVALIDATED"
        direction = prior_direction
        reason = "one_minute_pressure_reversed_across_session_vwap" if crossed_vwap else "opposite_one_minute_pressure"
    elif pressure and previous_active and direction == prior_direction:
        successive_pressure = consecutive_observation and (previous or {}).get("pressure_present") is True
        state = "CONFIRMED" if successive_pressure else prior_state
        reason = "two_successive_completed_1m_pressure_observations" if successive_pressure else "awaiting_consecutive_pressure_observations"
    elif pressure:
        state = "ARMED"
        reason = (
            "extended_move_rolling_vwap_reversal" if reversal_pressure
            else "completed_1m_vwap_aligned_velocity_shock" if shock
            else "two_completed_1m_closes_with_vwap_aligned_velocity"
        )
    elif previous_active:
        state = prior_state
        direction = prior_direction
        reason = "active_pressure_has_not_reversed_or_reconfirmed"
    else:
        state = "WATCH"
        direction = "NONE"
        reason = "one_minute_pressure_threshold_not_met"

    bar_completed_at = completed_at.isoformat().replace("+00:00", "Z") if completed_at else None
    pending_reversal_id = reversal_id if state == "INVALIDATED" and reversal_pressure and reversal_direction != prior_direction else ""
    active_reversal_id = ""
    reversal_extreme = None
    reversal_extreme_at = None
    if state in {"ARMED", "CONFIRMED"} and (reversal_pressure or prior_pressure_mode == "rolling_reversal"):
        keep_prior = previous_active and prior_pressure_mode == "rolling_reversal"
        active_reversal_id = prior_active_reversal_id if keep_prior else reversal_id
        reversal_extreme = prior_extreme if keep_prior else reversal.get("extreme")
        reversal_extreme_at = (previous or {}).get("reversal_extreme_at") if keep_prior else reversal.get("extreme_at")
    if state == "INVALIDATED" and prior_active_reversal_id:
        consumed_reversal_ids.add(prior_active_reversal_id)
        cooldown_until = completed_at + timedelta(minutes=REVERSAL_COOLDOWN_MINUTES) if completed_at else cooldown_until
        last_reversal_direction = prior_direction
        last_reversal_extreme = prior_extreme
    latency = max(0.0, (now_et.astimezone(timezone.utc) - completed_at).total_seconds()) if completed_at else None
    transition = state != prior_state and state in ALERTABLE_STATES
    volume_reference = median(float(row["v"]) for row in completed[:-1][-10:]) if completed[:-1] else None
    return {
        **base,
        "state": state,
        "previous_state": prior_state,
        "direction": direction,
        "reason": reason,
        "data_status": "ok",
        "pressure_present": pressure,
        "active_started_at": (active_started_at if previous_active else completed_at).isoformat().replace("+00:00", "Z") if state in {"ARMED", "CONFIRMED"} else None,
        "bar_completed_at": bar_completed_at,
        "detected_at": now_et.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "detection_latency_seconds": round(latency, 3) if latency is not None else None,
        "last_price": round(close, 4),
        "session_open": round(session_open, 4),
        "session_vwap": round(vwap, 4) if vwap is not None else None,
        "fast_vwap": round(float(reversal["fast_vwap"]), 4) if reversal.get("fast_vwap") is not None else None,
        "session_high": round(float(reversal["session_high"]), 4) if reversal.get("session_high") is not None else None,
        "session_low": round(float(reversal["session_low"]), 4) if reversal.get("session_low") is not None else None,
        "reversal_direction": reversal_direction,
        "active_reversal_id": active_reversal_id or None,
        "pending_reversal_id": pending_reversal_id or None,
        "reversal_extreme": round(float(reversal_extreme), 4) if reversal_extreme is not None else None,
        "reversal_extreme_at": reversal_extreme_at,
        "consumed_reversal_ids": sorted(consumed_reversal_ids)[-20:],
        "reversal_cooldown_until": cooldown_until.isoformat().replace("+00:00", "Z") if cooldown_until else None,
        "last_reversal_direction": last_reversal_direction,
        "last_reversal_extreme": round(float(last_reversal_extreme), 4) if last_reversal_extreme is not None else None,
        "extreme_reversal_bps": round(float(reversal.get("extreme_reversal_bps") or 0.0), 2),
        "pressure_mode": "rolling_reversal" if active_reversal_id else "velocity",
        "one_minute_return_bps": round(one_minute_bps, 2),
        "window_return_bps": round(window_return_bps, 2),
        "session_return_bps": round(session_return_bps, 2),
        "last_minute_volume_ratio": round(float(last["v"]) / volume_reference, 2) if volume_reference else None,
        "completed_1m_bars": len(completed),
        "alertable": transition,
        "transition": transition,
        "warning": "Early tape observation only; completed 5m confirmation is still required before manual trade review.",
    }


def fetch_completed_1m(
    symbols: Iterable[str], *, now_et: datetime, feed: str = "iex"
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    requested = list(dict.fromkeys(str(value).upper() for value in symbols if str(value).strip()))
    start = datetime.combine(now_et.astimezone(MARKET_TZ).date(), wall_time(9, 30), MARKET_TZ)
    params = {
        "symbols": ",".join(requested),
        "timeframe": "1Min",
        "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "end": now_et.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "adjustment": "raw",
        "feed": feed,
        "limit": 10000,
        "sort": "asc",
    }
    last_error = "unknown"
    for attempt in range(1, 4):
        try:
            response = requests.get(
                "https://data.alpaca.markets/v2/stocks/bars",
                headers=_credentials(),
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            output = {
                symbol: completed_minute_bars(rows or [], now_et)
                for symbol, rows in (payload.get("bars") or {}).items()
                if str(symbol).upper() in requested
            }
            return {str(key).upper(): value for key, value in output.items()}, []
        except Exception as exc:
            last_error = type(exc).__name__
            if attempt < 3:
                time.sleep(0.2 * attempt)
    return {}, [f"alpaca_completed_1m:{last_error}"]


def build_report(
    *, now_et: datetime | None = None, previous_state: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    clock = (now_et or datetime.now(timezone.utc).astimezone(MARKET_TZ)).astimezone(MARKET_TZ)
    prior = previous_state or {}
    prior_rows = prior.get("observations") if isinstance(prior.get("observations"), Mapping) else {}
    session_date = clock.date().isoformat()
    market_day = clock.weekday() < 5 and session_date not in NYSE_HOLIDAYS_2026
    in_window = wall_time(9, 30) <= clock.time() <= wall_time(16, 5) and market_day
    bars: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    feed = str(os.getenv("VIBE_TRADING_STOCK_FEED") or "iex").lower()
    feed = feed if feed in {"iex", "sip"} else "iex"
    if in_window:
        bars, errors = fetch_completed_1m(CORE_SYMBOLS, now_et=clock, feed=feed)
    observations = [
        build_observation(
            symbol,
            bars.get(symbol, []),
            now_et=clock,
            previous=prior_rows.get(symbol) if isinstance(prior_rows, Mapping) else None,
        )
        for symbol in CORE_SYMBOLS
    ]
    observed = sum(row.get("data_status") in {"ok", "unchanged"} for row in observations)
    stale = sum(
        float(row.get("detection_latency_seconds") or 0) > MAX_FRESHNESS_SECONDS
        for row in observations
        if row.get("bar_completed_at") is not None
    )
    status = "market_closed" if not market_day else "outside_rth" if not in_window else "ok" if not errors and observed == len(CORE_SYMBOLS) and not stale else "warming" if not errors and clock.time() < wall_time(9, 33) else "degraded"
    return {
        "schema_version": "core-index-tape-watcher-v1",
        "generated_at": clock.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "as_of_et": clock.isoformat(),
        "status": status,
        "provider": f"alpaca_{feed}_completed_1m",
        "symbols": list(CORE_SYMBOLS),
        "observations": observations,
        "state_counts": {state: sum(row.get("state") == state for row in observations) for state in ("WATCH", "ARMED", "CONFIRMED", "INVALIDATED")},
        "coverage": {"requested": len(CORE_SYMBOLS), "observed": observed, "stale": stale, "unavailable": len(CORE_SYMBOLS) - observed, "freshness_slo_seconds": MAX_FRESHNESS_SECONDS},
        "errors": errors,
        "notification_attempts": 0,
        "alerts_sent": 0,
        "notification_failures": 0,
        "pending_delivery": 0,
        "execution_enabled": False,
        "can_submit_orders": False,
        "warning": "Fast one-minute eyes and shadow heads-ups only. Not an options contract recommendation and no order authority.",
    }


def _transition_id(row: Mapping[str, Any]) -> str:
    raw = "|".join(str(row.get(key) or "") for key in ("session_date", "symbol", "state", "direction", "bar_completed_at"))
    return hashlib.sha256((raw + "|core-index-tape-watcher-v1").encode("utf-8")).hexdigest()


def _event(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "transition_id": _transition_id(row),
        **{key: row.get(key) for key in (
            "session_date", "symbol", "previous_state", "state", "direction", "reason",
            "bar_completed_at", "detected_at", "detection_latency_seconds", "last_price",
            "session_vwap", "one_minute_return_bps", "window_return_bps", "session_return_bps",
            "execution_enabled", "can_submit_orders",
        )},
        "alertable": row.get("alertable") is True,
    }


def _append_unique(path: Path, events: Iterable[Mapping[str, Any]]) -> None:
    seen: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(str(json.loads(line).get("transition_id") or ""))
            except json.JSONDecodeError:
                continue
    fresh = [dict(row) for row in events if str(row.get("transition_id") or "") not in seen]
    if not fresh:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in fresh:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def format_alert(event: Mapping[str, Any]) -> str:
    proxy = " (SPX proxy)" if event.get("symbol") == "SPY" else ""
    return (
        f"**FAST TAPE {event.get('state')} | {event.get('symbol')}{proxy} {event.get('direction')}**\n"
        f"Completed 1m `{event.get('bar_completed_at')}` | detected +`{event.get('detection_latency_seconds')}s`\n"
        f"Price `{event.get('last_price')}` | VWAP `{event.get('session_vwap')}` | "
        f"1m `{event.get('one_minute_return_bps')} bp` | window `{event.get('window_return_bps')} bp`\n"
        f"Reason `{event.get('reason')}`\n"
        "Early shadow heads-up only. Wait for the separate completed-5m trade review; no option contract selected and No order placed."
    )


def persist_run(
    report: dict[str, Any], *, report_path: Path = REPORT_PATH, state_path: Path = STATE_PATH,
    event_path: Path = EVENT_PATH, alert: bool = False,
    sender: Callable[[str], Mapping[str, Any]] | None = None,
    delivery_event_path: Path | None = None,
    utc_clock: Callable[[], datetime] | None = None,
) -> None:
    clock = utc_clock or (lambda: datetime.now(timezone.utc))
    delivery_event_path = delivery_event_path or (DELIVERY_EVENT_PATH if event_path == EVENT_PATH else event_path.with_name(event_path.stem + "_deliveries.jsonl"))
    previous = _read_json(state_path)
    delivered = {str(value) for value in previous.get("delivered_transition_ids") or []}
    pending = [dict(row) for row in previous.get("pending_alerts") or [] if isinstance(row, Mapping)]
    transitions = [_event(row) for row in report.get("observations") or [] if isinstance(row, Mapping) and row.get("transition") is True]
    _append_unique(event_path, transitions)
    observations = {
        str(row.get("symbol")): dict(row)
        for row in report.get("observations") or []
        if isinstance(row, Mapping) and row.get("symbol")
    }
    retry: list[dict[str, Any]] = []
    attempts = sent = failures = 0
    error_classes: dict[str, int] = {}
    dropped: dict[str, int] = {}

    def rejection(event: Mapping[str, Any]) -> str | None:
        current = observations.get(str(event.get("symbol")))
        bar_at = _utc(event.get("bar_completed_at"))
        age = (clock().astimezone(timezone.utc) - bar_at).total_seconds() if bar_at else None
        if age is None or age < 0 or age > MAX_ALERT_AGE_SECONDS:
            return "expired"
        if current is None or current.get("session_date") != event.get("session_date"):
            return "missing_current_session"
        if current.get("data_status", "ok") not in {"ok", "unchanged"}:
            return "unavailable_current_feed"
        if any(current.get(key) != event.get(key) for key in ("state", "direction")):
            return "superseded"
        if current.get("transition") is True and _transition_id(current) != event.get("transition_id"):
            return "superseded"
        return None

    def record_delivery(event: Mapping[str, Any], **fields: Any) -> None:
        delivery_event_path.parent.mkdir(parents=True, exist_ok=True)
        with delivery_event_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({**dict(event), **fields, "execution_enabled": False, "can_submit_orders": False}, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    if alert:
        transport = sender or governed_shadow_alert.deliver
        by_id = {
            str(row.get("transition_id")): row
            for row in [*pending, *transitions]
            if row.get("transition_id") and row.get("alertable") is True
        }
        for transition_id, event in by_id.items():
            if transition_id in delivered:
                continue
            rejected = rejection(event)
            if rejected:
                dropped[rejected] = dropped.get(rejected, 0) + 1
                record_delivery(event, delivery_status="dropped", drop_reason=rejected, recorded_at=clock().isoformat(), attempted_at=None, delivered_at=None)
                continue
            attempted_at = clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            try:
                result = dict(transport(format_alert(event)))
            except Exception as exc:
                result = {"delivered": False, "attempts": 1, "error_class": type(exc).__name__}
            completed_at = clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            discord_message_id = result.get("discord_message_id")
            discord_delivered_ts = result.get("discord_delivered_ts")
            exact_receipt = bool(result.get("delivered") is True and discord_message_id and discord_delivered_ts)
            record_delivery(event, attempted_at=attempted_at, completed_at=completed_at,
                            trace_id=new_trace_id(str(event.get("transition_id"))),
                            bar_close_ts=event.get("bar_completed_at"),
                            scanner_emit_ts=event.get("detected_at"),
                            decision_ts=event.get("detected_at"),
                            dispatch_send_ts=attempted_at,
                            discord_message_id=discord_message_id,
                            discord_delivered_ts=discord_delivered_ts,
                            ack_receipt_ts=result.get("ack_receipt_ts") or completed_at,
                            delivery_timestamp_semantics="discord_message_timestamp" if exact_receipt else "http_ack_only" if result.get("delivered") is True else "missing",
                            signal_available_at=event.get("bar_completed_at"),
                            decision_at=event.get("detected_at"),
                            delivered_at=discord_delivered_ts if exact_receipt else None,
                            delivery_status="delivered" if result.get("delivered") is True else "failed",
                            delivery_result=result)
            attempts += max(0, int(result.get("attempts") or 0))
            if result.get("delivered") is True:
                delivered.add(transition_id)
                sent += 1
            else:
                failures += 1
                retry.append(event)
                label = str(result.get("error_class") or "unknown_delivery_error")
                error_classes[label] = error_classes.get(label, 0) + 1
    else:
        retry = [row for row in pending if rejection(row) is None]
    _atomic_json(state_path, {
        "schema_version": 1,
        "updated_at": report.get("generated_at"),
        "observations": observations,
        "delivered_transition_ids": sorted(delivered)[-5000:],
        "pending_alerts": retry,
        "execution_enabled": False,
        "can_submit_orders": False,
    })
    report["notification_attempts"] = attempts
    report["alerts_sent"] = sent
    report["notification_failures"] = failures
    report["pending_delivery"] = len(retry)
    report["notification_error_classes"] = dict(sorted(error_classes.items()))
    report["dropped_delivery_reasons"] = dict(sorted(dropped.items()))
    _atomic_json(report_path, report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alert", action="store_true")
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument("--event-path", type=Path, default=EVENT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    previous = _read_json(args.state_path)
    report = build_report(previous_state=previous)
    persist_run(report, report_path=args.report_path, state_path=args.state_path, event_path=args.event_path, alert=args.alert)
    if args.print_report:
        print(json.dumps({key: report[key] for key in ("status", "state_counts", "coverage", "alerts_sent", "pending_delivery")}, sort_keys=True))
    return 0 if report.get("status") in {"ok", "warming", "outside_rth", "market_closed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
