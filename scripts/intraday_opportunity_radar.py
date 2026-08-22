#!/usr/bin/env python3
"""Market-wide intraday discovery radar (read-only, no order authority).

The radar expands beyond the repository's static watchlists by combining
Alpaca's market movers and most-active screeners plus fresh news, standing
liquid names, and the repository's current-day scanners. Candidates are then
checked against executable spread, dollar liquidity, completed 5-minute
structure, volume pace, and fresh news. It produces watch and confirmation
levels only; it never submits an order or promotes a strategy.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.premarket_opportunity_radar import (  # noqa: E402
    BASE_UNIVERSE,
    _atomic_json,
    _credentials,
    _finite,
    _read_json,
    fetch_daily_liquidity,
    fetch_news,
    fetch_snapshots,
    load_social_symbols,
    news_by_symbol,
    snapshot_metrics,
)

VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "intraday-opportunity-radar.json"
LOG_PATH = ROOT / "data" / "intraday_opportunity_radar_log.jsonl"
SCREENER_BASE = "https://data.alpaca.markets/v1beta1/screener"
MARKET_TZ = ZoneInfo("America/New_York")
MIN_PRICE = 3.0
MIN_AVG_DOLLAR_VOLUME = 20_000_000.0
MIN_CURRENT_DOLLAR_VOLUME = 5_000_000.0
MAX_UNDERLYING_SPREAD_PCT = 0.015
MAX_BAR_SYMBOLS = 100
CORE_BENCHMARKS = ("SPY", "QQQ", "IWM")
CORE_LIQUID_SYMBOLS = (
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "AVGO",
    "MSTR", "COIN",
)
INTRADAY_EXTENDED_UNIVERSE = [
    # Liquid thematic names can produce tradeable sector moves without making
    # Alpaca's top-100 activity lists. Keep this list small and auditable.
    "HUT", "MARA", "RIOT", "CLSK", "CIFR", "IREN", "APLD", "WULF", "BTDR", "BITF", "CAN",
    "CF", "MOS", "NTR", "AGCO", "MANH", "AU", "GOLD", "KGC",
]
KNOWN_LEADERS = list(dict.fromkeys(BASE_UNIVERSE + INTRADAY_EXTENDED_UNIVERSE))
REPORT_NOMINATION_SOURCES = (
    ("deep_liquid_universe", VIBE_HOME / "reports" / "deep-liquid-universe-scan.json", ("scans", "top_candidates")),
    ("daily_stock_screener", VIBE_HOME / "reports" / "daily-stock-screener.json", ("rankings",)),
    ("premarket_opportunity_radar", VIBE_HOME / "reports" / "premarket-opportunity-radar.json", ("observations",)),
)

FACTOR_CONSENSUS_WEIGHTS = {
    "momentum": 0.18,
    "volume_pace": 0.19,
    "liquidity": 0.16,
    "spread_quality": 0.16,
    "structure": 0.18,
    "discovery_breadth": 0.08,
    "catalyst": 0.05,
}


def _valid_symbol(value: Any) -> str | None:
    symbol = str(value or "").strip().upper()
    if not symbol or len(symbol) > 6 or not symbol.replace(".", "").isalnum():
        return None
    return symbol


def nominate_symbols(discovered: dict[str, dict[str, Any]], symbols: list[str], source: str) -> None:
    """Add symbols with provenance while preserving existing screener metadata."""
    for raw_symbol in symbols:
        symbol = _valid_symbol(raw_symbol)
        if not symbol:
            continue
        item = discovered.setdefault(
            symbol,
            {"symbol": symbol, "sources": [], "source_ranks": {}, "screener_values": {}},
        )
        if source not in item["sources"]:
            item["sources"].append(source)


def symbols_from_report_payload(
    payload: dict[str, Any], row_keys: tuple[str, ...], as_of_date: str,
) -> list[str]:
    """Read only same-day report symbols so stale candidates cannot leak forward."""
    report_date = str(payload.get("date") or payload.get("generated_at") or "")[:10]
    if report_date != as_of_date:
        return []
    symbols: list[str] = []
    for key in row_keys:
        for row in payload.get(key) or []:
            if not isinstance(row, dict):
                continue
            symbol = _valid_symbol(row.get("symbol"))
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    return symbols


def coverage_trace(
    discovered: dict[str, dict[str, Any]], snapshots: dict[str, Any], selected: list[str], bars: dict[str, Any],
) -> list[dict[str, Any]]:
    selected_set = set(selected)
    trace = []
    for symbol in sorted(discovered):
        if symbol not in snapshots:
            stop_stage = "snapshot_unavailable"
        elif symbol not in selected_set:
            stop_stage = "not_selected_for_intraday_bars"
        elif not bars.get(symbol):
            stop_stage = "intraday_bars_unavailable"
        else:
            stop_stage = "evaluated"
        trace.append({
            "symbol": symbol,
            "nomination_sources": sorted(set(discovered[symbol].get("sources") or [])),
            "snapshot_available": symbol in snapshots,
            "selected_for_intraday_bars": symbol in selected_set,
            "intraday_bars_available": bool(bars.get(symbol)),
            "stop_stage": stop_stage,
        })
    return trace


def select_symbols_for_intraday_bars(
    discovered: dict[str, dict[str, Any]], metrics: dict[str, dict[str, Any]], limit: int = MAX_BAR_SYMBOLS,
) -> list[str]:
    """Reserve liquid core names, then balance magnitude, activity, and coverage."""
    available = [symbol for symbol in discovered if symbol in metrics]
    by_magnitude = sorted(
        available,
        key=lambda symbol: (
            abs(_finite(metrics[symbol].get("gap_return")) or 0.0),
            _finite(metrics[symbol].get("snapshot_volume")) or 0.0,
        ),
        reverse=True,
    )
    by_activity = sorted(
        available,
        key=lambda symbol: (
            _finite(metrics[symbol].get("snapshot_volume")) or 0.0,
            abs(_finite(metrics[symbol].get("gap_return")) or 0.0),
        ),
        reverse=True,
    )
    standing = sorted(
        (
            symbol for symbol in available
            if "known_liquid_leader" in (discovered[symbol].get("sources") or [])
        ),
        key=lambda symbol: (
            abs(_finite(metrics[symbol].get("gap_return")) or 0.0),
            _finite(metrics[symbol].get("snapshot_volume")) or 0.0,
        ),
        reverse=True,
    )
    selected = [symbol for symbol in CORE_LIQUID_SYMBOLS if symbol in available][:limit]
    remaining = max(0, limit - len(selected))
    magnitude_quota = round(remaining * 0.50)
    activity_quota = round(remaining * 0.30)
    quotas = (
        (by_magnitude, magnitude_quota),
        (by_activity, activity_quota),
        (standing, max(0, remaining - magnitude_quota - activity_quota)),
    )
    for ranked, quota in quotas:
        if quota <= 0:
            continue
        added = 0
        for symbol in ranked:
            if symbol in selected:
                continue
            selected.append(symbol)
            added += 1
            if added >= quota:
                break
    if len(selected) < limit:
        for symbol in by_magnitude:
            if symbol not in selected:
                selected.append(symbol)
            if len(selected) >= limit:
                break
    return selected[:limit]


def _screen_rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    return [row for row in rows or [] if isinstance(row, dict)]


def fetch_market_screeners(top_movers: int = 50, top_active: int = 100) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Return official Alpaca discovery lists without exposing credentials."""
    headers = _credentials()
    sources: dict[str, list[dict[str, Any]]] = {
        "movers_gainers": [],
        "movers_losers": [],
        "most_active_volume": [],
        "most_active_trades": [],
    }
    errors: list[str] = []
    requests_to_make = [
        ("movers", f"{SCREENER_BASE}/stocks/movers", {"top": top_movers}),
        ("most_active_volume", f"{SCREENER_BASE}/stocks/most-actives", {"top": top_active, "by": "volume"}),
        ("most_active_trades", f"{SCREENER_BASE}/stocks/most-actives", {"top": top_active, "by": "trades"}),
    ]
    for name, url, params in requests_to_make:
        try:
            response = requests.get(url, headers=headers, params=params, timeout=18)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            errors.append(f"alpaca_{name}:{type(exc).__name__}")
            continue
        if name == "movers":
            sources["movers_gainers"] = _screen_rows(payload, "gainers")
            sources["movers_losers"] = _screen_rows(payload, "losers")
        else:
            sources[name] = _screen_rows(payload, "most_actives")
    return sources, errors


def discovery_map(sources: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for source_name, rows in sources.items():
        for rank, row in enumerate(rows, start=1):
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol or not symbol.replace(".", "").isalnum():
                continue
            item = output.setdefault(symbol, {"symbol": symbol, "sources": [], "source_ranks": {}, "screener_values": {}})
            item["sources"].append(source_name)
            item["source_ranks"][source_name] = rank
            item["screener_values"][source_name] = {
                key: value for key, value in row.items() if key != "symbol"
            }
    return output


def normalized_movers(sources: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_name in ("movers_gainers", "movers_losers"):
        direction = "gainer" if source_name.endswith("gainers") else "loser"
        for rank, row in enumerate(sources.get(source_name) or [], start=1):
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "direction": direction,
                    "rank": rank,
                    "price": _finite(row.get("price")),
                    "change": _finite(row.get("change")),
                    "percent_change": _finite(row.get("percent_change")),
                }
            )
    return rows


def fetch_intraday_bars(symbols: list[str], now_et: datetime) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    if not symbols:
        return {}, []
    start_et = datetime.combine(now_et.date(), time(9, 30), MARKET_TZ)
    # Exclude the currently-forming 5-minute bar. Alerts must be causal and
    # reproducible from data that was complete at decision time.
    completed_through = now_et.replace(
        minute=now_et.minute - (now_et.minute % 5), second=0, microsecond=0
    )
    params: dict[str, Any] = {
        "symbols": ",".join(symbols[:MAX_BAR_SYMBOLS]),
        "timeframe": "5Min",
        "start": start_et.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "end": completed_through.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "adjustment": "raw",
        "feed": "iex",
        "limit": 10000,
        "sort": "asc",
    }
    output: dict[str, list[dict[str, Any]]] = {}
    errors: list[str] = []
    token = None
    for _ in range(4):
        if token:
            params["page_token"] = token
        try:
            response = requests.get("https://data.alpaca.markets/v2/stocks/bars", headers=_credentials(), params=params, timeout=25)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            errors.append(f"alpaca_intraday_bars:{type(exc).__name__}")
            break
        for symbol, rows in (payload.get("bars") or {}).items():
            output.setdefault(str(symbol).upper(), []).extend(row for row in rows or [] if isinstance(row, dict))
        token = payload.get("next_page_token")
        if not token:
            break
    return output, errors


def bar_features(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = []
    for row in rows:
        values = {key: _finite(row.get(key)) for key in ("o", "h", "l", "c", "v")}
        if all(value is not None for value in values.values()):
            values["t"] = row.get("t")
            completed.append(values)
    if len(completed) < 3:
        return {"status": "insufficient_completed_5m_bars", "bars": len(completed)}
    opening = completed[:3]
    opening_high = max(float(row["h"]) for row in opening)
    opening_low = min(float(row["l"]) for row in opening)
    session_high = max(float(row["h"]) for row in completed)
    session_low = min(float(row["l"]) for row in completed)
    close = float(completed[-1]["c"])
    prior_close = float(completed[-2]["c"])
    cumulative_pv = sum(float(row["c"]) * float(row["v"]) for row in completed)
    cumulative_volume = sum(float(row["v"]) for row in completed)
    vwap = cumulative_pv / cumulative_volume if cumulative_volume else None
    range_width = session_high - session_low
    range_position = (close - session_low) / range_width if range_width > 0 else 0.5
    last = completed[-1]
    prior = completed[-2]
    post_opening = completed[3:]
    prior_post_opening = post_opening[:-1]
    tolerance = max(opening_high - opening_low, close * 0.002) * 0.12
    prior_bull_break = any(float(row["c"]) > opening_high for row in prior_post_opening)
    prior_bear_break = any(float(row["c"]) < opening_low for row in prior_post_opening)
    bullish_breakout_close = bool(
        close > opening_high
        and close > float(prior["h"])
        and vwap is not None
        and close > vwap
    )
    bearish_breakdown_close = bool(
        close < opening_low
        and close < float(prior["l"])
        and vwap is not None
        and close < vwap
    )
    bullish_retest_hold = bool(
        prior_bull_break
        and float(last["l"]) <= opening_high + tolerance
        and close > opening_high
        and close > float(last["o"])
        and vwap is not None
        and close > vwap
    )
    bearish_retest_reject = bool(
        prior_bear_break
        and float(last["h"]) >= opening_low - tolerance
        and close < opening_low
        and close < float(last["o"])
        and vwap is not None
        and close < vwap
    )
    if bullish_retest_hold:
        price_action_state, price_action_pattern = "bullish_confirmed", "breakout_retest_hold"
    elif bearish_retest_reject:
        price_action_state, price_action_pattern = "bearish_confirmed", "breakdown_retest_reject"
    elif bullish_breakout_close:
        price_action_state, price_action_pattern = "bullish_confirmed", "breakout_close"
    elif bearish_breakdown_close:
        price_action_state, price_action_pattern = "bearish_confirmed", "breakdown_close"
    else:
        price_action_state, price_action_pattern = "waiting", "no_closed_bar_confirmation"
    return {
        "status": "ok",
        "bars": len(completed),
        "opening_range_high": round(opening_high, 4),
        "opening_range_low": round(opening_low, 4),
        "session_high": round(session_high, 4),
        "session_low": round(session_low, 4),
        "last_close": round(close, 4),
        "prior_close_5m": round(prior_close, 4),
        "last_bar_high": round(float(completed[-1]["h"]), 4),
        "last_bar_low": round(float(completed[-1]["l"]), 4),
        "last_completed_bar_at": completed[-1].get("t"),
        "vwap_proxy": round(vwap, 4) if vwap is not None else None,
        "range_position": round(range_position, 4),
        "session_volume_5m": round(cumulative_volume),
        "above_vwap": bool(vwap is not None and close > vwap),
        "below_vwap": bool(vwap is not None and close < vwap),
        "above_opening_range": close > opening_high,
        "below_opening_range": close < opening_low,
        "price_action_state": price_action_state,
        "price_action_pattern": price_action_pattern,
        "bullish_breakout_close": bullish_breakout_close,
        "bearish_breakdown_close": bearish_breakdown_close,
        "bullish_retest_hold": bullish_retest_hold,
        "bearish_retest_reject": bearish_retest_reject,
    }


def _session_progress(now_et: datetime) -> float:
    start = datetime.combine(now_et.date(), time(9, 30), MARKET_TZ)
    end = datetime.combine(now_et.date(), time(16, 0), MARKET_TZ)
    if now_et <= start:
        return 0.01
    if now_et >= end:
        return 1.0
    return max((now_et - start).total_seconds() / (end - start).total_seconds(), 0.01)


def _percentile_ranks(values: list[float | None], *, higher_is_better: bool = True) -> list[float | None]:
    """Return tie-aware cross-sectional percentile ranks without imputing missing data."""
    available = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not available:
        return [None for _ in values]
    if len(available) == 1:
        return [50.0 if value is not None else None for value in values]

    output: list[float | None] = []
    denominator = len(available) - 1
    for value in values:
        if value is None or not math.isfinite(float(value)):
            output.append(None)
            continue
        numeric = float(value)
        lower = sum(peer < numeric for peer in available)
        equal = sum(peer == numeric for peer in available)
        average_rank = lower + (equal - 1) / 2
        percentile = 100.0 * average_rank / denominator
        output.append(round(percentile if higher_is_better else 100.0 - percentile, 1))
    return output


def _factor_consensus_grade(score: float) -> str:
    if score >= 93:
        return "A+"
    if score >= 87:
        return "A"
    if score >= 80:
        return "A-"
    if score >= 73:
        return "B+"
    if score >= 67:
        return "B"
    if score >= 60:
        return "B-"
    if score >= 50:
        return "C"
    return "D"


def apply_cross_sectional_factor_consensus(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach a read-only, universe-relative factor agreement diagnostic.

    Percentiles are computed only against symbols evaluated in the same radar
    snapshot. The diagnostic is not a probability and has no execution authority.
    """
    enriched = [dict(row) for row in candidates]
    raw_values: dict[str, list[float | None]] = {
        "momentum": [],
        "volume_pace": [],
        "liquidity": [],
        "spread_quality": [],
        "structure": [],
        "discovery_breadth": [],
        "catalyst": [],
    }
    for row in enriched:
        factors = row.get("factor_scores") if isinstance(row.get("factor_scores"), dict) else {}
        raw_values["momentum"].append(_finite(factors.get("magnitude")))
        raw_values["volume_pace"].append(_finite(factors.get("volume_pace")))
        raw_values["liquidity"].append(_finite(factors.get("liquidity")))
        raw_values["spread_quality"].append(_finite(row.get("spread_pct")))
        raw_values["structure"].append(_finite(factors.get("structure")))
        raw_values["discovery_breadth"].append(_finite(factors.get("discovery_breadth")))
        raw_values["catalyst"].append(_finite(factors.get("catalyst")))

    ranks = {
        name: _percentile_ranks(values, higher_is_better=name != "spread_quality")
        for name, values in raw_values.items()
    }
    for index, row in enumerate(enriched):
        available = {
            name: values[index]
            for name, values in ranks.items()
            if values[index] is not None
        }
        weight_total = sum(FACTOR_CONSENSUS_WEIGHTS[name] for name in available)
        score = (
            sum(float(value) * FACTOR_CONSENSUS_WEIGHTS[name] for name, value in available.items()) / weight_total
            if weight_total
            else 0.0
        )
        supporting = sorted(name for name, value in available.items() if float(value) >= 60.0)
        conflicting = sorted(name for name, value in available.items() if float(value) <= 25.0)
        completeness = len(available) / len(FACTOR_CONSENSUS_WEIGHTS)
        row["factor_consensus"] = {
            "status": "complete" if completeness == 1.0 else "partial" if completeness >= 0.5 else "insufficient",
            "score": round(score, 1),
            "grade": _factor_consensus_grade(score),
            "agreement_ratio": round(len(supporting) / len(available), 3) if available else 0.0,
            "data_completeness": round(completeness, 3),
            "cross_section_size": len(enriched),
            "percentile_ranks": available,
            "supporting_factors": supporting,
            "conflicting_factors": conflicting,
            "definition": "same_snapshot_cross_sectional_percentile_agreement_not_probability",
            "authority": "observe_only_no_gate_or_sizing_effect",
        }
    return enriched


def evaluate_candidate(
    discovery: dict[str, Any],
    metrics: dict[str, Any],
    bars: dict[str, Any],
    avg_dollar_volume: float | None,
    articles: list[dict[str, Any]],
    now_et: datetime,
) -> dict[str, Any]:
    symbol = str(discovery.get("symbol") or "UNKNOWN")
    price = _finite(metrics.get("price"))
    change = _finite(metrics.get("gap_return"))
    spread = _finite(metrics.get("spread_pct"))
    current_volume = _finite(metrics.get("snapshot_volume")) or _finite(bars.get("session_volume_5m"))
    current_dollar = current_volume * price if current_volume is not None and price is not None else None
    expected_dollar = (avg_dollar_volume or 0.0) * _session_progress(now_et)
    pace_rvol = current_dollar / expected_dollar if current_dollar is not None and expected_dollar > 0 else None
    range_position = _finite(bars.get("range_position"))
    sources = list(dict.fromkeys(str(item) for item in discovery.get("sources") or []))

    confirmed_direction = str(bars.get("price_action_state") or "")
    direction = (
        "bullish" if confirmed_direction == "bullish_confirmed"
        else "bearish" if confirmed_direction == "bearish_confirmed"
        else "bullish" if (change or 0) >= 0
        else "bearish"
    )
    structure = "unconfirmed"
    if direction == "bullish" and bars.get("above_opening_range") and bars.get("above_vwap"):
        structure = "opening_range_breakout"
    elif direction == "bullish" and bars.get("above_vwap") and (range_position or 0) >= 0.72:
        structure = "trend_continuation"
    elif direction == "bearish" and bars.get("below_opening_range") and bars.get("below_vwap"):
        structure = "opening_range_breakdown"
    elif direction == "bearish" and bars.get("below_vwap") and (range_position or 1) <= 0.28:
        structure = "trend_breakdown"
    elif bars.get("status") == "ok":
        structure = "range_or_reversal_watch"

    gates = {
        "price_floor": price is not None and price >= MIN_PRICE,
        "completed_5m_structure": bars.get("status") == "ok",
        "underlying_spread": spread is not None and spread <= MAX_UNDERLYING_SPREAD_PCT,
        "dollar_liquidity": bool(
            (avg_dollar_volume is not None and avg_dollar_volume >= MIN_AVG_DOLLAR_VOLUME)
            or (current_dollar is not None and current_dollar >= MIN_CURRENT_DOLLAR_VOLUME)
        ),
        "meaningful_move_or_activity": bool(abs(change or 0.0) >= 0.015 or len(sources) >= 2),
    }
    liquidity_score = 0
    if avg_dollar_volume is not None:
        liquidity_score += 45 if avg_dollar_volume >= 500_000_000 else 35 if avg_dollar_volume >= 100_000_000 else 22 if avg_dollar_volume >= MIN_AVG_DOLLAR_VOLUME else 5
    if spread is not None:
        liquidity_score += 35 if spread <= 0.0025 else 25 if spread <= 0.005 else 12 if spread <= MAX_UNDERLYING_SPREAD_PCT else 0
    if current_dollar is not None and current_dollar >= MIN_CURRENT_DOLLAR_VOLUME:
        liquidity_score += 20
    magnitude_score = min(abs(change or 0.0) * 500.0, 100.0)
    activity_score = min((pace_rvol or 0.0) * 35.0, 100.0)
    structure_score = 92.0 if structure in {"opening_range_breakout", "opening_range_breakdown"} else 76.0 if structure in {"trend_continuation", "trend_breakdown"} else 42.0
    source_score = min(38.0 + len(sources) * 16.0, 100.0)
    catalyst_score = 88.0 if articles else 45.0
    score = round(
        0.21 * magnitude_score
        + 0.18 * activity_score
        + 0.23 * structure_score
        + 0.17 * min(liquidity_score, 100.0)
        + 0.13 * source_score
        + 0.08 * catalyst_score,
        1,
    )
    if not all(gates.values()):
        score = min(score, 64.0)
    grade = "A" if score >= 87 else "A-" if score >= 80 else "B+" if score >= 73 else "B" if score >= 67 else "B-" if score >= 60 else "C" if score >= 50 else "D"

    if direction == "bullish":
        if bars.get("price_action_state") == "bullish_confirmed":
            trigger = _finite(bars.get("opening_range_high"))
        else:
            trigger = max(value for value in (_finite(bars.get("last_bar_high")), _finite(bars.get("opening_range_high"))) if value is not None) if bars.get("status") == "ok" else None
        stop_candidates = [
            value for value in (_finite(bars.get("vwap_proxy")), _finite(bars.get("last_bar_low")))
            if value is not None and trigger is not None and value < trigger
        ]
        invalidation = max(stop_candidates) if stop_candidates else None
        risk = trigger - invalidation if trigger is not None and invalidation is not None and trigger > invalidation else None
        target = trigger + 2 * risk if risk else None
    else:
        if bars.get("price_action_state") == "bearish_confirmed":
            trigger = _finite(bars.get("opening_range_low"))
        else:
            trigger = min(value for value in (_finite(bars.get("last_bar_low")), _finite(bars.get("opening_range_low"))) if value is not None) if bars.get("status") == "ok" else None
        stop_candidates = [
            value for value in (_finite(bars.get("vwap_proxy")), _finite(bars.get("last_bar_high")))
            if value is not None and trigger is not None and value > trigger
        ]
        invalidation = min(stop_candidates) if stop_candidates else None
        risk = invalidation - trigger if trigger is not None and invalidation is not None and invalidation > trigger else None
        target = trigger - 2 * risk if risk else None

    gates["directional_level_geometry"] = risk is not None and risk > 0
    if not gates["directional_level_geometry"]:
        score = min(score, 64.0)
        grade = "B-" if score >= 60 else "C" if score >= 50 else "D"

    core_executable = all(
        gates[name]
        for name in ("price_floor", "underlying_spread", "dollar_liquidity", "directional_level_geometry")
    )
    if not core_executable:
        state = "filtered"
    elif score >= 73 and all(gates.values()):
        state = "precision_watch"
    elif score >= 60:
        state = "watch"
    else:
        state = "filtered"

    blockers = [name for name, passed in gates.items() if not passed]
    blockers.append("strategy_confirmation_and_revalidation_required")
    return {
        "symbol": symbol,
        "state": state,
        "grade": grade,
        "score": score,
        "direction": direction,
        "setup": structure,
        "price": round(price, 4) if price is not None else None,
        "change_pct": round((change or 0.0) * 100.0, 3),
        "spread_pct": round(spread * 100.0, 4) if spread is not None else None,
        "avg_dollar_volume_20d": round(avg_dollar_volume) if avg_dollar_volume is not None else None,
        "current_session_dollar_volume": round(current_dollar) if current_dollar is not None else None,
        "volume_pace_rvol_proxy": round(pace_rvol, 3) if pace_rvol is not None else None,
        "discovery_sources": sources,
        "source_ranks": discovery.get("source_ranks") or {},
        "catalyst_available": bool(articles),
        "catalyst_headlines": articles[:3],
        "hard_gates": gates,
        "blockers": blockers,
        "structure": bars,
        "price_action_confirmation": {
            "state": bars.get("price_action_state", "waiting"),
            "pattern": bars.get("price_action_pattern", "no_closed_bar_confirmation"),
            "bar_completed_at": bars.get("last_completed_bar_at"),
            "definition": "closed_5m_opening_range_vwap_break_or_retest_confirmation",
        },
        "trade_levels": {
            "confirmation_trigger": round(trigger, 4) if trigger is not None else None,
            "invalidation": round(invalidation, 4) if invalidation is not None else None,
            "target_2r": round(target, 4) if target is not None else None,
            "instruction": "wait_for_completed_5m_break_and_retest_then_revalidate_quote",
        },
        "factor_scores": {
            "magnitude": round(magnitude_score, 1),
            "volume_pace": round(activity_score, 1),
            "structure": round(structure_score, 1),
            "liquidity": round(min(liquidity_score, 100.0), 1),
            "discovery_breadth": round(source_score, 1),
            "catalyst": round(catalyst_score, 1),
        },
        "execution_enabled": False,
        "can_submit_orders": False,
        "authority": "discovery_and_confirmation_levels_only",
    }


def build_report(now_et: datetime | None = None) -> dict[str, Any]:
    now_et = (now_et or datetime.now(timezone.utc).astimezone(MARKET_TZ)).astimezone(MARKET_TZ)
    regular_session = time(9, 30) <= now_et.time() <= time(16, 5)
    screeners, errors = fetch_market_screeners()
    discovered = discovery_map(screeners)
    broad_news, more_errors = fetch_news(now_et, pages=3)
    errors.extend(more_errors)
    nominate_symbols(discovered, list(news_by_symbol(broad_news)), "fresh_market_news")
    nominate_symbols(discovered, load_social_symbols(now_et.date()), "social_research")
    nominate_symbols(discovered, KNOWN_LEADERS, "known_liquid_leader")
    for source, path, row_keys in REPORT_NOMINATION_SOURCES:
        symbols_from_report = symbols_from_report_payload(_read_json(path), row_keys, now_et.date().isoformat())
        nominate_symbols(discovered, symbols_from_report, source)

    symbols = list(discovered)
    snapshots, more_errors = fetch_snapshots(symbols)
    errors.extend(more_errors)
    metrics = {symbol: snapshot_metrics(snapshot) for symbol, snapshot in snapshots.items()}
    ranked_for_bars = select_symbols_for_intraday_bars(discovered, metrics)
    bars, more_errors = fetch_intraday_bars(ranked_for_bars, now_et)
    errors.extend(more_errors)
    daily_liquidity, more_errors = fetch_daily_liquidity(ranked_for_bars, now_et)
    errors.extend(more_errors)
    symbol_news, more_errors = fetch_news(now_et, symbols=ranked_for_bars)
    errors.extend(more_errors)
    news = broad_news + symbol_news
    news_map = news_by_symbol(news)

    candidates = [
        evaluate_candidate(
            discovered[symbol], metrics.get(symbol, {}), bar_features(bars.get(symbol, [])),
            daily_liquidity.get(symbol), news_map.get(symbol, []), now_et,
        )
        for symbol in ranked_for_bars
    ]
    candidates = apply_cross_sectional_factor_consensus(candidates)
    candidates.sort(
        key=lambda row: (
            float(row.get("score") or 0),
            float((row.get("factor_consensus") or {}).get("score") or 0),
            abs(float(row.get("change_pct") or 0)),
        ),
        reverse=True,
    )
    precision = [row for row in candidates if row.get("state") == "precision_watch"]
    filtered = [row for row in candidates if row.get("state") == "filtered"]
    nomination_source_counts: dict[str, int] = {}
    for item in discovered.values():
        for source in set(item.get("sources") or []):
            nomination_source_counts[source] = nomination_source_counts.get(source, 0) + 1
    return {
        "schema_version": 3,
        "provider": "alpaca_marketwide_intraday_discovery",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "as_of_et": now_et.isoformat(),
        "date": now_et.date().isoformat(),
        "session_status": "regular_session" if regular_session else "outside_regular_session_snapshot",
        "mode": "read_only_discovery",
        "execution_enabled": False,
        "can_submit_orders": False,
        "coverage": {
            "unique_symbols_discovered": len(discovered),
            "snapshot_symbols": len(snapshots),
            "symbols_with_5m_bars": len(bars),
            "symbols_evaluated": len(candidates),
            "precision_watch_count": len(precision),
            "factor_consensus_complete_count": sum(
                (row.get("factor_consensus") or {}).get("status") == "complete" for row in candidates
            ),
            "filtered_count": len(filtered),
            "source_counts": {name: len(rows) for name, rows in screeners.items()},
            "nomination_source_counts": dict(sorted(nomination_source_counts.items())),
            "snapshot_coverage_pct": round(len(snapshots) / len(discovered) * 100.0, 2) if discovered else 0.0,
            "reserved_benchmarks": [symbol for symbol in CORE_BENCHMARKS if symbol in ranked_for_bars],
            "reserved_liquid_core": [symbol for symbol in CORE_LIQUID_SYMBOLS if symbol in ranked_for_bars],
        },
        "market_movers": normalized_movers(screeners),
        "all_discovered_symbols": sorted(discovered),
        "coverage_trace": coverage_trace(discovered, snapshots, ranked_for_bars, bars),
        "precision_watch": precision,
        "ranked_candidates": candidates,
        "filtered_candidates": filtered,
        "errors": errors,
        "operational_health": "ok" if discovered and snapshots and not errors else "degraded",
        "warnings": [
            "Market movers identify moves already underway; they do not predict surprise news.",
            "Standing and report-nominated symbols broaden coverage but do not establish an edge.",
            "Volume pace is a session-progress proxy, not exchange-wide RVOL.",
            "Confirmation levels are watch levels, not orders.",
            "Cross-sectional factor consensus is a relative diagnostic, not probability of profit.",
            "No paper or live order authority.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    _atomic_json(report_path, report)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report()
    write_report(report, args.report_path, args.log_path)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        coverage = report["coverage"]
        print(
            "Intraday radar: "
            f"discovered={coverage['unique_symbols_discovered']} "
            f"evaluated={coverage['symbols_evaluated']} "
            f"precision={coverage['precision_watch_count']} errors={len(report['errors'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
