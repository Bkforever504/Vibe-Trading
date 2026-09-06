#!/usr/bin/env python3
"""Causal multi-symbol daily level map with completed three-minute confirmation.

This is a shadow observation lane.  It maps reproducible public reference
levels from information available before the current decision, then describes
the latest completed three-minute interaction as WATCH, ARMED, CONFIRMED,
LATE, INVALIDATED, or DORMANT.  It does not reproduce proprietary
"magnet"/"magnitude" formulas and cannot submit an order.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_data import fetch_ohlcv
from scripts.premarket_opportunity_radar import _credentials, _finite
from scripts.priority_focus_universe import PRIORITY_FOCUS_UNIVERSE
from scripts import governed_shadow_alert


ET = ZoneInfo("America/New_York")
UNIVERSE = PRIORITY_FOCUS_UNIVERSE
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "daily-level-map-shadow.json"
EVENT_PATH = ROOT / "data" / "daily_level_map_shadow_candidates.jsonl"
STATE_PATH = VIBE_HOME / "state" / "daily-level-map-shadow-alerts.json"
DELIVERY_EVENT_PATH = VIBE_HOME / "data" / "daily_level_map_alert_events.jsonl"
CUSTOM_LEVEL_PATH = ROOT / "data" / "external_custom_levels.json"
ALERT_STATES = {"WATCH", "ARMED", "CONFIRMED", "LATE", "INVALIDATED"}
DIRECT_ALERT_STATES = {"WATCH", "ARMED", "LATE", "INVALIDATED"}
MAX_3M_FEED_AGE = timedelta(minutes=6)


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ET)
    return parsed.astimezone(ET)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _append_jsonl(path: Path, value: Mapping[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(value), separators=(",", ":"), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return True
    except OSError:
        return False


def normalize_minute_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normalize one-minute bar-start timestamps without declaring completion."""
    normalized: list[dict[str, Any]] = []
    for row in rows:
        stamp = _timestamp(row.get("t") or row.get("timestamp"))
        values = {
            key: _finite(row.get(short) if row.get(short) is not None else row.get(key))
            for key, short in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"), ("volume", "v"))
        }
        if stamp is None or any(value is None for value in values.values()):
            continue
        normalized.append({"timestamp": stamp, **{key: float(value) for key, value in values.items()}})
    return sorted(normalized, key=lambda row: row["timestamp"])


def completed_three_minute_bars(rows: Iterable[Mapping[str, Any]], *, as_of: datetime) -> list[dict[str, Any]]:
    """Aggregate only three consecutive, fully completed one-minute bars.

    Input timestamps are treated as bar starts.  A 09:30 three-minute bar is
    decision-available at 09:33 ET, never at 09:30 or after only two minutes.
    """
    clock = as_of.astimezone(ET)
    groups: dict[datetime, list[dict[str, Any]]] = {}
    for row in normalize_minute_rows(rows):
        stamp = row["timestamp"]
        if stamp + timedelta(minutes=1) > clock:
            continue
        bucket = stamp.replace(minute=stamp.minute - stamp.minute % 3, second=0, microsecond=0)
        groups.setdefault(bucket, []).append(row)
    completed: list[dict[str, Any]] = []
    for bucket, members in sorted(groups.items()):
        expected = [bucket + timedelta(minutes=index) for index in range(3)]
        by_stamp = {row["timestamp"].replace(second=0, microsecond=0): row for row in members}
        if bucket + timedelta(minutes=3) > clock or any(stamp not in by_stamp for stamp in expected):
            continue
        ordered = [by_stamp[stamp] for stamp in expected]
        completed.append({
            "timestamp": bucket,
            "completed_at": bucket + timedelta(minutes=3),
            "open": ordered[0]["open"],
            "high": max(row["high"] for row in ordered),
            "low": min(row["low"] for row in ordered),
            "close": ordered[-1]["close"],
            "volume": sum(row["volume"] for row in ordered),
            "source_bar_count": 3,
        })
    return completed


def _daily_rows(frame: pd.DataFrame | Iterable[Mapping[str, Any]], *, as_of: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(frame, pd.DataFrame):
        iterator = (
            {"date": index, **{str(key).lower(): value for key, value in series.items()}}
            for index, series in frame.iterrows()
        )
    else:
        iterator = (dict(row) for row in frame)
    for row in iterator:
        raw_date = row.get("date") or row.get("timestamp") or row.get("t")
        try:
            session_date = pd.Timestamp(raw_date).date()
        except (TypeError, ValueError):
            continue
        values = {key: _finite(row.get(key) if row.get(key) is not None else row.get(key[0])) for key in ("open", "high", "low", "close")}
        if session_date >= as_of or any(value is None for value in values.values()):
            continue
        rows.append({"date": session_date, **{key: float(value) for key, value in values.items()}})
    return sorted(rows, key=lambda row: row["date"])


def _daily_atr(rows: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(rows) < period + 1:
        return None
    true_ranges: list[float] = []
    for prior, current in zip(rows[-period - 1:-1], rows[-period:]):
        true_ranges.append(max(
            current["high"] - current["low"],
            abs(current["high"] - prior["close"]),
            abs(current["low"] - prior["close"]),
        ))
    return sum(true_ranges) / len(true_ranges)


def _daily_bias(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [row["close"] for row in rows]
    if len(closes) < 21:
        return {"state": "UNAVAILABLE", "reason": "requires_21_completed_daily_bars"}
    sma_now = sum(closes[-20:]) / 20
    sma_prior = sum(closes[-21:-1]) / 20
    close = closes[-1]
    state = "BULLISH" if close > sma_now > sma_prior else "BEARISH" if close < sma_now < sma_prior else "NEUTRAL"
    return {
        "state": state, "completed_daily_close": round(close, 4),
        "sma20": round(sma_now, 4), "sma20_prior": round(sma_prior, 4),
        "definition": "last_completed_daily_close_vs_20_day_sma_and_one_day_sma_slope",
    }


def build_public_level_map(
    symbol: str,
    daily: pd.DataFrame | Iterable[Mapping[str, Any]],
    minute_rows: Iterable[Mapping[str, Any]],
    *,
    now_et: datetime,
    custom_levels: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Build levels that are reproducible from completed bars or typed input."""
    day_rows = _daily_rows(daily, as_of=now_et.date())
    if not day_rows:
        return {"symbol": symbol, "status": "unavailable", "reason": "no_completed_daily_bars", "levels": []}
    prior = day_rows[-1]
    atr = _daily_atr(day_rows)
    current_week = now_et.date() - timedelta(days=now_et.weekday())
    prior_week_rows = [row for row in day_rows if current_week - timedelta(days=7) <= row["date"] < current_week]
    minute = normalize_minute_rows(minute_rows)
    completed_minute = [row for row in minute if row["timestamp"] + timedelta(minutes=1) <= now_et]
    current_date = now_et.date()
    premarket = [row for row in completed_minute if row["timestamp"].date() == current_date and time(4) <= row["timestamp"].time() < time(9, 30)]
    overnight_start = datetime.combine(current_date - timedelta(days=1), time(16), ET)
    overnight = [row for row in completed_minute if overnight_start <= row["timestamp"] < datetime.combine(current_date, time(9, 30), ET)]
    levels: list[dict[str, Any]] = []

    def add(name: str, price: float | None, role: str, source: str, **extra: Any) -> None:
        if price is None or not math.isfinite(float(price)):
            return
        levels.append({
            "name": name, "price": round(float(price), 4), "role": role, "source": source,
            "provenance": "reproducible_public_completed_bar", "external_unverified": False, **extra,
        })

    add("prior_day_high", prior["high"], "resistance", "last_completed_daily_bar")
    add("prior_day_low", prior["low"], "support", "last_completed_daily_bar")
    add("prior_day_close", prior["close"], "two_sided", "last_completed_daily_bar")
    if prior_week_rows:
        add("prior_week_high", max(row["high"] for row in prior_week_rows), "resistance", "completed_prior_calendar_week")
        add("prior_week_low", min(row["low"] for row in prior_week_rows), "support", "completed_prior_calendar_week")
    if premarket:
        pre_high, pre_low = max(row["high"] for row in premarket), min(row["low"] for row in premarket)
        add("premarket_high", pre_high, "resistance", "completed_current_premarket_1m")
        add("premarket_low", pre_low, "support", "completed_current_premarket_1m")
        add("premarket_mid", (pre_high + pre_low) / 2, "two_sided", "completed_current_premarket_1m")
    if overnight:
        overnight_high, overnight_low = max(row["high"] for row in overnight), min(row["low"] for row in overnight)
        add("overnight_high", overnight_high, "resistance", "completed_extended_hours_1m")
        add("overnight_low", overnight_low, "support", "completed_extended_hours_1m")
        add("overnight_mid", (overnight_high + overnight_low) / 2, "two_sided", "completed_extended_hours_1m")
    if atr is not None:
        add("prior_close_plus_atr", prior["close"] + atr, "resistance", "completed_daily_atr14_projection", projection=True)
        add("prior_close_minus_atr", prior["close"] - atr, "support", "completed_daily_atr14_projection", projection=True)

    for custom in custom_levels:
        if str(custom.get("symbol") or "").upper() != symbol:
            continue
        price = _finite(custom.get("price"))
        created = _timestamp(custom.get("created_at"))
        expires = _timestamp(custom.get("expires_at")) if custom.get("expires_at") else None
        if price is None or created is None or created > now_et or str(custom.get("session_date") or "") != current_date.isoformat():
            continue
        role = str(custom.get("role") or "two_sided")
        if role not in {"support", "resistance", "two_sided"}:
            continue
        levels.append({
            "name": str(custom.get("name") or "external_custom_level")[:80], "price": round(price, 4),
            "role": role, "source": str(custom.get("source") or "user_supplied")[:120],
            "created_at": created.isoformat(), "expires_at": expires.isoformat() if expires else None,
            "provenance": "typed_external_input_not_formula_inference", "external_unverified": True,
            "expired": bool(expires and expires <= now_et),
        })
    return {
        "symbol": symbol, "status": "available", "daily_as_of": prior["date"].isoformat(),
        "daily_bias": _daily_bias(day_rows), "daily_atr14": round(atr, 4) if atr is not None else None,
        "levels": levels,
        "level_policy": "public_completed_bar_references_plus_typed_external_unverified_input",
        "proprietary_formula_inferred": False,
    }


def classify_lifecycle(level: Mapping[str, Any], bars: list[dict[str, Any]], *, daily_atr: float | None) -> dict[str, Any]:
    """Classify the latest causal three-minute relationship to one level."""
    price = float(level["price"])
    zone = max(price * 0.0004, (daily_atr or price * 0.01) * 0.03)
    watch_distance = max(zone * 3, (daily_atr or price * 0.01) * 0.10)
    late_distance = max(zone * 6, (daily_atr or price * 0.01) * 0.25)
    base = {
        "level_name": level["name"], "level": round(price, 4), "level_role": level["role"],
        "level_source": level["source"], "external_unverified": bool(level.get("external_unverified")),
        "zone": round(zone, 4), "watch_distance": round(watch_distance, 4),
        "execution_enabled": False, "can_submit_orders": False,
    }
    if level.get("expired"):
        return {**base, "state": "INVALIDATED", "direction": "NONE", "reason": "external_level_expired"}
    if not bars:
        return {**base, "state": "DORMANT", "direction": "NONE", "reason": "no_completed_3m_rth_bar"}
    last = bars[-1]
    previous = bars[-2] if len(bars) > 1 else None
    touched_rows = [bar for bar in bars if bar["low"] <= price + zone and bar["high"] >= price - zone]
    touched = bool(touched_rows)
    direction, kind = "NONE", None
    if previous is not None:
        if previous["close"] > price + zone and last["low"] <= price + zone and last["close"] > price + zone:
            direction, kind = "LONG", "held_retest_above"
        elif previous["close"] < price - zone and last["high"] >= price - zone and last["close"] < price - zone:
            direction, kind = "SHORT", "held_retest_below"
        elif previous["close"] < price - zone and last["low"] < price and last["close"] > price + zone:
            direction, kind = "LONG", "completed_reclaim_up"
        elif previous["close"] > price + zone and last["high"] > price and last["close"] < price - zone:
            direction, kind = "SHORT", "completed_reclaim_down"
    if kind is None and last["low"] <= price + zone and last["close"] > price + zone and last["close"] > last["open"] and level["role"] in {"support", "two_sided"}:
        direction, kind = "LONG", "bullish_rejection"
    if kind is None and last["high"] >= price - zone and last["close"] < price - zone and last["close"] < last["open"] and level["role"] in {"resistance", "two_sided"}:
        direction, kind = "SHORT", "bearish_rejection"
    distance = last["close"] - price
    if kind:
        state, reason = "CONFIRMED", kind
    elif touched and level["role"] == "support" and last["close"] < price - zone:
        state, direction, reason = "INVALIDATED", "LONG", "support_closed_below_zone"
    elif touched and level["role"] == "resistance" and last["close"] > price + zone:
        state, direction, reason = "INVALIDATED", "SHORT", "resistance_closed_above_zone"
    elif touched and abs(distance) >= late_distance:
        state, direction, reason = "LATE", "LONG" if distance > 0 else "SHORT", "post_interaction_move_extended"
    elif any(bar["low"] <= price + zone and bar["high"] >= price - zone for bar in bars[-2:]):
        state, direction, reason = "ARMED", "NONE", "level_in_contention_await_completed_confirmation"
    elif abs(distance) <= watch_distance:
        state, direction, reason = "WATCH", "LONG" if distance < 0 else "SHORT", "approaching_mapped_level"
    else:
        state, direction, reason = "DORMANT", "NONE", "outside_approach_window"
    return {
        **base, "state": state, "direction": direction, "reason": reason,
        "last_price": round(last["close"], 4), "distance_points": round(distance, 4),
        "bar_started_at": last["timestamp"].isoformat(), "bar_completed_at": last["completed_at"].isoformat(),
        "bar_basis": "three_consecutive_completed_1m_bars", "touches_today": len(touched_rows),
    }


def evaluate_symbol(level_map: Mapping[str, Any], minute_rows: Iterable[Mapping[str, Any]], *, now_et: datetime) -> dict[str, Any]:
    minute = normalize_minute_rows(minute_rows)
    completed_minute = [row for row in minute if row["timestamp"] + timedelta(minutes=1) <= now_et]
    bars = [
        row for row in completed_three_minute_bars(minute, as_of=now_et)
        if row["timestamp"].date() == now_et.date() and time(9, 30) <= row["timestamp"].time() < time(16)
    ]
    lifecycles = [classify_lifecycle(level, bars, daily_atr=_finite(level_map.get("daily_atr14"))) for level in level_map.get("levels") or []]
    active = [row for row in lifecycles if row["state"] != "DORMANT"]
    latest_3m = bars[-1]["completed_at"] if bars else None
    confirmation_age = (now_et - latest_3m) if latest_3m else None
    confirmation_fresh = confirmation_age is not None and timedelta(0) <= confirmation_age <= MAX_3M_FEED_AGE
    return {
        **dict(level_map), "completed_3m_bar_count": len(bars),
        "last_completed_3m_at": latest_3m.isoformat() if latest_3m else None,
        "confirmation_3m_fresh": confirmation_fresh,
        "confirmation_3m_age_seconds": round(confirmation_age.total_seconds(), 1) if confirmation_age is not None else None,
        "last_completed_1m_price": completed_minute[-1]["close"] if completed_minute else None,
        "last_completed_1m_at": (completed_minute[-1]["timestamp"] + timedelta(minutes=1)).isoformat() if completed_minute else None,
        "lifecycles": lifecycles, "active_lifecycles": active,
    }


def load_custom_levels(path: Path, *, now_et: datetime) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.exists():
        return [], []
    payload = _read_json(path)
    if payload.get("schema_version") != 1 or not isinstance(payload.get("levels"), list):
        return [], ["custom_levels_invalid_schema"]
    required = {"symbol", "name", "price", "role", "session_date", "created_at", "source"}
    levels: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, raw in enumerate(payload["levels"]):
        if not isinstance(raw, dict) or not required.issubset(raw):
            errors.append(f"custom_level_{index}:missing_required_fields")
            continue
        symbol = str(raw.get("symbol") or "").upper()
        role = str(raw.get("role") or "")
        if symbol not in UNIVERSE or role not in {"support", "resistance", "two_sided"} or _finite(raw.get("price")) is None:
            errors.append(f"custom_level_{index}:invalid_symbol_role_or_price")
            continue
        if _timestamp(raw.get("created_at")) is None:
            errors.append(f"custom_level_{index}:invalid_created_at")
            continue
        try:
            date.fromisoformat(str(raw.get("session_date")))
        except ValueError:
            errors.append(f"custom_level_{index}:invalid_session_date")
            continue
        levels.append(raw)
    return levels, errors


def fetch_intraday_1m(symbols: Iterable[str], *, now_et: datetime) -> dict[str, list[dict[str, Any]]]:
    start = datetime.combine(now_et.date() - timedelta(days=1), time(16), ET).astimezone(timezone.utc)
    requested = list(symbols)
    output = {symbol: [] for symbol in requested}
    # Five-symbol chunks remain below Alpaca's 10k multi-symbol page ceiling
    # for one extended-hours session.  This prevents a newly reserved symbol
    # at the end of the list (notably DELL) from being silently truncated.
    for offset in range(0, len(requested), 5):
        chunk = requested[offset:offset + 5]
        response = requests.get(
            "https://data.alpaca.markets/v2/stocks/bars", headers=_credentials(), timeout=20,
            params={
                "symbols": ",".join(chunk), "timeframe": "1Min", "feed": "iex", "adjustment": "all",
                "start": start.isoformat().replace("+00:00", "Z"),
                "end": now_et.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "limit": 10000,
            },
        )
        response.raise_for_status()
        payload = response.json()
        for symbol in chunk:
            output[symbol] = list((payload.get("bars") or {}).get(symbol) or [])
    return output


def build_report(
    *, now_et: datetime | None = None, symbols: Iterable[str] = UNIVERSE,
    daily_frames: Mapping[str, Any] | None = None, minute_frames: Mapping[str, list[dict[str, Any]]] | None = None,
    custom_level_path: Path = CUSTOM_LEVEL_PATH,
) -> dict[str, Any]:
    clock = (now_et or datetime.now(ET)).astimezone(ET)
    requested = [symbol.upper() for symbol in symbols if symbol.upper() in UNIVERSE]
    custom, errors = load_custom_levels(custom_level_path, now_et=clock)
    if minute_frames is None:
        try:
            minute_frames = fetch_intraday_1m(requested, now_et=clock)
        except Exception as exc:
            minute_frames = {}
            errors.append(f"intraday_fetch:{type(exc).__name__}:{str(exc)[:120]}")
    observations: list[dict[str, Any]] = []
    for symbol in requested:
        try:
            daily = daily_frames[symbol] if daily_frames is not None else fetch_ohlcv(symbol, lookback_days=90)
            level_map = build_public_level_map(symbol, daily, minute_frames.get(symbol, []), now_et=clock, custom_levels=custom)
            observations.append(evaluate_symbol(level_map, minute_frames.get(symbol, []), now_et=clock))
        except Exception as exc:
            errors.append(f"{symbol}:{type(exc).__name__}:{str(exc)[:120]}")
            observations.append({"symbol": symbol, "status": "unavailable", "error": str(exc)[:160], "active_lifecycles": []})
    active = [row for observation in observations for row in observation.get("active_lifecycles") or []]
    counts = {state: sum(row.get("state") == state for row in active) for state in sorted(ALERT_STATES)}
    symbol_contracts = [_dashboard_symbol_contract(row) for row in observations]
    available = sum(row.get("status") == "available" for row in observations)
    session_state = "premarket" if time(4) <= clock.time() < time(9, 30) else "rth" if time(9, 30) <= clock.time() < time(16) else "postmarket"
    confirmation_expected = session_state == "rth" and clock.time() >= time(9, 33)
    confirmation_available = sum(int(row.get("completed_3m_bar_count") or 0) > 0 for row in observations)
    confirmation_fresh = sum(row.get("confirmation_3m_fresh") is True for row in observations)
    if not available:
        status = "degraded"
    elif errors or available != len(requested) or (confirmation_expected and confirmation_fresh != available):
        status = "partial"
    else:
        status = "ok"
    return {
        "schema_version": "daily-level-map-shadow-v1", "provider": "daily_level_map_shadow", "date": clock.date().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "as_of_et": clock.isoformat(), "status": status, "session_state": session_state,
        "freshness_sla_seconds": 240, "mode": "shadow_observation_only", "shadow_only": True,
        "universe": requested, "observations": observations, "active_lifecycles": active,
        "symbols": symbol_contracts,
        "state_counts": counts,
        "coverage": {
            "requested": len(requested), "available": available, "errors": len(errors),
            "completed_3m_available": confirmation_available,
            "completed_3m_fresh": confirmation_fresh,
            "completed_3m_expected_now": confirmation_expected,
        },
        "errors": errors, "notification_attempts": 0, "alerts_sent": 0, "notification_failures": 0,
        "custom_level_contract": {
            "schema_version": 1,
            "required_fields": ["symbol", "name", "price", "role", "session_date", "created_at", "source"],
            "label": "external_unverified", "may_infer_proprietary_formula": False,
        },
        "execution_enabled": False, "can_submit_orders": False,
        "warning": "Mapped-level context and completed 3m shadow alerts only. No proprietary magnet/magnitude formula is inferred; no order is placed.",
    }


def _dashboard_symbol_contract(observation: Mapping[str, Any]) -> dict[str, Any]:
    """Expose a compact, typed dashboard seam without weakening raw evidence."""
    symbol = str(observation.get("symbol") or "")
    bias = observation.get("daily_bias") if isinstance(observation.get("daily_bias"), Mapping) else {}
    lifecycles = [row for row in observation.get("lifecycles") or [] if isinstance(row, Mapping)]
    with_price = [row for row in lifecycles if _finite(row.get("distance_points")) is not None]
    nearest = min(with_price, key=lambda row: abs(float(row["distance_points"]))) if with_price else None
    if nearest is None:
        levels = [row for row in observation.get("levels") or [] if _finite(row.get("price")) is not None]
        last_price = _finite(observation.get("last_completed_1m_price"))
        if levels and last_price is not None:
            mapped = min(levels, key=lambda row: abs(float(row["price"]) - last_price))
            return {
                "symbol": symbol, "status": observation.get("status"), "daily_bias": bias.get("state", "UNAVAILABLE"),
                "daily_context": dict(bias),
                "nearest_level": {
                    "price": mapped.get("price"), "type": mapped.get("name"), "role": mapped.get("role"),
                    "source": mapped.get("source"), "provenance": mapped.get("provenance"),
                    "external_unverified": bool(mapped.get("external_unverified")),
                    "distance_points": round(last_price - float(mapped["price"]), 4),
                },
                "confirmation_3m": {
                    "state": "PREMARKET", "direction": "NONE", "reason": "awaiting_first_completed_3m_rth_bar",
                    "trigger": mapped.get("price"), "invalidation": None, "next_target": None,
                    "next_target_type": None, "bar_completed_at": observation.get("last_completed_1m_at"),
                    "observed_at": observation.get("last_completed_1m_at"),
                },
                "execution_enabled": False, "can_submit_orders": False,
            }
        return {
            "symbol": symbol, "status": observation.get("status"), "daily_bias": bias.get("state", "UNAVAILABLE"),
            "daily_context": dict(bias), "nearest_level": None,
            "confirmation_3m": {"state": "UNAVAILABLE", "reason": "no_completed_3m_level_relationship"},
            "execution_enabled": False, "can_submit_orders": False,
        }
    levels = sorted(
        [row for row in observation.get("levels") or [] if _finite(row.get("price")) is not None],
        key=lambda row: float(row["price"]),
    )
    current = float(nearest.get("last_price"))
    direction = str(nearest.get("direction") or "NONE")
    if direction == "LONG":
        next_level = next((row for row in levels if float(row["price"]) > current), None)
        invalidation = float(nearest["level"]) - float(nearest["zone"])
    elif direction == "SHORT":
        next_level = next((row for row in reversed(levels) if float(row["price"]) < current), None)
        invalidation = float(nearest["level"]) + float(nearest["zone"])
    else:
        next_level, invalidation = None, None
    risk = abs(float(nearest["level"]) - invalidation) if invalidation is not None else None
    projected_target = (
        float(nearest["level"]) + (2 * risk) if direction == "LONG" and risk is not None
        else float(nearest["level"]) - (2 * risk) if direction == "SHORT" and risk is not None
        else None
    )
    return {
        "symbol": symbol, "status": observation.get("status"), "daily_bias": bias.get("state", "UNAVAILABLE"),
        "daily_context": dict(bias),
        "nearest_level": {
            "price": nearest.get("level"), "type": nearest.get("level_name"), "role": nearest.get("level_role"),
            "source": nearest.get("level_source"),
            "provenance": "typed_external_input_not_formula_inference" if nearest.get("external_unverified") else "reproducible_public_completed_bar",
            "external_unverified": bool(nearest.get("external_unverified")),
            "distance_points": nearest.get("distance_points"),
        },
        "confirmation_3m": {
            "state": nearest.get("state"), "direction": direction, "reason": nearest.get("reason"),
            "trigger": nearest.get("level"), "invalidation": round(invalidation, 4) if invalidation is not None else None,
            "next_target": round(float(next_level["price"]), 4) if next_level else round(projected_target, 4) if projected_target is not None else None,
            "next_target_type": next_level.get("name") if next_level else "risk_projection_2r" if projected_target is not None else None,
            "bar_completed_at": nearest.get("bar_completed_at"), "observed_at": nearest.get("bar_completed_at"),
        },
        "execution_enabled": False, "can_submit_orders": False,
    }


def _event_id(symbol: str, lifecycle: Mapping[str, Any]) -> str:
    raw = "|".join((symbol, str(lifecycle.get("level_name")), str(lifecycle.get("level")), str(lifecycle.get("state")), str(lifecycle.get("bar_completed_at"))))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def append_candidates(report: Mapping[str, Any], path: Path = EVENT_PATH) -> int:
    seen: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(str(json.loads(line).get("event_id") or ""))
            except json.JSONDecodeError:
                continue
    events: list[dict[str, Any]] = []
    for observation in report.get("observations") or []:
        symbol = str(observation.get("symbol") or "")
        for lifecycle in observation.get("active_lifecycles") or []:
            event_id = _event_id(symbol, lifecycle)
            if event_id in seen:
                continue
            events.append({
                "schema_version": 1, "event_id": event_id, "provider": report.get("provider"),
                "captured_at": report.get("generated_at"), "symbol": symbol,
                "daily_bias": observation.get("daily_bias"), "lifecycle": lifecycle,
                "execution_enabled": False, "can_submit_orders": False,
            })
    if events:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return len(events)


def format_alert(
    symbol: str,
    lifecycle: Mapping[str, Any],
    daily_bias: Mapping[str, Any],
    confirmation: Mapping[str, Any] | None = None,
) -> str:
    plan = confirmation or {}
    return (
        f"**Mapped level {lifecycle.get('state')} | {symbol} {lifecycle.get('direction')}**\n"
        f"Daily bias `{daily_bias.get('state', 'UNAVAILABLE')}` | level `{lifecycle.get('level_name')}` "
        f"`{lifecycle.get('level')}` | last `{lifecycle.get('last_price')}`\n"
        f"Why: `{lifecycle.get('reason')}` | completed `{lifecycle.get('bar_completed_at')}`\n"
        f"Trigger `{plan.get('trigger')}` | invalidation `{plan.get('invalidation')}` | "
        f"target `{plan.get('next_target')}` ({plan.get('next_target_type')})\n"
        f"Source `{lifecycle.get('level_source')}` | external unverified `{lifecycle.get('external_unverified')}`\n"
        "Shadow observation only. Do not chase LATE states. No order placed."
    )


def send_state_change_alerts(
    report: dict[str, Any], *, state_path: Path = STATE_PATH,
    sender: Callable[[str], Mapping[str, Any]] | None = None,
    event_path: Path = DELIVERY_EVENT_PATH,
) -> int:
    """Deliver transitions with the governed retry transport.

    The structured result exposes bounded attempt/error evidence without ever
    persisting the webhook URL.  An undelivered transition is not acknowledged
    and therefore remains eligible for the next scheduled retry.
    """
    transport = sender or governed_shadow_alert.deliver
    previous = _read_json(state_path)
    acknowledged = previous.get("states") if isinstance(previous.get("states"), dict) else {}
    next_states = dict(acknowledged)
    attempts = transitions = delivered = failures = event_log_failures = 0
    error_classes: dict[str, int] = {}
    delivery_results: list[dict[str, Any]] = []
    contracts = {
        str(row.get("symbol") or ""): row
        for row in report.get("symbols") or []
        if isinstance(row, Mapping)
    }
    for observation in report.get("observations") or []:
        symbol = str(observation.get("symbol") or "")
        daily_bias = observation.get("daily_bias") if isinstance(observation.get("daily_bias"), dict) else {}
        contract = contracts.get(symbol) or {}
        selected = contract.get("nearest_level") if isinstance(contract.get("nearest_level"), Mapping) else {}
        confirmation = contract.get("confirmation_3m") if isinstance(contract.get("confirmation_3m"), Mapping) else {}
        # One actionable state transition per symbol prevents the first run from
        # flooding Discord with every historical level relationship.
        lifecycles = [
            row for row in observation.get("lifecycles") or []
            if isinstance(row, Mapping)
            and row.get("level_name") == selected.get("type")
            and row.get("level") == selected.get("price")
        ]
        if not contract:
            lifecycles = [row for row in observation.get("lifecycles") or [] if isinstance(row, Mapping)]
        if int(observation.get("completed_3m_bar_count") or 0) > 0 and observation.get("confirmation_3m_fresh") is not True:
            continue
        for lifecycle in lifecycles:
            key = "|".join((symbol, str(lifecycle.get("level_name")), str(lifecycle.get("level"))))
            current = str(lifecycle.get("state") or "DORMANT")
            prior = acknowledged.get(key)
            if current in DIRECT_ALERT_STATES and current != prior:
                transitions += 1
                result = dict(transport(format_alert(symbol, lifecycle, daily_bias, confirmation)))
                attempt_count = max(0, int(result.get("attempts") or 0))
                attempts += attempt_count
                was_delivered = result.get("delivered") is True
                error_class = str(result.get("error_class") or "") or None
                delivery_results.append({
                    "symbol": symbol, "level_name": lifecycle.get("level_name"), "state": current,
                    "delivered": was_delivered, "attempts": attempt_count, "error_class": error_class,
                })
                event_id = hashlib.sha256(
                    "|".join((key, current, str(lifecycle.get("bar_completed_at") or ""))).encode("utf-8")
                ).hexdigest()
                if not _append_jsonl(event_path, {
                    "event_id": event_id,
                    "attempted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "symbol": symbol,
                    "state": current,
                    "direction": lifecycle.get("direction"),
                    "level_name": lifecycle.get("level_name"),
                    "level": lifecycle.get("level"),
                    "reason": lifecycle.get("reason"),
                    "bar_completed_at": lifecycle.get("bar_completed_at"),
                    "trigger": confirmation.get("trigger"),
                    "stop": confirmation.get("invalidation"),
                    "target": confirmation.get("next_target"),
                    "delivered": was_delivered,
                    "attempts": attempt_count,
                    "error_class": error_class,
                    "execution_enabled": False,
                    "can_submit_orders": False,
                }):
                    event_log_failures += 1
                if was_delivered:
                    delivered += 1
                    next_states[key] = current
                else:
                    failures += 1
                    label = error_class or "unknown_delivery_error"
                    error_classes[label] = error_classes.get(label, 0) + 1
                    # Preserve the prior acknowledgement so this transition retries.
            elif current not in ALERT_STATES:
                next_states[key] = current
    _atomic_json(state_path, {"schema_version": 1, "updated_at": report.get("generated_at"), "states": next_states})
    report["notification_attempts"] = attempts
    report["notification_transitions"] = transitions
    report["alerts_sent"] = delivered
    report["notification_failures"] = failures
    report["pending_delivery"] = failures
    report["notification_error_classes"] = dict(sorted(error_classes.items()))
    report["event_log_failures"] = event_log_failures
    report["notification_results"] = delivery_results
    return delivered


def write_report(report: Mapping[str, Any], path: Path = REPORT_PATH) -> None:
    _atomic_json(path, report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(UNIVERSE))
    parser.add_argument("--custom-level-path", type=Path, default=CUSTOM_LEVEL_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--event-path", type=Path, default=EVENT_PATH)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument("--alert", action="store_true")
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    symbols = [part.strip().upper() for part in args.symbols.split(",") if part.strip()]
    report = build_report(symbols=symbols, custom_level_path=args.custom_level_path)
    report["new_candidate_events"] = append_candidates(report, args.event_path)
    if args.alert:
        send_state_change_alerts(report, state_path=args.state_path)
    write_report(report, args.report_path)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(json.dumps({"coverage": report["coverage"], "state_counts": report["state_counts"], "alerts_sent": report["alerts_sent"]}, sort_keys=True))
    return 0 if report["coverage"]["available"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
