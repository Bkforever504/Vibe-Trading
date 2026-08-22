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
from collections import defaultdict
from datetime import datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.intraday_opportunity_radar import bar_features, fetch_intraday_bars
from scripts.market_data_provider_registry import build_provider_registry
from scripts.market_structure_intelligence import PATTERN_CATALOG, analyze_market_structure


MARKET_TZ = ZoneInfo("America/New_York")
DEFAULT_REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "live-opportunity-engine.json"
DEFAULT_RADAR_PATH = Path.home() / ".vibe-trading" / "reports" / "intraday-opportunity-radar.json"
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
    stamp = _utc(quote.get("timestamp") or quote.get("t"))
    midpoint = (bid + ask) / 2 if bid is not None and ask is not None and ask >= bid else None
    spread_bps = (ask - bid) / midpoint * 10_000 if midpoint and bid is not None and ask is not None else None
    age = max(0.0, (now - stamp).total_seconds()) if stamp else None
    freshness = "live" if age is not None and age <= 5 else "recent" if age is not None and age <= MAX_QUOTE_AGE_SECONDS else "stale" if stamp else "missing"
    return {
        "bid": bid,
        "ask": ask,
        "midpoint": round(midpoint, 4) if midpoint is not None else None,
        "spread_bps": round(spread_bps, 2) if spread_bps is not None else None,
        "timestamp": stamp.isoformat().replace("+00:00", "Z") if stamp else None,
        "age_seconds": round(age, 2) if age is not None else None,
        "freshness": freshness,
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
    aliases = {"1h": "60m", "1day": "1d", "1week": "1w"}
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

    def __init__(self, *, feed: str = "iex") -> None:
        self.feed = feed if feed in {"iex", "sip"} else "iex"
        self.transport = "websocket"
        self._symbols: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

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

    def update_quote(self, symbol: str, quote: dict[str, Any]) -> None:
        with self._lock:
            state = self._symbols.setdefault(symbol.upper(), {"bars": []})
            state["quote"] = dict(quote)

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

    def _candidates_for(self, symbol: str, state: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
        rows = _bars_normalized(state.get("bars") or [])
        if len(rows) < 3:
            return []
        features = bar_features(rows)
        quote = _quote_context(state.get("quote") or {}, now)
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
                )
            market_structure = structure_by_direction[direction]
            if context_source_labels:
                market_structure["source_labels"] = list(dict.fromkeys([*market_structure["source_labels"], *context_source_labels]))
            blockers: list[str] = []
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
                "bar_completed_at": features.get("last_completed_bar_at"),
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
                **geometry,
                "execution_enabled": False,
                "can_submit_orders": False,
            }
            output.append(row)
        return output

    def snapshot(self, *, now: datetime | None = None) -> dict[str, Any]:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self._lock:
            candidates = [
                row
                for symbol, state in sorted(self._symbols.items())
                for row in self._candidates_for(symbol, state, now)
            ]
            quote_times = [
                str((state.get("quote") or {}).get("timestamp") or (state.get("quote") or {}).get("t") or "")
                for state in self._symbols.values()
            ]
            structure_watchlist = []
            for symbol, state in sorted(self._symbols.items()):
                rows = _bars_normalized(state.get("bars") or [])
                quote = _quote_context(state.get("quote") or {}, now)
                session_dollar = sum(float(row["c"]) * float(row["v"]) for row in rows)
                average_dollar = _finite(state.get("average_dollar_volume"))
                rvol = session_dollar / (average_dollar * _session_progress(now)) if average_dollar and average_dollar > 0 else None
                analysis = analyze_market_structure(
                    rows,
                    quote=quote,
                    rvol=rvol,
                    average_dollar_volume=average_dollar,
                    higher_timeframes=state.get("higher_timeframes") or None,
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
                    "participation_context": analysis["participation_context"],
                    "macro_context": analysis["macro_context"],
                    "freshness": analysis["freshness"],
                    "source_labels": analysis["source_labels"],
                    "execution_enabled": False,
                    "can_submit_orders": False,
                })
        candidates.sort(key=lambda row: (-float(row["decision_score"]), row["symbol"], row["setup_family"]))
        ready = [row for row in candidates if row["state"] == "READY_TO_REVIEW"]
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


def project_radar_report(radar: dict[str, Any], *, feed: str = "iex") -> dict[str, Any]:
    """Project the existing scheduled radar into the canonical stream schema."""
    candidates: list[dict[str, Any]] = []
    for source in radar.get("ranked_candidates") or []:
        if not isinstance(source, dict):
            continue
        levels = source.get("trade_levels") if isinstance(source.get("trade_levels"), dict) else {}
        setup = str(source.get("setup") or "").lower()
        family = "opening_range_break_retest" if "opening_range" in setup else "relative_weakness_breakdown" if source.get("direction") == "bearish" else "vwap_reclaim_pullback"
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
    return {
        symbol: {
            timeframe: context[timeframe].get(symbol) or []
            for timeframe in ("15m", "30m", "60m", "1d", "1w")
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
    next_bar_refresh = 0.0
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
            snapshot = engine.snapshot()
            snapshot["stream_status"] = "rest_polling_fallback"
            snapshot["stream_fallback_reason"] = "alpaca_websocket_connection_limit"
            _atomic_json(report_path, snapshot)
        except Exception as exc:
            failure = engine.snapshot()
            failure["stream_status"] = "rest_polling_degraded"
            failure["stream_error"] = type(exc).__name__
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
    aggregator = FiveMinuteAggregator()
    delay = 1.0
    while not stop.is_set():
        try:
            ws = websocket.create_connection(build_feed_provenance({"VIBE_TRADING_STOCK_FEED": engine.feed})["endpoint"], timeout=20)
            _receive_control(ws, expected_type="success", expected_message="connected")
            ws.send(json.dumps({"action": "auth", "key": key, "secret": secret}))
            _receive_control(ws, expected_type="success", expected_message="authenticated")
            ws.send(json.dumps({"action": "subscribe", "quotes": symbols, "bars": symbols}))
            _receive_control(ws, expected_type="subscription")
            delay = 1.0
            last_write = 0.0
            while not stop.is_set():
                messages = json.loads(ws.recv())
                for message in messages if isinstance(messages, list) else [messages]:
                    if not isinstance(message, dict):
                        continue
                    if message.get("T") == "error":
                        raise RuntimeError(f"alpaca_stream_error_{message.get('code', 'unknown')}")
                    symbol = str(message.get("S") or "").upper()
                    if message.get("T") == "q" and symbol:
                        engine.update_quote(symbol, {"bid": message.get("bp"), "ask": message.get("ap"), "timestamp": message.get("t")})
                    elif message.get("T") == "b" and symbol:
                        completed = aggregator.add(symbol, message)
                        if completed:
                            engine.update_completed_bar(symbol, completed)
                if time.monotonic() - last_write >= 2.0:
                    snapshot = engine.snapshot()
                    snapshot["stream_status"] = "connected"
                    _atomic_json(report_path, snapshot)
                    last_write = time.monotonic()
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
    engine = LiveOpportunityEngine(feed=args.feed)
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
        )
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    return run_stream(engine, symbols, report_path=args.report_path, stop_event=stop)


if __name__ == "__main__":
    raise SystemExit(main())
