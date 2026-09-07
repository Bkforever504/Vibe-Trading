#!/usr/bin/env python3
"""Read-only streaming opportunity engine for the daily decision dashboard.

The engine consumes quotes and completed bars, evaluates a frozen six-family
setup library, and publishes a compact ranked snapshot.  It has no broker
client, order model, or mutation path into strategy registries/trade ledgers.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.intraday_opportunity_radar import CORE_LIQUID_SYMBOLS, bar_features, fetch_intraday_bars
from scripts.market_data_provider_registry import build_provider_registry
from scripts.market_structure_intelligence import PATTERN_CATALOG, analyze_market_structure
from scripts.priority_focus_universe import PRIORITY_FOCUS_UNIVERSE
from scripts.shadow_alert_intelligence import (
    adaptive_conformal_abstention,
    build_action_deadline,
    diversify_discord_queue,
    event_intensity_challenger,
    market_data_quorum,
    schedule_by_action_deadline,
)
from agent.src.market_data.event_eyes import (
    EventKind,
    EventTimeGuard,
    HotCandidate,
    HotSetSelector,
    LevelDirection,
    LevelStateMachine,
    MarketEvent,
    QuotePersistence,
    SaleConditionPolicy,
    TapeTruthBook,
)


MARKET_TZ = ZoneInfo("America/New_York")
DEFAULT_REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "live-opportunity-engine.json"
DEFAULT_RADAR_PATH = Path.home() / ".vibe-trading" / "reports" / "intraday-opportunity-radar.json"
DEFAULT_CATALYST_PATH = Path.home() / ".vibe-trading" / "reports" / "market-catalyst-calendar.json"
SETUP_FAMILIES = (
    "catalyst_continuation",
    "opening_range_break_retest",
    "vwap_reclaim_pullback",
    "liquidity_sweep_mss_retest",
    "cbc_strong_flip",
    "session_liquidity_sweep_reclaim",
    "ict_cisd_universal_model",
    "relative_weakness_breakdown",
    "failed_breakout_reversal",
)
MAX_QUOTE_AGE_SECONDS = 15.0
MAX_SPREAD_BPS = 35.0
MIN_DOLLAR_LIQUIDITY = 20_000_000.0
MIN_RVOL = 1.25
ESTIMATED_SLIPPAGE_BPS_PER_SIDE = 5.0
MAX_MARKET_RISK_AGE_SECONDS = 20 * 60.0
MAX_COMPLETED_BAR_LAG_SECONDS = 10 * 60.0
MAX_WEBSOCKET_SYMBOLS = 30
REST_QUOTE_REFRESH_SECONDS = 5.0
REST_BAR_REFRESH_SECONDS = 60.0
HOT_SET_REBALANCE_SECONDS = 30.0
NYSE_HOLIDAYS_2026 = frozenset({
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
})
NYSE_EARLY_CLOSES_2026 = frozenset({"2026-11-27", "2026-12-24"})


def _with_core_context_symbols(symbols: list[str]) -> list[str]:
    """Reserve every canonical liquid leader before filling the broker cap."""
    normalized = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
    return list(dict.fromkeys([*CORE_LIQUID_SYMBOLS, *PRIORITY_FOCUS_UNIVERSE, *normalized]))[:100]


def _hybrid_symbol_partition(symbols: list[str]) -> tuple[list[str], list[str]]:
    """Put the highest-priority names on WebSocket and retain full REST coverage."""
    normalized = list(dict.fromkeys(
        str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()
    ))[:100]
    return normalized[:MAX_WEBSOCKET_SYMBOLS], normalized[MAX_WEBSOCKET_SYMBOLS:]


def _event_time_symbol_partition(
    engine: "LiveOpportunityEngine", symbols: list[str], *, now: datetime | None = None,
) -> tuple[list[str], list[str]]:
    """Allocate scarce socket slots to reserved and near-trigger symbols."""
    snapshot = engine.snapshot(now=now)
    hot = snapshot.get("event_time_intelligence", {}).get("hot_set", {}).get("symbols") or []
    normalized = list(dict.fromkeys([
        *(str(symbol).upper() for symbol in hot),
        *(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()),
    ]))[:100]
    return normalized[:MAX_WEBSOCKET_SYMBOLS], normalized[MAX_WEBSOCKET_SYMBOLS:]


def _stream_coverage(
    websocket_symbols: list[str],
    rest_symbols: list[str],
    *,
    rest_quote_status: str,
    rest_bar_status: str,
) -> dict[str, Any]:
    mandatory = list(CORE_LIQUID_SYMBOLS)
    return {
        "architecture": "hybrid_websocket_plus_rest",
        "websocket_symbol_limit": MAX_WEBSOCKET_SYMBOLS,
        "websocket_symbols": websocket_symbols,
        "websocket_symbol_count": len(websocket_symbols),
        "rest_symbols": rest_symbols,
        "rest_symbol_count": len(rest_symbols),
        "total_symbol_count": len(websocket_symbols) + len(rest_symbols),
        "mandatory_core_symbols": mandatory,
        "mandatory_core_on_websocket": [symbol for symbol in mandatory if symbol in websocket_symbols],
        "mandatory_core_missing": [
            symbol for symbol in mandatory
            if symbol not in websocket_symbols and symbol not in rest_symbols
        ],
        "rest_quote_status": rest_quote_status,
        "rest_bar_status": rest_bar_status,
        "source_labels": ["alpaca_iex_websocket", "alpaca_iex_rest"],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _validation_snapshot(root: Path) -> dict[str, Any]:
    intelligence = _read_json(root / "data" / "opportunity_intelligence_report.json")
    return {
        "promotion_authority": intelligence.get("promotion_authority", "blocked"),
        "strategy_lifecycle": intelligence.get("strategy_lifecycle") or {},
        "configuration_fingerprint": intelligence.get("configuration_fingerprint") or {},
        "status": "evidence_available" if intelligence else "collecting_forward_shadow_evidence",
        "warning": "Live candidates cannot promote a strategy or authorize execution.",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_feed_provenance(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = env if env is not None else os.environ
    requested = str(values.get("VIBE_TRADING_STOCK_FEED") or "iex").strip().lower()
    feed = requested if requested in {"iex", "sip"} else "iex"
    return {
        "provider": "alpaca",
        "feed": feed,
        "transport": "websocket",
        "endpoint": f"wss://stream.data.alpaca.markets/v2/{feed}",
        "entitlement": "configured_not_verified",
        "label": f"alpaca_{feed}_stock_stream",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _session_progress(now: datetime) -> float:
    current = now.astimezone(MARKET_TZ)
    start = datetime.combine(current.date(), wall_time(9, 30), MARKET_TZ)
    end = datetime.combine(current.date(), wall_time(16, 0), MARKET_TZ)
    if current <= start:
        return 0.03
    if current >= end:
        return 1.0
    return max(0.03, (current - start).total_seconds() / (end - start).total_seconds())


def _grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def _quote_context(quote: dict[str, Any], now: datetime) -> dict[str, Any]:
    bid = _finite(quote.get("bid") if "bid" in quote else quote.get("bp"))
    ask = _finite(quote.get("ask") if "ask" in quote else quote.get("ap"))
    bid_size = _finite(quote.get("bid_size") if "bid_size" in quote else quote.get("bs"))
    ask_size = _finite(quote.get("ask_size") if "ask_size" in quote else quote.get("as"))
    stamp = _utc(quote.get("timestamp") or quote.get("t"))
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        market_state = "invalid_or_missing"
    elif bid > ask:
        market_state = "crossed"
    elif bid == ask:
        market_state = "locked"
    else:
        market_state = "two_sided"
    midpoint = (bid + ask) / 2 if market_state in {"two_sided", "locked"} else None
    spread_bps = (ask - bid) / midpoint * 10_000 if midpoint and bid is not None and ask is not None else None
    age = max(0.0, (now - stamp).total_seconds()) if stamp else None
    freshness = "live" if age is not None and age <= 5 else "recent" if age is not None and age <= MAX_QUOTE_AGE_SECONDS else "stale" if stamp else "missing"
    depth_total = (bid_size or 0.0) + (ask_size or 0.0)
    depth_imbalance = (bid_size - ask_size) / depth_total if bid_size is not None and ask_size is not None and depth_total > 0 else None
    return {
        "bid": bid,
        "ask": ask,
        "bid_size": bid_size,
        "ask_size": ask_size,
        "midpoint": round(midpoint, 4) if midpoint is not None else None,
        "spread_bps": round(spread_bps, 2) if spread_bps is not None else None,
        "market_state": market_state,
        "depth_imbalance": round(depth_imbalance, 4) if depth_imbalance is not None else None,
        "depth_imbalance_status": "advisory_only_not_order_flow" if depth_imbalance is not None else "unavailable",
        "timestamp": stamp.isoformat().replace("+00:00", "Z") if stamp else None,
        "age_seconds": round(age, 2) if age is not None else None,
        "freshness": freshness,
        "source_label": "alpaca_latest_quote",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _session_risk_context(now: datetime) -> dict[str, Any]:
    """Classify manual-entry timing against the frozen official 2026 NYSE calendar."""
    current = now.astimezone(MARKET_TZ)
    minute = current.hour * 60 + current.minute
    day = current.date().isoformat()
    weekday = current.weekday() < 5
    scheduled_close = 13 * 60 if day in NYSE_EARLY_CLOSES_2026 else 16 * 60
    calendar_covered = current.year == 2026
    if day in NYSE_HOLIDAYS_2026:
        phase, hard_veto = "exchange_holiday", True
    elif not calendar_covered:
        phase, hard_veto = "calendar_coverage_unavailable", True
    elif not weekday or minute < 9 * 60 + 30 or minute >= scheduled_close:
        phase, hard_veto = "outside_regular_session", True
    elif minute < 9 * 60 + 35:
        phase, hard_veto = "opening_auction_buffer", True
    elif minute >= scheduled_close - 10:
        phase, hard_veto = "closing_auction_buffer", True
    elif minute < 11 * 60 + 30:
        phase, hard_veto = "morning_session", False
    elif minute < 14 * 60:
        phase, hard_veto = "midday_session", False
    else:
        phase, hard_veto = "afternoon_session", False
    return {
        "phase": phase,
        "status": "stand_aside" if hard_veto else "eligible_for_review",
        "hard_veto": hard_veto,
        "reason": "Opening/closing auction buffers and times outside regular hours are not eligible for new manual entries." if hard_veto else "Regular-session timing gate is open; all other setup gates still apply.",
        "calendar_status": "official_2026_calendar_frozen" if calendar_covered else "unsupported_year_fail_closed",
        "scheduled_close_et": f"{scheduled_close // 60:02d}:{scheduled_close % 60:02d}",
        "source_label": "nyse_2026_hours_calendar_plus_entry_buffer_policy_v1",
        "evaluated_at": now.isoformat().replace("+00:00", "Z"),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _market_risk_context(report: dict[str, Any], *, now: datetime, required: bool) -> dict[str, Any]:
    generated = _utc(report.get("generated_at"))
    age = max(0.0, (now - generated).total_seconds()) if generated else None
    today = report.get("today") if isinstance(report.get("today"), dict) else {}
    current = now.astimezone(MARKET_TZ)
    report_day = str(today.get("date") or "")
    blockers: list[str] = []
    if not report:
        status = "missing"
        if required:
            blockers.append("market_risk_context_missing")
    elif report_day and report_day != current.date().isoformat():
        status = "wrong_session"
        if required:
            blockers.append("market_risk_context_wrong_session")
    elif age is None or age > MAX_MARKET_RISK_AGE_SECONDS:
        status = "stale"
        if required:
            blockers.append("market_risk_context_stale")
    else:
        status = "available"
    dynamic = today.get("dynamic_risk") if isinstance(today.get("dynamic_risk"), dict) else {}
    allowed = [str(value) for value in today.get("allowed_playbooks") or []]
    vetoes = [str(value) for value in today.get("vetoes") or []]
    active_windows: list[dict[str, Any]] = []
    for window in today.get("caution_windows") or []:
        if not isinstance(window, dict):
            continue
        try:
            start_hour, start_minute = (int(value) for value in str(window.get("start_et")).split(":", 1))
            end_hour, end_minute = (int(value) for value in str(window.get("end_et")).split(":", 1))
        except (TypeError, ValueError):
            continue
        current_minute = current.hour * 60 + current.minute
        if start_hour * 60 + start_minute <= current_minute <= end_hour * 60 + end_minute:
            active_windows.append(dict(window))
    explicit_stand_aside = (
        allowed == ["stand_aside"]
        or str(dynamic.get("recommended_posture") or "").lower() == "stand_aside"
    )
    hard_veto = bool(blockers) or (status == "available" and explicit_stand_aside)
    if status == "available" and explicit_stand_aside:
        status = "stand_aside"
        blockers.append("market_risk_stand_aside")
    macro_event_window = bool(active_windows) or (status == "stand_aside" and str(today.get("max_impact") or "").lower() == "high")
    return {
        "status": status,
        "required": required,
        "hard_veto": hard_veto,
        "macro_event_window": macro_event_window,
        "max_impact": today.get("max_impact") or "unknown",
        "allowed_playbooks": allowed,
        "vetoes": vetoes,
        "active_caution_windows": active_windows,
        "dynamic_risk": dynamic,
        "blockers": blockers,
        "generated_at": generated.isoformat().replace("+00:00", "Z") if generated else None,
        "age_seconds": round(age, 1) if age is not None else None,
        "source_label": str(report.get("provider") or "market_catalyst_calendar"),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _data_quality_context(
    rows: list[dict[str, Any]],
    quote: dict[str, Any],
    *,
    now: datetime,
    consolidated_quote: bool = True,
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    stamps = [_utc(row.get("t") or row.get("timestamp")) for row in rows]
    valid_stamps = [stamp for stamp in stamps if stamp is not None]
    if quote.get("market_state") == "crossed":
        blockers.append("crossed_quote")
    elif quote.get("market_state") == "invalid_or_missing":
        blockers.append("invalid_or_missing_quote")
    elif quote.get("market_state") == "locked":
        warnings.append("locked_quote")
    malformed = any(
        (high := _finite(row.get("h") if "h" in row else row.get("high"))) is None
        or (low := _finite(row.get("l") if "l" in row else row.get("low"))) is None
        or (open_price := _finite(row.get("o") if "o" in row else row.get("open"))) is None
        or (close := _finite(row.get("c") if "c" in row else row.get("close"))) is None
        or high < max(open_price, close, low)
        or low > min(open_price, close, high)
        for row in rows
    )
    if malformed:
        blockers.append("malformed_ohlc")
    if len(valid_stamps) != len(set(valid_stamps)):
        blockers.append("duplicate_bar_timestamps")
    if valid_stamps != sorted(valid_stamps):
        blockers.append("out_of_order_bars")
    if any(stamp > now + timedelta(seconds=30) for stamp in valid_stamps):
        blockers.append("future_dated_bars")
    session = _session_risk_context(now)
    latest = max(valid_stamps, default=None)
    completed_at = latest + timedelta(minutes=5) if latest else None
    lag = max(0.0, (now - completed_at).total_seconds()) if completed_at else None
    if not session["hard_veto"] and (lag is None or lag > MAX_COMPLETED_BAR_LAG_SECONDS):
        blockers.append("stale_primary_bars")
    recent = sorted(stamp for stamp in valid_stamps if stamp.astimezone(MARKET_TZ).date() == now.astimezone(MARKET_TZ).date())[-24:]
    missing_intervals = sum(1 for left, right in zip(recent, recent[1:]) if (right - left).total_seconds() > 5 * 60 + 30)
    if missing_intervals:
        warnings.append("missing_intraday_bar_intervals")
    if not consolidated_quote:
        warnings.append("consolidated_nbbo_unavailable")
    status = "blocked" if blockers else "degraded" if warnings else "pass"
    return {
        "status": status,
        "blockers": list(dict.fromkeys(blockers)),
        "warnings": list(dict.fromkeys(warnings)),
        "bar_count": len(rows),
        "latest_completed_bar_at": completed_at.isoformat().replace("+00:00", "Z") if completed_at else None,
        "completed_bar_lag_seconds": round(lag, 1) if lag is not None else None,
        "missing_intraday_intervals": missing_intervals,
        "quote_scope": "consolidated_sip" if consolidated_quote else "single_venue_iex_not_nbbo",
        "source_labels": ["completed_5m_bar_integrity_v1", "alpaca_latest_quote_integrity_v1"],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _bars_normalized(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        mapped = {
            "t": row.get("t") or row.get("timestamp"),
            "o": _finite(row.get("o") if "o" in row else row.get("open")),
            "h": _finite(row.get("h") if "h" in row else row.get("high")),
            "l": _finite(row.get("l") if "l" in row else row.get("low")),
            "c": _finite(row.get("c") if "c" in row else row.get("close")),
            "v": _finite(row.get("v") if "v" in row else row.get("volume")),
        }
        if all(mapped[key] is not None for key in ("o", "h", "l", "c", "v")):
            output.append(mapped)
    return output


def _aggregate_rth_hourly(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build 09:30-anchored RTH hours from completed 30-minute bars."""
    buckets: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(_bars_normalized(rows), key=lambda value: str(value.get("t") or "")):
        stamp = _utc(row.get("t"))
        if stamp is None:
            continue
        local = stamp.astimezone(MARKET_TZ)
        minute_of_day = local.hour * 60 + local.minute
        if minute_of_day < 9 * 60 + 30 or minute_of_day >= 16 * 60:
            continue
        elapsed = minute_of_day - (9 * 60 + 30)
        bucket_index = min(6, elapsed // 60)
        buckets[(local.date().isoformat(), bucket_index)].append(row)
    output: list[dict[str, Any]] = []
    for key in sorted(buckets):
        group = buckets[key]
        output.append({
            "t": group[0].get("t"),
            "o": float(group[0]["o"]),
            "h": max(float(row["h"]) for row in group),
            "l": min(float(row["l"]) for row in group),
            "c": float(group[-1]["c"]),
            "v": sum(float(row["v"]) for row in group),
        })
    return output


def _aggregate_rth_four_hour(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate only complete eight-bar RTH blocks from completed 30m bars."""
    buckets: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(_bars_normalized(rows), key=lambda value: str(value.get("t") or "")):
        stamp = _utc(row.get("t"))
        if stamp is None:
            continue
        local = stamp.astimezone(MARKET_TZ)
        minute_of_day = local.hour * 60 + local.minute
        if minute_of_day < 9 * 60 + 30 or minute_of_day >= 16 * 60:
            continue
        elapsed = minute_of_day - (9 * 60 + 30)
        buckets[(local.date().isoformat(), elapsed // 240)].append(row)
    output: list[dict[str, Any]] = []
    for key in sorted(buckets):
        group = buckets[key]
        if len(group) != 8:
            continue
        output.append({
            "t": group[0].get("t"),
            "o": float(group[0]["o"]),
            "h": max(float(row["h"]) for row in group),
            "l": min(float(row["l"]) for row in group),
            "c": float(group[-1]["c"]),
            "v": sum(float(row["v"]) for row in group),
        })
    return output


def _filter_completed_period_bars(
    rows: list[dict[str, Any]], *, timeframe: str, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Exclude the still-forming daily or weekly Alpaca aggregate."""
    current = (now or datetime.now(timezone.utc)).astimezone(MARKET_TZ)
    output: list[dict[str, Any]] = []
    for row in sorted(_bars_normalized(rows), key=lambda value: str(value.get("t") or "")):
        stamp = _utc(row.get("t"))
        if stamp is None:
            continue
        local_date = stamp.astimezone(MARKET_TZ).date()
        if timeframe == "1Day" and local_date < current.date():
            output.append(row)
        elif timeframe == "1Week" and local_date.isocalendar()[:2] < current.date().isocalendar()[:2]:
            output.append(row)
    return output


def _context_source_labels(higher_timeframes: Mapping[str, list[dict[str, Any]]] | None) -> list[str]:
    aliases = {"1h": "60m", "4hour": "4h", "1day": "1d", "1week": "1w"}
    labels: list[str] = []
    for name, rows in (higher_timeframes or {}).items():
        if not rows:
            continue
        normalized = aliases.get(str(name).strip().lower(), str(name).strip().lower())
        labels.append(f"completed_{normalized}_bars")
    return list(dict.fromkeys(labels))


def _detect_families(
    rows: list[dict[str, Any]],
    features: dict[str, Any],
    *,
    catalyst: dict[str, Any] | None,
    relative_strength: float | None,
) -> list[tuple[str, str, str]]:
    """Return frozen setup-family detections as (family, direction, reason)."""
    if len(rows) < 4 or features.get("status") != "ok":
        return []
    last, prior = rows[-1], rows[-2]
    close = float(last["c"])
    vwap = _finite(features.get("vwap_proxy"))
    opening_high = _finite(features.get("opening_range_high"))
    opening_low = _finite(features.get("opening_range_low"))
    detections: list[tuple[str, str, str]] = []

    if catalyst and vwap is not None:
        direction = "bullish" if close > vwap else "bearish"
        detections.append(("catalyst_continuation", direction, "fresh catalyst with price holding on one side of VWAP"))
    pattern = str(features.get("price_action_pattern") or "")
    if pattern in {"breakout_retest_hold", "breakout_close"}:
        detections.append(("opening_range_break_retest", "bullish", f"completed-bar {pattern}"))
    elif pattern in {"breakdown_retest_reject", "breakdown_close"}:
        detections.append(("opening_range_break_retest", "bearish", f"completed-bar {pattern}"))

    if vwap is not None:
        if float(prior["c"]) <= vwap < close and close > float(last["o"]):
            detections.append(("vwap_reclaim_pullback", "bullish", "completed bar reclaimed VWAP"))
        elif float(prior["c"]) >= vwap > close and close < float(last["o"]):
            detections.append(("vwap_reclaim_pullback", "bearish", "completed bar rejected VWAP"))

    lookback = rows[-6:-1]
    if lookback:
        prior_low = min(float(row["l"]) for row in lookback)
        prior_high = max(float(row["h"]) for row in lookback)
        if float(last["l"]) < prior_low and close > prior_low and close > float(last["o"]):
            detections.append(("liquidity_sweep_mss_retest", "bullish", "sell-side sweep closed back above the swept low"))
        elif float(last["h"]) > prior_high and close < prior_high and close < float(last["o"]):
            detections.append(("liquidity_sweep_mss_retest", "bearish", "buy-side sweep closed back below the swept high"))

    if relative_strength is not None and relative_strength <= -0.012 and vwap is not None and close < vwap:
        detections.append(("relative_weakness_breakdown", "bearish", "underperformed benchmark and sector while below VWAP"))

    if opening_high is not None and float(prior["h"]) > opening_high and close < opening_high:
        detections.append(("failed_breakout_reversal", "bearish", "prior breakout failed back inside the opening range"))
    elif opening_low is not None and float(prior["l"]) < opening_low and close > opening_low:
        detections.append(("failed_breakout_reversal", "bullish", "prior breakdown failed back inside the opening range"))

    seen: set[str] = set()
    return [row for row in detections if not (row[0] in seen or seen.add(row[0]))]


def _geometry(
    direction: str,
    quote: dict[str, Any],
    features: dict[str, Any],
    last_bar: dict[str, Any],
) -> dict[str, Any]:
    bid, ask = _finite(quote.get("bid")), _finite(quote.get("ask"))
    vwap = _finite(features.get("vwap_proxy"))
    if direction == "bullish":
        entry = ask
        stops = [value for value in (vwap, _finite(last_bar.get("l"))) if value is not None and entry is not None and value < entry]
        invalidation = max(stops) if stops else None
        raw_risk = entry - invalidation if entry is not None and invalidation is not None else None
        target = entry + 2.0 * raw_risk if raw_risk and raw_risk > 0 else None
    else:
        entry = bid
        stops = [value for value in (vwap, _finite(last_bar.get("h"))) if value is not None and entry is not None and value > entry]
        invalidation = min(stops) if stops else None
        raw_risk = invalidation - entry if entry is not None and invalidation is not None else None
        target = entry - 2.0 * raw_risk if raw_risk and raw_risk > 0 else None
    friction = (entry or 0.0) * ESTIMATED_SLIPPAGE_BPS_PER_SIDE * 2 / 10_000
    reward = abs(target - entry) - friction if target is not None and entry is not None else None
    cost_risk = (raw_risk + friction) if raw_risk is not None else None
    rr = reward / cost_risk if reward is not None and cost_risk and reward > 0 else None
    return {
        "entry": round(entry, 4) if entry is not None else None,
        "invalidation": round(invalidation, 4) if invalidation is not None else None,
        "targets": [{"name": "target_2r", "price": round(target, 4)}] if target is not None else [],
        "raw_risk_per_share": round(raw_risk, 4) if raw_risk is not None else None,
        "estimated_round_trip_friction": round(friction, 4) if entry is not None else None,
        "reward_risk_after_friction": round(rr, 3) if rr is not None else None,
    }


class LiveOpportunityEngine:
    """In-memory evaluator. Network transport is intentionally separate."""

    def __init__(self, *, feed: str = "iex", risk_report_path: Path | None = None) -> None:
        self.feed = feed if feed in {"iex", "sip"} else "iex"
        self.transport = "websocket"
        self.risk_report_path = risk_report_path
        self._symbols: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._event_guard = EventTimeGuard()
        self._sale_conditions = SaleConditionPolicy()
        self._quote_persistence = QuotePersistence()
        self._tape_truth = TapeTruthBook()
        self._level_machines: dict[tuple[str, str], LevelStateMachine] = {}
        self._event_audit: deque[dict[str, Any]] = deque(maxlen=1000)
        self._event_lifecycle: deque[dict[str, Any]] = deque(maxlen=1000)
        self._headsup_pairs: set[str] = set()
        self._event_rate_windows: dict[str, deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=120))

    def _record_event_rate(self, event: MarketEvent) -> None:
        bucket = int(event.event_ts.timestamp()) // 10
        windows = self._event_rate_windows[event.symbol]
        if not windows or windows[-1]["bucket"] != bucket:
            windows.append({"bucket": bucket, "quote_changes": 0, "cancels": 0, "price_ticks": 0})
        row = windows[-1]
        if event.kind == EventKind.QUOTE:
            row["quote_changes"] += 1
        elif event.kind == EventKind.TRADE:
            # Stock feeds do not supply aggressor side. Keep this as a neutral
            # price-tick channel rather than inventing aggressive flow.
            row["price_ticks"] += 1
        elif event.kind in {EventKind.CORRECTION, EventKind.CANCEL_ERROR}:
            row["cancels"] += 1

    def _event_intensity_card(self, symbol: str, *, now: datetime) -> dict[str, Any]:
        current_bucket = int(now.timestamp()) // 10
        completed = [row for row in self._event_rate_windows.get(symbol, ()) if row["bucket"] < current_bucket]
        if len(completed) < 4:
            return event_intensity_challenger({}, {}, persistence_windows=0)
        baseline_rows, recent_rows = completed[:-2], completed[-2:]
        if not baseline_rows:
            return event_intensity_challenger({}, {}, persistence_windows=0)
        channels = ("quote_changes", "cancels", "price_ticks")
        baseline = {name: sum(float(row[name]) for row in baseline_rows) / len(baseline_rows) for name in channels}
        persistence = 0
        for row in reversed(recent_rows):
            ratios = [float(row[name]) / baseline[name] for name in channels if baseline[name] > 0]
            if sum(value >= 2.0 for value in ratios) >= 2:
                persistence += 1
            else:
                break
        return event_intensity_challenger(recent_rows[-1], baseline, persistence_windows=persistence)

    def seed_symbol(
        self,
        symbol: str,
        *,
        bars: list[dict[str, Any]],
        quote: dict[str, Any],
        higher_timeframes: Mapping[str, list[dict[str, Any]]] | None = None,
        average_dollar_volume: float | None = None,
        catalyst: dict[str, Any] | None = None,
        benchmark_return: float | None = None,
        sector_return: float | None = None,
        previous_close: float | None = None,
        mapped_levels: Mapping[str, Any] | None = None,
        mapped_setup_family: str | None = None,
        mapped_direction: str | None = None,
    ) -> None:
        with self._lock:
            self._symbols[symbol.strip().upper()] = {
                "bars": _bars_normalized(bars)[-120:],
                "quote": dict(quote),
                "higher_timeframes": {
                    str(name): _bars_normalized(list(frame_rows))[-120:]
                    for name, frame_rows in (higher_timeframes or {}).items()
                    if frame_rows
                },
                "average_dollar_volume": _finite(average_dollar_volume),
                "catalyst": dict(catalyst) if catalyst else None,
                "benchmark_return": _finite(benchmark_return),
                "sector_return": _finite(sector_return),
                "previous_close": _finite(previous_close),
            }
            level = _finite((mapped_levels or {}).get("confirmation_trigger"))
            direction = str(mapped_direction or "").lower()
            family = str(mapped_setup_family or "").strip()
            if level is not None and family and direction in {"bullish", "long", "bearish", "short"}:
                self._level_machines[(symbol.strip().upper(), family)] = LevelStateMachine(
                    symbol=symbol,
                    level=level,
                    direction=LevelDirection.LONG if direction in {"bullish", "long"} else LevelDirection.SHORT,
                )

    def update_quote(self, symbol: str, quote: dict[str, Any]) -> None:
        with self._lock:
            state = self._symbols.setdefault(symbol.upper(), {"bars": []})
            state["quote"] = dict(quote)

    def update_market_event(self, event: MarketEvent, *, now: datetime | None = None) -> dict[str, Any]:
        """Record event-time evidence without changing completed-bar authority."""
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        integrity = self._event_guard.evaluate(event, now=current)
        with self._lock:
            state = self._symbols.setdefault(event.symbol, {"quote": {}, "bars": []})
            if integrity.get("accepted"):
                self._record_event_rate(event)
            tape = state.setdefault("event_time_shadow", {})
            tape["last_integrity"] = integrity
            tape["last_event_kind"] = event.kind.value
            tape["last_event_at"] = event.event_ts.isoformat().replace("+00:00", "Z")
            tape["provider_received_at"] = event.received_ts.isoformat().replace("+00:00", "Z")
            tape["processed_at"] = current.isoformat().replace("+00:00", "Z")
            tape["tape_truth"] = self._tape_truth.apply(
                event, integrity_accepted=bool(integrity.get("accepted"))
            )
            # These are current-event/persistent-tradability observations, not
            # an ever-growing latch. Historical revisions remain append-only in
            # their own audit field while a later clean quote can clear a
            # transient stale/unknown observation.
            shadow_vetoes: set[str] = set()
            price_forming = bool(integrity.get("accepted"))
            if not integrity.get("accepted"):
                shadow_vetoes.add("event_integrity_rejected")
            if event.kind == EventKind.TRADE:
                sale = self._sale_conditions.evaluate(event)
                tape["sale_condition"] = sale
                if not sale.get("eligible"):
                    shadow_vetoes.add(str(sale.get("reason") or "trade_condition_unavailable"))
                    price_forming = False
            elif event.kind == EventKind.QUOTE:
                observations = state.setdefault("feed_quote_observations", {})
                observations[event.source] = {
                    "source": event.source, "bid": event.bid, "ask": event.ask,
                    "event_at": event.event_ts.isoformat().replace("+00:00", "Z"),
                }
                tape["feed_quorum"] = market_data_quorum(observations.values(), as_of=current)
                if tape["feed_quorum"].get("status") == "data_disagreement":
                    shadow_vetoes.add("market_data_disagreement")
                persistence = self._quote_persistence.observe(event, integrity_accepted=bool(integrity.get("accepted")))
                tape["quote_persistence"] = persistence
                if persistence.get("state") == "LIQUIDITY_VACUUM":
                    tape["liquidity_state"] = "LIQUIDITY_VACUUM"
            elif event.kind in {EventKind.CORRECTION, EventKind.CANCEL_ERROR, EventKind.UPDATED_BAR}:
                tape["source_revision"] = {
                    "status": "observed",
                    "kind": event.kind.value,
                    "event_at": tape["last_event_at"],
                    "original_sequence": event.original_sequence,
                    "history_policy": "append_only_never_rewrite_delivered_alert",
                }
                shadow_vetoes.add("source_revised_or_cancelled")
            elif event.kind == EventKind.STATUS:
                tape["trading_status"] = event.status_code
                tape["trading_status_reason"] = event.reason_code
                truth_reason = tape["tape_truth"].get("reason")
                if truth_reason in {"halt_or_pause", "unknown_status_code"}:
                    shadow_vetoes.add(str(truth_reason))
            elif event.kind == EventKind.LULD:
                price = event.price
                distance = None
                if price and event.lower_band and event.upper_band:
                    distance = min(abs(price - event.lower_band), abs(event.upper_band - price)) / price * 10_000
                tape["luld"] = {
                    "lower_band": event.lower_band,
                    "upper_band": event.upper_band,
                    "distance_bps": round(distance, 4) if distance is not None else None,
                    "event_at": tape["last_event_at"],
                }
                if distance is None or distance <= 10:
                    shadow_vetoes.add("near_or_unknown_luld_band")
            if price_forming and event.kind in {EventKind.TRADE, EventKind.QUOTE}:
                observed_price = event.price if event.kind == EventKind.TRADE else ((event.bid or 0) + (event.ask or 0)) / 2 or None
                tape["tradability"] = self._tape_truth.tradability(
                    symbol=event.symbol,
                    price=observed_price,
                    as_of=event.event_ts,
                )
                shadow_vetoes.update(str(reason) for reason in tape["tradability"].get("reasons") or [])
                for (symbol, _family), machine in list(self._level_machines.items()):
                    if symbol == event.symbol:
                        level_state = machine.observe(price=observed_price, event_ts=event.event_ts)
                        tape["level_state"] = level_state
                        quote_ready = bool((tape.get("quote_persistence") or {}).get("quote_persistent"))
                        heads_up = level_state.get("state") == "HOLDING" and quote_ready and not shadow_vetoes
                        pair_id = f"{event.event_ts.date().isoformat()}:{event.symbol}:{_family}"
                        newly_ready = heads_up and pair_id not in self._headsup_pairs
                        if level_state.get("transition") or newly_ready:
                            if newly_ready:
                                self._headsup_pairs.add(pair_id)
                            self._event_lifecycle.append({
                                "pair_id": pair_id,
                                "symbol": event.symbol,
                                "setup_family": _family,
                                "state": "SHADOW_HEADS_UP" if heads_up else level_state.get("state"),
                                "level_transition": level_state.get("transition"),
                                "event_at": tape["last_event_at"],
                                "provider_received_at": tape["provider_received_at"],
                                "processed_at": tape["processed_at"],
                                "quote_persistent": quote_ready,
                                "shadow_vetoes": sorted(shadow_vetoes),
                                "paired_bar_lane": "awaiting_completed_5m_candidate",
                                "notification_authority": "dashboard_shadow_only",
                                "execution_enabled": False,
                                "can_submit_orders": False,
                            })
            tape["shadow_vetoes"] = sorted(shadow_vetoes)
            tape["execution_enabled"] = False
            tape["can_submit_orders"] = False
            self._event_audit.append({
                "symbol": event.symbol,
                "kind": event.kind.value,
                "event_at": tape["last_event_at"],
                "provider_received_at": tape["provider_received_at"],
                "processed_at": tape["processed_at"],
                "integrity_accepted": bool(integrity.get("accepted")),
                "transport_latency_ms": integrity.get("transport_latency_ms"),
                "shadow_vetoes": list(tape["shadow_vetoes"]),
                "execution_enabled": False,
                "can_submit_orders": False,
            })
            return dict(tape)

    def update_completed_bar(self, symbol: str, bar: dict[str, Any]) -> None:
        normalized = _bars_normalized([bar])
        if not normalized:
            return
        with self._lock:
            state = self._symbols.setdefault(symbol.upper(), {"quote": {}, "bars": []})
            rows = state.setdefault("bars", [])
            stamp = normalized[0].get("t")
            rows[:] = [row for row in rows if row.get("t") != stamp]
            rows.append(normalized[0])
            rows.sort(key=lambda row: str(row.get("t") or ""))
            del rows[:-120]

    def update_higher_timeframes(
        self,
        symbol: str,
        higher_timeframes: Mapping[str, list[dict[str, Any]]],
        *,
        refreshed_at: str | None = None,
    ) -> None:
        """Replace completed HTF context without disturbing live 5m state."""
        with self._lock:
            state = self._symbols.setdefault(symbol.upper(), {"quote": {}, "bars": []})
            current = state.setdefault("higher_timeframes", {})
            for name, frame_rows in higher_timeframes.items():
                normalized = _bars_normalized(list(frame_rows))[-120:]
                if normalized:
                    current[str(name)] = normalized
            state["higher_timeframes_refreshed_at"] = refreshed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _correlated_bars_for(self, symbol: str) -> dict[str, list[dict[str, Any]]]:
        peer = {"QQQ": "SPY", "SPY": "QQQ"}.get(symbol.upper())
        if not peer:
            return {}
        rows = _bars_normalized((self._symbols.get(peer) or {}).get("bars") or [])
        return {peer: rows} if rows else {}

    def _candidates_for(
        self,
        symbol: str,
        state: dict[str, Any],
        now: datetime,
        *,
        market_risk: dict[str, Any],
        session_risk: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows = _bars_normalized(state.get("bars") or [])
        if len(rows) < 3:
            return []
        features = bar_features(rows)
        quote = _quote_context(state.get("quote") or {}, now)
        data_quality = _data_quality_context(rows, quote, now=now, consolidated_quote=self.feed == "sip")
        previous_close = _finite(state.get("previous_close"))
        last_close = _finite(rows[-1].get("c"))
        stock_return = last_close / previous_close - 1 if last_close is not None and previous_close else None
        benchmark = _finite(state.get("benchmark_return")) or 0.0
        sector = _finite(state.get("sector_return")) or 0.0
        relative_strength = stock_return - 0.5 * (benchmark + sector) if stock_return is not None else None
        session_dollar = sum(float(row["c"]) * float(row["v"]) for row in rows)
        average_dollar = _finite(state.get("average_dollar_volume"))
        rvol = session_dollar / (average_dollar * _session_progress(now)) if average_dollar and average_dollar > 0 else None
        families = _detect_families(
            rows,
            features,
            catalyst=state.get("catalyst"),
            relative_strength=relative_strength,
        )
        structure_probe = analyze_market_structure(
            rows,
            quote=quote,
            rvol=rvol,
            average_dollar_volume=average_dollar,
            higher_timeframes=state.get("higher_timeframes") or None,
            correlated_bars=self._correlated_bars_for(symbol),
            macro_event_window=bool(market_risk.get("macro_event_window")),
        )
        structure_by_direction: dict[str, dict[str, Any]] = {}
        probe_setup = structure_probe.get("best_setup") if isinstance(structure_probe.get("best_setup"), dict) else {}
        structure_families = {"cbc_strong_flip", "session_liquidity_sweep_reclaim", "ict_cisd_universal_model"}
        if probe_setup.get("pattern_id") in structure_families and not any(
            family == probe_setup.get("pattern_id") for family, _, _ in families
        ):
            families.append((
                str(probe_setup["pattern_id"]),
                str(probe_setup.get("direction") or "neutral"),
                str(probe_setup.get("reason") or "Completed-bar structure sequence is developing."),
            ))
        output: list[dict[str, Any]] = []
        context_source_labels = _context_source_labels(state.get("higher_timeframes"))
        for family, direction, reason in families:
            geometry = _geometry(direction, quote, features, rows[-1])
            if direction not in structure_by_direction:
                structure_by_direction[direction] = analyze_market_structure(
                    rows,
                    quote=quote,
                    rvol=rvol,
                    average_dollar_volume=average_dollar,
                    direction_hint=direction,
                    higher_timeframes=state.get("higher_timeframes") or None,
                    correlated_bars=self._correlated_bars_for(symbol),
                    macro_event_window=bool(market_risk.get("macro_event_window")),
                )
            market_structure = structure_by_direction[direction]
            if context_source_labels:
                market_structure["source_labels"] = list(dict.fromkeys([*market_structure["source_labels"], *context_source_labels]))
            blockers: list[str] = []
            blockers.extend(str(value) for value in data_quality.get("blockers") or [])
            if session_risk.get("hard_veto"):
                blockers.append(str(session_risk.get("phase") or "session_timing_blocked"))
            blockers.extend(str(value) for value in market_risk.get("blockers") or [])
            if quote["freshness"] not in {"live", "recent"}:
                blockers.append("stale_quote")
            if quote["spread_bps"] is None or float(quote["spread_bps"]) > MAX_SPREAD_BPS:
                blockers.append("spread_too_wide_or_missing")
            if average_dollar is None or average_dollar < MIN_DOLLAR_LIQUIDITY:
                blockers.append("insufficient_dollar_liquidity")
            if rvol is None or rvol < MIN_RVOL:
                blockers.append("rvol_below_preregistered_threshold")
            if geometry["reward_risk_after_friction"] is None or geometry["reward_risk_after_friction"] < 1.5:
                blockers.append("post_friction_reward_risk_below_1_5")
            if family == "catalyst_continuation" and not state.get("catalyst"):
                blockers.append("fresh_catalyst_required")
            blockers.extend(str(row) for row in market_structure.get("hard_blockers") or [])
            blockers = list(dict.fromkeys(blockers))
            structure_score = float(market_structure.get("score") or (92.0 if "retest" in family or family == "liquidity_sweep_mss_retest" else 84.0))
            activity_score = min(100.0, (rvol or 0.0) * 40.0)
            liquidity_score = 95.0 if (average_dollar or 0) >= 500_000_000 else 82.0
            spread_score = max(0.0, 100.0 - (quote["spread_bps"] or 100.0) * 2.0)
            catalyst_score = 90.0 if state.get("catalyst") else 50.0
            relative_score = min(100.0, abs(relative_strength or 0.0) * 2500.0)
            # The market-structure rubric is the single canonical grade.  The
            # remaining factors stay visible as context and gates, but must not
            # create a second dashboard score for the same setup.
            score = round(structure_score, 2)
            structure_decision = str(market_structure.get("decision") or "STAND_ASIDE")
            if blockers or structure_decision == "REJECT":
                decision_state = "REJECT"
            elif structure_decision == "READY_TO_REVIEW" and score >= 73:
                decision_state = "READY_TO_REVIEW"
            else:
                decision_state = "WATCH"
            row = {
                "candidate_id": f"{now.date().isoformat()}:{symbol}:{family}",
                "event_pair_id": f"{now.date().isoformat()}:{symbol}:{family}",
                "symbol": symbol,
                "asset_class": "equity",
                "setup_family": family,
                "direction": direction,
                "reason": reason,
                "decision_score": score,
                "grade": str(market_structure.get("grade") or "D"),
                "state": decision_state,
                "freshness": quote["freshness"],
                "quote": quote,
                "rvol_time_of_day": round(rvol, 3) if rvol is not None else None,
                "session_dollar_volume": round(session_dollar),
                "average_dollar_volume": round(average_dollar) if average_dollar is not None else None,
                "relative_strength_vs_market_sector": round(relative_strength, 5) if relative_strength is not None else None,
                "catalyst": state.get("catalyst"),
                "bar_start_at": features.get("last_completed_bar_at"),
                "bar_completed_at": (
                    (_utc(features.get("last_completed_bar_at")) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
                    if _utc(features.get("last_completed_bar_at")) else None
                ),
                "signal_available_at": now.isoformat().replace("+00:00", "Z"),
                "source_labels": [f"alpaca_{self.feed}_{self.transport}", "completed_5m_bars", *context_source_labels] + ([str((state.get("catalyst") or {}).get("source") or "catalyst")] if state.get("catalyst") else []),
                "blockers": blockers,
                "factor_scores": {
                    "structure": round(structure_score, 1),
                    "activity": round(activity_score, 1),
                    "liquidity": round(liquidity_score, 1),
                    "spread": round(spread_score, 1),
                    "catalyst": round(catalyst_score, 1),
                    "relative_strength": round(relative_score, 1),
                },
                "market_structure": market_structure,
                "data_quality": data_quality,
                "market_risk_context": market_risk,
                "session_risk_context": session_risk,
                **geometry,
                "execution_enabled": False,
                "can_submit_orders": False,
            }
            if geometry.get("entry") is not None:
                key = (symbol, family)
                direction_value = LevelDirection.LONG if direction == "bullish" else LevelDirection.SHORT
                machine = self._level_machines.get(key)
                if machine is None or machine.level != float(geometry["entry"]) or machine.direction != direction_value:
                    self._level_machines[key] = LevelStateMachine(
                        symbol=symbol,
                        level=float(geometry["entry"]),
                        direction=direction_value,
                    )
            for lifecycle in self._event_lifecycle:
                if (
                    lifecycle.get("pair_id") == row["event_pair_id"]
                    and lifecycle.get("paired_bar_lane") == "awaiting_completed_5m_candidate"
                ):
                    lifecycle.update({
                        "paired_bar_lane": "completed_5m_candidate_observed",
                        "bar_candidate_state": decision_state,
                        "bar_completed_at": row["bar_completed_at"],
                        "bar_signal_available_at": row["signal_available_at"],
                        "event_to_bar_seconds": max(
                            0.0,
                            (now - (_utc(lifecycle.get("event_at")) or now)).total_seconds(),
                        ),
                    })
            row["event_time_shadow"] = dict(state.get("event_time_shadow") or {
                "status": "unavailable", "reason": "no_event_time_observation",
                "shadow_vetoes": [], "execution_enabled": False, "can_submit_orders": False,
            })
            row["alert_deadline_shadow"] = build_action_deadline(
                row,
                {
                    "status": "insufficient_data",
                    "conservative_validity_seconds": 180,
                    "fallback_used": True,
                },
                now=now,
            )
            row["adaptive_conformal_shadow"] = adaptive_conformal_abstention(
                score / 100.0,
                [],
                as_of=now,
                economic_threshold=0.60,
            )
            output.append(row)
        return output

    def snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        risk_required = self.risk_report_path is not None
        market_risk = _market_risk_context(
            _read_json(self.risk_report_path) if self.risk_report_path is not None else {},
            now=now,
            required=risk_required,
        )
        session_risk = _session_risk_context(now)
        with self._lock:
            candidates = [
                row
                for symbol, state in sorted(self._symbols.items())
                for row in self._candidates_for(
                    symbol,
                    state,
                    now,
                    market_risk=market_risk,
                    session_risk=session_risk,
                )
            ]
            quote_times = [
                str((state.get("quote") or {}).get("timestamp") or (state.get("quote") or {}).get("t") or "")
                for state in self._symbols.values()
            ]
            structure_watchlist = []
            for symbol, state in sorted(self._symbols.items()):
                rows = _bars_normalized(state.get("bars") or [])
                quote = _quote_context(state.get("quote") or {}, now)
                data_quality = _data_quality_context(rows, quote, now=now, consolidated_quote=self.feed == "sip")
                session_dollar = sum(float(row["c"]) * float(row["v"]) for row in rows)
                average_dollar = _finite(state.get("average_dollar_volume"))
                rvol = session_dollar / (average_dollar * _session_progress(now)) if average_dollar and average_dollar > 0 else None
                analysis = analyze_market_structure(
                    rows,
                    quote=quote,
                    rvol=rvol,
                    average_dollar_volume=average_dollar,
                    higher_timeframes=state.get("higher_timeframes") or None,
                    correlated_bars=self._correlated_bars_for(symbol),
                    macro_event_window=bool(market_risk.get("macro_event_window")),
                )
                context_source_labels = _context_source_labels(state.get("higher_timeframes"))
                if context_source_labels:
                    analysis["source_labels"] = list(dict.fromkeys([*analysis["source_labels"], *context_source_labels]))
                structure_watchlist.append({
                    "symbol": symbol,
                    "decision": analysis["decision"],
                    "grade": analysis["grade"],
                    "score": analysis["score"],
                    "pattern_grade": analysis["pattern_grade"],
                    "best_setup": analysis["best_setup"],
                    "worst_setup": analysis["worst_setup"],
                    "entry_plan": analysis["entry_plan"],
                    "exit_plan": analysis["exit_plan"],
                    "hard_blockers": analysis["hard_blockers"],
                    "timeframe_alignment": analysis["timeframe_alignment"],
                    "timeframe_coverage": analysis["timeframe_coverage"],
                    "timeframe_scan": analysis["timeframe_scan"],
                    "timeframe_plan": analysis["timeframe_plan"],
                    "liquidity_level_context": analysis["liquidity_level_context"],
                    "volume_profile_context": analysis["volume_profile_context"],
                    "value_area_reversion_context": analysis["value_area_reversion_context"],
                    "participation_context": analysis["participation_context"],
                    "macro_context": analysis["macro_context"],
                    "strat_context": analysis["strat_context"],
                    "ny_0800_0900_range_context": analysis["ny_0800_0900_range_context"],
                    "smt_divergence_context": analysis["smt_divergence_context"],
                    "clc_entry_context": analysis["clc_entry_context"],
                    "data_quality": data_quality,
                    "market_risk_context": market_risk,
                    "session_risk_context": session_risk,
                    "freshness": analysis["freshness"],
                    "source_labels": analysis["source_labels"],
                    "execution_enabled": False,
                    "can_submit_orders": False,
                })
        candidates.sort(key=lambda row: (-float(row["decision_score"]), row["symbol"], row["setup_family"]))
        ready = [row for row in candidates if row["state"] == "READY_TO_REVIEW"]
        hot_candidates: dict[str, HotCandidate] = {}
        for row in candidates:
            quote = row.get("quote") or {}
            midpoint = _finite(quote.get("midpoint"))
            entry = _finite(row.get("entry"))
            distance = abs(midpoint - entry) / entry * 10_000 if midpoint is not None and entry else None
            symbol = str(row.get("symbol") or "")
            proposed = HotCandidate(symbol, _finite(row.get("decision_score")), distance)
            previous = hot_candidates.get(symbol)
            if previous is None or (proposed.base_score or 0) > (previous.base_score or 0):
                hot_candidates[symbol] = proposed
        hot_set = HotSetSelector(MAX_WEBSOCKET_SYMBOLS, reserved_symbols=PRIORITY_FOCUS_UNIVERSE).select(hot_candidates.values())
        exposure_rows = [
            {
                **row,
                "utility_score": row.get("decision_score"),
                "exposure_vector": {
                    "market": 1.0,
                    "bullish": 1.0 if row.get("direction") == "bullish" else -1.0,
                    str(row.get("setup_family") or "unknown"): 1.0,
                },
            }
            for row in ready
        ]
        deadline_queue = schedule_by_action_deadline(exposure_rows, capacity=min(3, len(exposure_rows)))
        diversified = diversify_discord_queue(
            exposure_rows,
            capacity=min(3, len(exposure_rows)),
            reserved_symbols=("DELL",),
        )
        feed = build_feed_provenance({"VIBE_TRADING_STOCK_FEED": self.feed})
        feed["transport"] = self.transport
        feed["label"] = f"alpaca_{self.feed}_{self.transport}"
        feed["last_event_at"] = max(quote_times, default=None)
        return {
            "schema_version": 1,
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "mode": "read_only_streaming_research" if self.transport == "websocket" else "read_only_rest_polling_research",
            "decision_state": "READY_TO_REVIEW" if ready else "STAND_ASIDE",
            "ready_count": len(ready),
            "candidate_count": len(candidates),
            "setup_families": list(SETUP_FAMILIES),
            "market_structure_patterns": list(PATTERN_CATALOG),
            "market_structure_watchlist": sorted(
                structure_watchlist,
                key=lambda row: (-float(row["score"]), row["symbol"]),
            ),
            "market_risk_context": market_risk,
            "session_risk_context": session_risk,
            "data_quality_summary": {
                "status": "blocked" if any(row.get("data_quality", {}).get("status") == "blocked" for row in structure_watchlist) else "degraded" if any(row.get("data_quality", {}).get("status") == "degraded" for row in structure_watchlist) else "pass",
                "blocked_symbols": [row["symbol"] for row in structure_watchlist if row.get("data_quality", {}).get("status") == "blocked"],
                "degraded_symbols": [row["symbol"] for row in structure_watchlist if row.get("data_quality", {}).get("status") == "degraded"],
                "source_labels": ["completed_5m_bar_integrity_v1", "alpaca_latest_quote_integrity_v1"],
                "execution_enabled": False,
                "can_submit_orders": False,
            },
            "event_time_intelligence": {
                "status": "observing" if any((state.get("event_time_shadow") or {}).get("last_event_at") for state in self._symbols.values()) else "awaiting_events",
                "hot_set": hot_set,
                "symbols": {
                    symbol: dict(state.get("event_time_shadow") or {})
                    for symbol, state in sorted(self._symbols.items())
                    if state.get("event_time_shadow")
                },
                "recent_event_audit": list(self._event_audit)[-100:],
                "lifecycle": list(self._event_lifecycle)[-100:],
                "shadow_heads_up_count": sum(row.get("state") == "SHADOW_HEADS_UP" for row in self._event_lifecycle),
                "event_intensity": {
                    symbol: self._event_intensity_card(symbol, now=now)
                    for symbol in sorted(self._symbols)
                },
                "authority": "shadow_challenger_never_overrides_completed_bar_or_deterministic_veto",
                "execution_enabled": False,
                "can_submit_orders": False,
            },
            "discord_diversification_shadow": diversified,
            "discord_deadline_queue_shadow": deadline_queue,
            "feed": feed,
            "providers": build_provider_registry(root=ROOT),
            "validation": _validation_snapshot(ROOT),
            "candidates": candidates,
            "top_candidates": ready[:3],
            "warnings": [
                "Candidates are research priorities, not trade recommendations.",
                "Every level requires quote and completed-bar revalidation before manual action.",
                "No order authority is present in this process.",
            ],
            "execution_enabled": False,
            "can_submit_orders": False,
        }


def _radar_setup_family(source: Mapping[str, Any]) -> str:
    setup = str(source.get("setup") or "").lower()
    if "opening_range" in setup:
        return "opening_range_break_retest"
    if str(source.get("direction") or "").lower() == "bearish":
        return "relative_weakness_breakdown"
    return "vwap_reclaim_pullback"


def project_radar_report(radar: dict[str, Any], *, feed: str = "iex") -> dict[str, Any]:
    """Project the existing scheduled radar into the canonical stream schema."""
    candidates: list[dict[str, Any]] = []
    for source in radar.get("ranked_candidates") or []:
        if not isinstance(source, dict):
            continue
        levels = source.get("trade_levels") if isinstance(source.get("trade_levels"), dict) else {}
        family = _radar_setup_family(source)
        blockers = [str(value) for value in source.get("blockers") or []]
        if "fresh_quote_and_post_friction_geometry_required" not in blockers:
            blockers.append("fresh_quote_and_post_friction_geometry_required")
        scheduled_score = float(source.get("score") or 0.0)
        candidates.append({
            "candidate_id": f"{radar.get('date')}:{source.get('symbol')}:{family}",
            "symbol": source.get("symbol"),
            "asset_class": "equity",
            "setup_family": family,
            "direction": source.get("direction"),
            "reason": "scheduled radar projection; canonical live pattern components require fresh bars and quote revalidation",
            "decision_score": scheduled_score,
            "grade": _grade(scheduled_score),
            "score_basis": "scheduled_radar_legacy_not_pattern_grade_v1",
            "state": "WATCH",
            "freshness": "recent",
            "entry": levels.get("confirmation_trigger"),
            "invalidation": levels.get("invalidation"),
            "targets": [{"name": "target_2r", "price": levels.get("target_2r")}] if levels.get("target_2r") is not None else [],
            "reward_risk_after_friction": None,
            "rvol_time_of_day": source.get("volume_pace_rvol_proxy"),
            "session_dollar_volume": source.get("current_session_dollar_volume"),
            "average_dollar_volume": source.get("avg_dollar_volume_20d"),
            "source_labels": [f"alpaca_{feed}_scheduled_radar", "completed_5m_bars", "pattern_grade_v1_unavailable_in_fallback"],
            "blockers": blockers,
            "execution_enabled": False,
            "can_submit_orders": False,
        })
    candidates.sort(key=lambda row: float(row.get("decision_score") or 0), reverse=True)
    ready = [row for row in candidates if row.get("state") == "READY_TO_REVIEW"]
    return {
        "schema_version": 1,
        "generated_at": radar.get("generated_at") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "read_only_scheduled_fallback",
        "decision_state": "READY_TO_REVIEW" if ready else "STAND_ASIDE",
        "ready_count": len(ready),
        "candidate_count": len(candidates),
        "setup_families": list(SETUP_FAMILIES),
        "market_structure_patterns": list(PATTERN_CATALOG),
        "market_structure_watchlist": [],
        "feed": build_feed_provenance({"VIBE_TRADING_STOCK_FEED": feed}),
        "providers": build_provider_registry(root=ROOT),
        "validation": _validation_snapshot(ROOT),
        "candidates": candidates,
        "top_candidates": ready[:3],
        "source_report": "intraday-opportunity-radar.json",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


class FiveMinuteAggregator:
    def __init__(self) -> None:
        self._buckets: dict[tuple[str, datetime], dict[str, Any]] = {}

    def add(self, symbol: str, message: dict[str, Any]) -> dict[str, Any] | None:
        stamp = _utc(message.get("t"))
        if stamp is None:
            return None
        bucket = stamp.replace(minute=stamp.minute - stamp.minute % 5, second=0, microsecond=0)
        key = (symbol, bucket)
        current = self._buckets.get(key)
        incoming = _bars_normalized([message])
        if not incoming:
            return None
        bar = incoming[0]
        if current is None:
            current = {**bar, "t": bucket.isoformat().replace("+00:00", "Z")}
            self._buckets[key] = current
        else:
            current["h"] = max(float(current["h"]), float(bar["h"]))
            current["l"] = min(float(current["l"]), float(bar["l"]))
            current["c"] = bar["c"]
            current["v"] = float(current["v"]) + float(bar["v"])
        prior_keys = sorted(value for value in self._buckets if value[0] == symbol and value[1] < bucket)
        if not prior_keys:
            return None
        complete_key = prior_keys[-1]
        return self._buckets.pop(complete_key)


def _load_alpaca_credentials() -> tuple[str, str]:
    from scripts.premarket_opportunity_radar import _credentials

    headers = _credentials()
    return str(headers.get("APCA-API-KEY-ID") or ""), str(headers.get("APCA-API-SECRET-KEY") or "")


def _alpaca_market_event(
    message: Mapping[str, Any], *, received_at: datetime | None = None, source: str = "alpaca",
) -> MarketEvent | None:
    """Normalize a documented Alpaca stock-stream message without inventing fields."""
    event_type = str(message.get("T") or "")
    kind = {
        "t": EventKind.TRADE,
        "q": EventKind.QUOTE,
        "b": EventKind.BAR,
        "u": EventKind.UPDATED_BAR,
        "c": EventKind.CORRECTION,
        "x": EventKind.CANCEL_ERROR,
        "s": EventKind.STATUS,
        "l": EventKind.LULD,
    }.get(event_type)
    event_at = _utc(message.get("t"))
    symbol = str(message.get("S") or "").upper()
    if kind is None or event_at is None or not symbol:
        return None
    received = (received_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    conditions = message.get("c")
    condition_tuple = tuple(str(item) for item in conditions) if isinstance(conditions, list) else ((str(conditions),) if conditions else ())
    original = (
        message.get("i") if event_type == "x"
        else message.get("oi") if event_type == "c"
        else message.get("original_id")
    )
    try:
        original_sequence = int(original) if original is not None else None
    except (TypeError, ValueError):
        # Alpaca trade IDs are not guaranteed to be numeric. Retain a stable
        # local digest solely as a revocation reference, never as venue sequence.
        original_sequence = int.from_bytes(str(original).encode("utf-8")[:8], "little") if original else None
    return MarketEvent(
        symbol=symbol,
        kind=kind,
        event_ts=event_at,
        received_ts=received,
        sequence=None,
        source=source,
        price=_finite(message.get("p") if message.get("p") is not None else message.get("c")),
        size=_finite(message.get("s")),
        bid=_finite(message.get("bp")),
        ask=_finite(message.get("ap")),
        bid_size=_finite(message.get("bs")),
        ask_size=_finite(message.get("as")),
        conditions=condition_tuple,
        status_code=str(message.get("sc") or message.get("status") or "") or None,
        reason_code=str(message.get("rc") or message.get("reason") or "") or None,
        lower_band=_finite(message.get("d") if message.get("d") is not None else message.get("lower_band")),
        upper_band=_finite(message.get("u") if message.get("u") is not None else message.get("upper_band")),
        original_sequence=original_sequence,
        metadata={"provider_message_type": event_type},
    )


def _receive_control(ws: Any, *, expected_type: str, expected_message: str | None = None) -> list[dict[str, Any]]:
    payload = json.loads(ws.recv())
    messages = payload if isinstance(payload, list) else [payload]
    rows = [row for row in messages if isinstance(row, dict)]
    for row in rows:
        if row.get("T") == "error":
            raise RuntimeError(f"alpaca_stream_error_{row.get('code', 'unknown')}")
    if not any(
        row.get("T") == expected_type
        and (expected_message is None or row.get("msg") == expected_message)
        for row in rows
    ):
        raise RuntimeError(f"alpaca_stream_missing_{expected_type}_{expected_message or 'ack'}")
    return rows


def _fetch_latest_quotes(symbols: list[str], *, feed: str) -> dict[str, dict[str, Any]]:
    import requests

    key, secret = _load_alpaca_credentials()
    response = requests.get(
        "https://data.alpaca.markets/v2/stocks/quotes/latest",
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
        params={"symbols": ",".join(symbols[:100]), "feed": feed},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    quotes = payload.get("quotes") if isinstance(payload, dict) else {}
    return {
        str(symbol).upper(): row
        for symbol, row in (quotes or {}).items()
        if isinstance(row, dict)
    }


def _fetch_completed_hourly_bars(
    symbols: list[str], *, feed: str, now: datetime | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Fetch bounded, completed hourly context using existing Alpaca data credentials."""
    import requests

    if not symbols:
        return {}
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    key, secret = _load_alpaca_credentials()
    params: dict[str, Any] = {
        "symbols": ",".join(symbols[:100]),
        "timeframe": "30Min",
        "start": (current - timedelta(days=10)).isoformat().replace("+00:00", "Z"),
        "end": current.isoformat().replace("+00:00", "Z"),
        "adjustment": "raw",
        "feed": feed,
        "limit": 10000,
        "sort": "asc",
    }
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    token: str | None = None
    for _ in range(4):
        if token:
            params["page_token"] = token
        response = requests.get(
            "https://data.alpaca.markets/v2/stocks/bars",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            params=params,
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        for symbol, rows in (payload.get("bars") or {}).items():
            for row in rows if isinstance(rows, list) else []:
                stamp = _utc(row.get("t")) if isinstance(row, dict) else None
                if stamp is not None and stamp + timedelta(minutes=30) <= current:
                    output[str(symbol).upper()].append(row)
        token = str(payload.get("next_page_token") or "") or None
        if not token:
            break
    return {symbol: _aggregate_rth_hourly(rows)[-120:] for symbol, rows in output.items()}


def _fetch_completed_intraday_context_bars(
    symbols: list[str], *, feed: str, timeframe: str, minutes: int, now: datetime | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Fetch recent, completed RTH confirmation bars for 15m/30m roles."""
    import requests

    if not symbols:
        return {}
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    key, secret = _load_alpaca_credentials()
    params: dict[str, Any] = {
        "symbols": ",".join(symbols[:100]),
        "timeframe": timeframe,
        "start": (current - timedelta(days=10)).isoformat().replace("+00:00", "Z"),
        "end": current.isoformat().replace("+00:00", "Z"),
        "adjustment": "raw",
        "feed": feed,
        "limit": 10000,
        "sort": "asc",
    }
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    token: str | None = None
    for _ in range(4):
        if token:
            params["page_token"] = token
        response = requests.get(
            "https://data.alpaca.markets/v2/stocks/bars",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            params=params,
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        for symbol, rows in (payload.get("bars") or {}).items():
            for row in rows if isinstance(rows, list) else []:
                stamp = _utc(row.get("t")) if isinstance(row, dict) else None
                if stamp is None:
                    continue
                local = stamp.astimezone(MARKET_TZ)
                minute_of_day = local.hour * 60 + local.minute
                if 9 * 60 + 30 <= minute_of_day < 16 * 60 and stamp + timedelta(minutes=minutes) <= current:
                    output[str(symbol).upper()].append(row)
        token = str(payload.get("next_page_token") or "") or None
        if not token:
            break
    return {symbol: _bars_normalized(rows)[-120:] for symbol, rows in output.items()}


def _fetch_completed_period_bars(
    symbols: list[str], *, feed: str, timeframe: str, lookback_days: int, now: datetime | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Fetch bounded daily/weekly context and discard the active period."""
    import requests

    if not symbols:
        return {}
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    key, secret = _load_alpaca_credentials()
    params: dict[str, Any] = {
        "symbols": ",".join(symbols[:100]),
        "timeframe": timeframe,
        "start": (current - timedelta(days=lookback_days)).isoformat().replace("+00:00", "Z"),
        "end": current.isoformat().replace("+00:00", "Z"),
        "adjustment": "raw",
        "feed": feed,
        "limit": 10000,
        "sort": "asc",
    }
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    token: str | None = None
    for _ in range(4):
        if token:
            params["page_token"] = token
        response = requests.get(
            "https://data.alpaca.markets/v2/stocks/bars",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            params=params,
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        for symbol, rows in (payload.get("bars") or {}).items():
            if isinstance(rows, list):
                output[str(symbol).upper()].extend(row for row in rows if isinstance(row, dict))
        token = str(payload.get("next_page_token") or "") or None
        if not token:
            break
    return {
        symbol: _filter_completed_period_bars(rows, timeframe=timeframe, now=current)[-120:]
        for symbol, rows in output.items()
    }


def _fetch_completed_context_bars(
    symbols: list[str], *, feed: str, now: datetime | None = None
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Fetch every broker-supported context frame needed by the A+ matrix."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=5, thread_name_prefix="aplus-context") as pool:
        futures = {
            "15m": pool.submit(_fetch_completed_intraday_context_bars, symbols, feed=feed, timeframe="15Min", minutes=15, now=now),
            "30m": pool.submit(_fetch_completed_intraday_context_bars, symbols, feed=feed, timeframe="30Min", minutes=30, now=now),
            "60m": pool.submit(_fetch_completed_hourly_bars, symbols, feed=feed, now=now),
            "1d": pool.submit(_fetch_completed_period_bars, symbols, feed=feed, timeframe="1Day", lookback_days=220, now=now),
            "1w": pool.submit(_fetch_completed_period_bars, symbols, feed=feed, timeframe="1Week", lookback_days=1_100, now=now),
        }
        context: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for timeframe, future in futures.items():
            try:
                context[timeframe] = future.result()
            except Exception:
                # Each missing frame is visible in coverage and fails its own
                # gate closed without taking down the other read-only sources.
                context[timeframe] = {}
    context["4h"] = {
        symbol: _aggregate_rth_four_hour(rows)[-120:]
        for symbol, rows in context.get("30m", {}).items()
        if rows
    }
    return {
        symbol: {
            timeframe: context[timeframe].get(symbol) or []
            for timeframe in ("15m", "30m", "60m", "4h", "1d", "1w")
        }
        for symbol in symbols
    }


def run_rest_poll(
    engine: LiveOpportunityEngine,
    symbols: list[str],
    *,
    report_path: Path,
    stop_event: threading.Event,
) -> int:
    """Fallback when the account's single Alpaca WebSocket is already in use."""
    engine.transport = "rest_polling"
    websocket_symbols: list[str] = []
    rest_symbols = list(symbols)
    next_bar_refresh = 0.0
    next_context_refresh = time.monotonic() + 15 * 60.0
    while not stop_event.is_set():
        try:
            quotes = _fetch_latest_quotes(symbols, feed=engine.feed)
            for symbol, quote in quotes.items():
                engine.update_quote(symbol, quote)
            if time.monotonic() >= next_bar_refresh:
                bars, _ = fetch_intraday_bars(symbols, datetime.now(MARKET_TZ))
                for symbol, rows in bars.items():
                    for bar in rows[-120:]:
                        engine.update_completed_bar(symbol, bar)
                next_bar_refresh = time.monotonic() + 60.0
            if time.monotonic() >= next_context_refresh:
                refreshed = _fetch_completed_context_bars(symbols, feed=engine.feed)
                refreshed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                for symbol in symbols:
                    engine.update_higher_timeframes(
                        symbol,
                        refreshed.get(symbol) or {},
                        refreshed_at=refreshed_at,
                    )
                next_context_refresh = time.monotonic() + 15 * 60.0
            snapshot = engine.snapshot()
            snapshot["stream_status"] = "rest_polling_fallback"
            snapshot["stream_fallback_reason"] = "alpaca_websocket_connection_limit"
            snapshot["stream_coverage"] = _stream_coverage(
                websocket_symbols,
                rest_symbols,
                rest_quote_status="connected",
                rest_bar_status="connected",
            )
            _atomic_json(report_path, snapshot)
        except Exception as exc:
            failure = engine.snapshot()
            failure["stream_status"] = "rest_polling_degraded"
            failure["stream_error"] = type(exc).__name__
            failure["stream_coverage"] = _stream_coverage(
                websocket_symbols,
                rest_symbols,
                rest_quote_status=f"degraded_{type(exc).__name__}",
                rest_bar_status=f"degraded_{type(exc).__name__}",
            )
            failure["decision_state"] = "STAND_ASIDE"
            failure["ready_count"] = 0
            _atomic_json(report_path, failure)
        stop_event.wait(5.0)
    return 0


def run_stream(
    engine: LiveOpportunityEngine,
    symbols: list[str],
    *,
    report_path: Path,
    stop_event: threading.Event | None = None,
) -> int:
    """Run Alpaca's read-only stock stream with bounded reconnect backoff."""
    import websocket

    stop = stop_event or threading.Event()
    key, secret = _load_alpaca_credentials()
    if not key or not secret:
        raise RuntimeError("Alpaca market-data credentials are unavailable")
    websocket_symbols, rest_symbols = _event_time_symbol_partition(engine, symbols)
    aggregator = FiveMinuteAggregator()
    delay = 1.0
    while not stop.is_set():
        try:
            ws = websocket.create_connection(build_feed_provenance({"VIBE_TRADING_STOCK_FEED": engine.feed})["endpoint"], timeout=20)
            _receive_control(ws, expected_type="success", expected_message="connected")
            ws.send(json.dumps({"action": "auth", "key": key, "secret": secret}))
            _receive_control(ws, expected_type="success", expected_message="authenticated")
            ws.send(json.dumps({
                "action": "subscribe",
                "trades": websocket_symbols,
                "quotes": websocket_symbols,
                "bars": websocket_symbols,
                "updatedBars": websocket_symbols,
                "statuses": websocket_symbols,
                "lulds": websocket_symbols,
            }))
            _receive_control(ws, expected_type="subscription")
            if hasattr(ws, "settimeout"):
                ws.settimeout(2.0)
            delay = 1.0
            last_write = 0.0
            next_rest_quote_refresh = 0.0
            next_rest_bar_refresh = 0.0
            next_context_refresh = time.monotonic() + 15 * 60.0
            rest_quote_status = "not_required" if not rest_symbols else "pending"
            rest_bar_status = "not_required" if not rest_symbols else "pending"
            next_hot_rebalance = time.monotonic() + HOT_SET_REBALANCE_SECONDS
            while not stop.is_set():
                try:
                    messages = json.loads(ws.recv())
                except websocket.WebSocketTimeoutException:
                    messages = []
                for message in messages if isinstance(messages, list) else [messages]:
                    if not isinstance(message, dict):
                        continue
                    if message.get("T") == "error":
                        raise RuntimeError(f"alpaca_stream_error_{message.get('code', 'unknown')}")
                    symbol = str(message.get("S") or "").upper()
                    normalized_event = _alpaca_market_event(message, source=f"alpaca_{engine.feed}")
                    if normalized_event is not None:
                        engine.update_market_event(normalized_event)
                    if message.get("T") == "q" and symbol:
                        engine.update_quote(symbol, {
                            "bid": message.get("bp"),
                            "ask": message.get("ap"),
                            "bid_size": message.get("bs"),
                            "ask_size": message.get("as"),
                            "timestamp": message.get("t"),
                        })
                    elif message.get("T") == "b" and symbol:
                        completed = aggregator.add(symbol, message)
                        if completed:
                            engine.update_completed_bar(symbol, completed)
                current_tick = time.monotonic()
                if current_tick >= next_hot_rebalance:
                    desired_websocket, desired_rest = _event_time_symbol_partition(engine, symbols)
                    removed = sorted(set(websocket_symbols) - set(desired_websocket))
                    added = sorted(set(desired_websocket) - set(websocket_symbols))
                    if removed:
                        ws.send(json.dumps({
                            "action": "unsubscribe", "trades": removed, "quotes": removed,
                            "bars": removed, "updatedBars": removed, "statuses": removed,
                            "lulds": removed,
                        }))
                    if added:
                        ws.send(json.dumps({
                            "action": "subscribe", "trades": added, "quotes": added,
                            "bars": added, "updatedBars": added, "statuses": added,
                            "lulds": added,
                        }))
                    websocket_symbols, rest_symbols = desired_websocket, desired_rest
                    next_hot_rebalance = current_tick + HOT_SET_REBALANCE_SECONDS
                if rest_symbols and current_tick >= next_rest_quote_refresh:
                    try:
                        quotes = _fetch_latest_quotes(rest_symbols, feed=engine.feed)
                        for symbol, quote in quotes.items():
                            engine.update_quote(symbol, quote)
                        rest_quote_status = "connected"
                    except Exception as exc:
                        rest_quote_status = f"degraded_{type(exc).__name__}"
                    next_rest_quote_refresh = current_tick + REST_QUOTE_REFRESH_SECONDS
                if rest_symbols and current_tick >= next_rest_bar_refresh:
                    try:
                        bars, _ = fetch_intraday_bars(rest_symbols, datetime.now(MARKET_TZ))
                        for symbol, rows in bars.items():
                            for bar in rows[-120:]:
                                engine.update_completed_bar(symbol, bar)
                        rest_bar_status = "connected"
                    except Exception as exc:
                        rest_bar_status = f"degraded_{type(exc).__name__}"
                    next_rest_bar_refresh = current_tick + REST_BAR_REFRESH_SECONDS
                if current_tick >= next_context_refresh:
                    refreshed = _fetch_completed_context_bars(symbols, feed=engine.feed)
                    refreshed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    for symbol in symbols:
                        engine.update_higher_timeframes(
                            symbol,
                            refreshed.get(symbol) or {},
                            refreshed_at=refreshed_at,
                        )
                    next_context_refresh = time.monotonic() + 15 * 60.0
                if current_tick - last_write >= 2.0:
                    snapshot = engine.snapshot()
                    snapshot["stream_status"] = "connected_hybrid" if rest_symbols else "connected"
                    snapshot["stream_coverage"] = _stream_coverage(
                        websocket_symbols,
                        rest_symbols,
                        rest_quote_status=rest_quote_status,
                        rest_bar_status=rest_bar_status,
                    )
                    _atomic_json(report_path, snapshot)
                    last_write = current_tick
            ws.close()
        except Exception as exc:
            if str(exc) == "alpaca_stream_error_406":
                return run_rest_poll(
                    engine,
                    symbols,
                    report_path=report_path,
                    stop_event=stop,
                )
            failure = engine.snapshot()
            failure["stream_status"] = "reconnecting"
            failure["stream_error"] = type(exc).__name__
            failure["stream_error_code"] = str(exc) if str(exc).startswith("alpaca_stream_") else None
            failure["decision_state"] = "STAND_ASIDE"
            failure["ready_count"] = 0
            _atomic_json(report_path, failure)
            stop.wait(delay)
            delay = min(delay * 2.0, 30.0)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--radar-path", type=Path, default=DEFAULT_RADAR_PATH)
    parser.add_argument("--feed", choices=("iex", "sip"), default=os.getenv("VIBE_TRADING_STOCK_FEED", "iex"))
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--symbols", default="")
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    radar = _read_json(args.radar_path)
    if not args.stream:
        report = project_radar_report(radar, feed=args.feed)
        _atomic_json(args.report_path, report)
        if args.print_report:
            print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    symbols = sorted({value.strip().upper() for value in args.symbols.split(",") if value.strip()})
    if not symbols:
        symbols = [str(value) for value in radar.get("all_discovered_symbols") or []][:100]
    if not symbols:
        symbols = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMD", "TSLA"]
    symbols = _with_core_context_symbols(symbols)
    engine = LiveOpportunityEngine(feed=args.feed, risk_report_path=DEFAULT_CATALYST_PATH)
    context_rows = [
        row
        for key in ("ranked_candidates", "filtered_candidates")
        for row in radar.get(key) or []
        if isinstance(row, dict)
    ]
    context_by_symbol = {
        str(row.get("symbol") or "").upper(): row
        for row in context_rows
        if row.get("symbol")
    }
    bootstrap_bars: dict[str, list[dict[str, Any]]] = {}
    bootstrap_context: dict[str, dict[str, list[dict[str, Any]]]] = {}
    if args.feed == "iex":
        # Seed completed bars before opening the socket so candidates can be
        # evaluated as soon as their first fresh quote arrives.
        bootstrap_bars, _ = fetch_intraday_bars(symbols, datetime.now(MARKET_TZ))
    try:
        bootstrap_context = _fetch_completed_context_bars(symbols, feed=args.feed)
    except Exception:
        # Missing HTF context fails A+ readiness and the CISD model closed; it
        # must not prevent the rest of the read-only dashboard from starting.
        bootstrap_context = {}
    for symbol in symbols:
        row = context_by_symbol.get(symbol, {})
        engine.seed_symbol(
            symbol,
            bars=bootstrap_bars.get(symbol) or [],
            quote={},
            higher_timeframes=bootstrap_context.get(symbol) or {},
            average_dollar_volume=_finite(row.get("avg_dollar_volume_20d")),
            catalyst=(row.get("catalyst_headlines") or [None])[0],
            mapped_levels=row.get("trade_levels") if isinstance(row.get("trade_levels"), dict) else None,
            mapped_setup_family=_radar_setup_family(row) if row else None,
            mapped_direction=str(row.get("direction") or "") or None,
        )
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    return run_stream(engine, symbols, report_path=args.report_path, stop_event=stop)


if __name__ == "__main__":
    raise SystemExit(main())
