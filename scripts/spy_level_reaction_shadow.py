#!/usr/bin/env python3
"""Shadow-only SPY mapped-level reaction monitor.

The monitor preserves pre-session levels (previous RTH high/low and premarket
high/low), adds completed-session opening-range/VWAP context, and classifies
only *completed five-minute-bar* reactions.  It is intentionally not an
options-pricing model: underlying reactions do not imply a specific 0DTE
premium return and cannot authorize an order.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.premarket_opportunity_radar import _credentials, _finite


ET = ZoneInfo("America/New_York")
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "spy-level-reaction-shadow.json"
LOG_PATH = ROOT / "data" / "spy_level_reaction_shadow_log.jsonl"
REACTION_LEDGER_PATH = ROOT / "data" / "spy_level_reaction_candidates.jsonl"
BREADTH_REPORT_PATH = VIBE_HOME / "reports" / "market-breadth-uptrend.json"
INTRADAY_RADAR_REPORT_PATH = VIBE_HOME / "reports" / "intraday-opportunity-radar.json"
SYMBOL = "SPY"
TOUCH_TOLERANCE_POINTS = 0.05
MIN_REACTION_POINTS = 0.40
MAX_REACTION_POINTS = 0.80


def _parse_timestamp(value: Any) -> datetime | None:
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


def _completed_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    completed: list[dict[str, Any]] = []
    for row in rows:
        values = {key: _finite(row.get(key)) for key in ("o", "h", "l", "c", "v")}
        timestamp = _parse_timestamp(row.get("t") or row.get("timestamp"))
        if timestamp is None or any(value is None for value in values.values()):
            continue
        completed.append({"timestamp": timestamp, **{key: float(value) for key, value in values.items()}})
    return sorted(completed, key=lambda row: row["timestamp"])


def _vwap(rows: list[dict[str, Any]]) -> float | None:
    total_volume = sum(row["v"] for row in rows)
    if total_volume <= 0:
        return None
    return sum(((row["h"] + row["l"] + row["c"]) / 3.0) * row["v"] for row in rows) / total_volume


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def build_gap_context(rows: Iterable[Mapping[str, Any]], *, now_et: datetime) -> dict[str, Any]:
    """Freeze an opening-gap state without asserting that a gap must fill."""
    now_et = now_et.astimezone(ET)
    bars = _completed_rows(rows)
    today = now_et.date()
    rth_today = [row for row in bars if row["timestamp"].date() == today and time(9, 30) <= row["timestamp"].time() < time(16, 0)]
    prior_rth = [row for row in bars if row["timestamp"].date() < today and time(9, 30) <= row["timestamp"].time() < time(16, 0)]
    prior_date = max((row["timestamp"].date() for row in prior_rth), default=None)
    prior_session = [row for row in prior_rth if row["timestamp"].date() == prior_date]
    if not rth_today or not prior_session:
        return {
            "status": "unavailable", "fill_bucket": "unavailable", "authority": "context_only_no_prediction",
            "reason": "completed_current_and_prior_rth_required",
        }

    prior_close = float(prior_session[-1]["c"])
    opening_bar = rth_today[0]
    opening_price = float(opening_bar["o"])
    gap_points = opening_price - prior_close
    gap_pct = gap_points / prior_close * 100.0 if prior_close else None
    tolerance = TOUCH_TOLERANCE_POINTS
    filled_bar: dict[str, Any] | None = None
    if abs(gap_points) <= tolerance:
        fill_state, fill_bucket = "flat_open", "flat_open"
    else:
        for bar in rth_today:
            if bar["l"] <= prior_close + tolerance and bar["h"] >= prior_close - tolerance:
                filled_bar = bar
                break
        if filled_bar is None:
            fill_state, fill_bucket = "unfilled_as_of_completed_bar", "unfilled"
        else:
            elapsed = int((filled_bar["timestamp"] - opening_bar["timestamp"]).total_seconds() // 60) + 5
            fill_state = "filled"
            fill_bucket = (
                "filled_within_15m" if elapsed <= 15 else "filled_within_30m" if elapsed <= 30
                else "filled_within_60m" if elapsed <= 60 else "filled_after_60m"
            )
    return {
        "status": "available",
        "prior_rth_close": round(prior_close, 4),
        "opening_price": round(opening_price, 4),
        "gap_points": round(gap_points, 4),
        "gap_pct": round(gap_pct, 4) if gap_pct is not None else None,
        "gap_direction": "up" if gap_points > tolerance else "down" if gap_points < -tolerance else "flat",
        "opening_bar_at": opening_bar["timestamp"].isoformat(),
        "fill_state": fill_state,
        "fill_bucket": fill_bucket,
        "fill_observed_at": filled_bar["timestamp"].isoformat() if filled_bar else None,
        "minutes_to_fill": (
            int((filled_bar["timestamp"] - opening_bar["timestamp"]).total_seconds() // 60) + 5
            if filled_bar else None
        ),
        "authority": "context_only_no_prediction",
        "warning": "Gap state is logged for outcome slicing; it never predicts that price must fill the prior close.",
    }


def breadth_context_from_report(payload: Mapping[str, Any], *, session_date: str) -> dict[str, Any]:
    """Carry a provenance-tagged breadth vector as a challenger, never a gate."""
    breadth = payload.get("breadth") if isinstance(payload.get("breadth"), Mapping) else {}
    if not breadth or breadth.get("status") != "ok":
        return {
            "status": "unavailable", "regime": "unavailable", "authority": "challenger_only_no_gate_or_sizing_effect",
            "reason": "breadth_report_missing_or_invalid",
        }
    report_date = str(payload.get("date") or breadth.get("as_of") or "")
    freshness = "same_session" if report_date == session_date else "prior_session"
    return {
        "status": "available" if freshness == "same_session" else "stale_context",
        "report_date": report_date or None,
        "freshness": freshness,
        "regime": str(breadth.get("uptrend_status") or "unknown"),
        "pct_above_20dma": _finite(breadth.get("pct_above_20dma")),
        "pct_above_50dma": _finite(breadth.get("pct_above_50dma")),
        "pct_above_200dma": _finite(breadth.get("pct_above_200dma")),
        "advancer_pct": _finite(breadth.get("advancer_pct")),
        "leadership_count": _finite(breadth.get("leadership_count")),
        "defensive_outperformer_count": _finite(breadth.get("defensive_outperformer_count")),
        "authority": "challenger_only_no_gate_or_sizing_effect",
        "warning": "Breadth is retained for a frozen outcome comparison and cannot create, block, or size a setup.",
    }


def intermarket_context_from_radar(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Read the radar's central QQQ/SPY and sector snapshot without recomputing it."""
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), Mapping) else {}
    context = coverage.get("market_context_snapshot") if isinstance(coverage.get("market_context_snapshot"), Mapping) else {}
    if not context:
        return {
            "status": "unavailable", "authority": "context_only_no_gate_or_sizing_effect",
            "reason": "intraday_radar_context_snapshot_missing",
        }
    copied = dict(context)
    copied["authority"] = "context_only_no_gate_or_sizing_effect"
    copied["source_generated_at"] = payload.get("generated_at")
    return copied


def build_level_map(rows: Iterable[Mapping[str, Any]], *, now_et: datetime) -> dict[str, Any]:
    """Map only price levels knowable no later than the current completed bar."""
    now_et = now_et.astimezone(ET)
    bars = _completed_rows(rows)
    today = now_et.date()
    current = [row for row in bars if row["timestamp"].date() == today]
    premarket = [row for row in current if time(4, 0) <= row["timestamp"].time() < time(9, 30)]
    rth = [row for row in current if time(9, 30) <= row["timestamp"].time() < time(16, 0)]
    prior_rth = [row for row in bars if row["timestamp"].date() < today and time(9, 30) <= row["timestamp"].time() < time(16, 0)]
    prior_date = max((row["timestamp"].date() for row in prior_rth), default=None)
    prior_session = [row for row in prior_rth if row["timestamp"].date() == prior_date]

    levels: list[dict[str, Any]] = []

    def add(name: str, price: float | None, role: str, source: str) -> None:
        if price is not None:
            levels.append({"name": name, "price": round(price, 4), "role": role, "source": source})

    add("previous_day_high", max((row["h"] for row in prior_session), default=None), "resistance", "completed_prior_rth")
    add("previous_day_low", min((row["l"] for row in prior_session), default=None), "support", "completed_prior_rth")
    add("premarket_high", max((row["h"] for row in premarket), default=None), "resistance", "completed_premarket")
    add("premarket_low", min((row["l"] for row in premarket), default=None), "support", "completed_premarket")
    opening = rth[:3]
    add("opening_range_high", max((row["h"] for row in opening), default=None), "resistance", "first_15m_rth")
    add("opening_range_low", min((row["l"] for row in opening), default=None), "support", "first_15m_rth")
    vwap = _vwap(rth)
    add("rth_vwap", vwap, "two_sided", "completed_rth_volume_proxy")

    return {
        "status": "available" if rth else "waiting_for_rth_completed_bar",
        "as_of_et": rth[-1]["timestamp"].isoformat() if rth else None,
        "prior_session_date": prior_date.isoformat() if prior_date else None,
        "levels": levels,
        "rth_completed_bar_count": len(rth),
        "premarket_completed_bar_count": len(premarket),
        "vwap_is_bar_volume_proxy": True,
    }


def classify_reactions(level_map: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Classify the most recent completed-bar reaction at each mapped level."""
    bars = _completed_rows(rows)
    if not bars:
        return []
    last = bars[-1]
    reactions: list[dict[str, Any]] = []
    for level in level_map.get("levels") or []:
        if not isinstance(level, Mapping):
            continue
        price = _finite(level.get("price"))
        role = str(level.get("role") or "")
        if price is None:
            continue
        direction: str | None = None
        reaction_points: float | None = None
        touched = False
        if role in {"support", "two_sided"} and last["l"] <= price + TOUCH_TOLERANCE_POINTS and last["c"] > price and last["c"] > last["o"]:
            direction, touched, reaction_points = "bullish", True, last["c"] - price
        if role in {"resistance", "two_sided"} and last["h"] >= price - TOUCH_TOLERANCE_POINTS and last["c"] < price and last["c"] < last["o"]:
            candidate_points = price - last["c"]
            if reaction_points is None or candidate_points > reaction_points:
                direction, touched, reaction_points = "bearish", True, candidate_points
        if not touched or direction is None or reaction_points is None:
            continue
        if MIN_REACTION_POINTS <= reaction_points <= MAX_REACTION_POINTS:
            status = "CONFIRMED_REACTION"
        elif reaction_points > MAX_REACTION_POINTS:
            status = "EXTENDED_NO_CHASE"
        else:
            status = "TOUCHED_WAIT_FOR_REACTION"
        reactions.append({
            "level_name": str(level.get("name") or "mapped_level"),
            "level": round(price, 4),
            "level_role": role,
            "level_source": str(level.get("source") or "unknown"),
            "direction": direction,
            "status": status,
            "reaction_points": round(reaction_points, 4),
            "observed_at": last["timestamp"].isoformat(),
            "decision_available_at": (last["timestamp"] + timedelta(minutes=5)).isoformat(),
            "bar_basis": "completed_5m_only",
            "required_reaction_range_points": [MIN_REACTION_POINTS, MAX_REACTION_POINTS],
            "execution_enabled": False,
            "can_submit_orders": False,
        })
    rank = {"CONFIRMED_REACTION": 0, "TOUCHED_WAIT_FOR_REACTION": 1, "EXTENDED_NO_CHASE": 2}
    return sorted(reactions, key=lambda row: (rank[row["status"]], -row["reaction_points"], row["level_name"]))


def evaluate_rows(
    rows: Iterable[Mapping[str, Any]], *, now_et: datetime,
    breadth_context: Mapping[str, Any] | None = None,
    intermarket_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    level_map = build_level_map(rows, now_et=now_et)
    reactions = classify_reactions(level_map, rows)
    confirmed = [row for row in reactions if row["status"] == "CONFIRMED_REACTION"]
    return {
        "schema_version": 2,
        "provider": "spy_mapped_level_reaction_shadow",
        "symbol": SYMBOL,
        "date": now_et.astimezone(ET).date().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "shadow_research_only",
        "level_map": level_map,
        "gap_context": build_gap_context(rows, now_et=now_et),
        "breadth_context": dict(breadth_context or {
            "status": "unavailable", "regime": "unavailable",
            "authority": "challenger_only_no_gate_or_sizing_effect",
        }),
        "intermarket_context": dict(intermarket_context or {
            "status": "unavailable", "authority": "context_only_no_gate_or_sizing_effect",
        }),
        "reactions": reactions,
        "active_reactions": confirmed,
        "summary": {
            "confirmed_reactions": len(confirmed),
            "extended_no_chase": sum(row["status"] == "EXTENDED_NO_CHASE" for row in reactions),
            "waiting_for_minimum_reaction": sum(row["status"] == "TOUCHED_WAIT_FOR_REACTION" for row in reactions),
        },
        "limitations": [
            "Underlying SPY reactions are not an options-premium model and do not imply a 15-25% 0DTE result.",
            "Only completed five-minute bars qualify; a touch alone is not a confirmation.",
            "A reaction beyond the configured $0.80 maximum is labelled no-chase, not upgraded.",
            "Gap, breadth, QQQ/SPY, and sector observations are frozen context for outcome slices, not trade triggers or ranking gates.",
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def fetch_spy_bars(now_et: datetime) -> list[dict[str, Any]]:
    now_et = now_et.astimezone(ET)
    completed_through = now_et.replace(minute=now_et.minute - now_et.minute % 5, second=0, microsecond=0)
    if completed_through <= datetime.combine(now_et.date(), time(9, 30), ET):
        return []
    start = datetime.combine(now_et.date() - timedelta(days=7), time(4, 0), ET)
    response = requests.get(
        "https://data.alpaca.markets/v2/stocks/bars",
        headers=_credentials(),
        params={
            "symbols": SYMBOL, "timeframe": "5Min",
            "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "end": completed_through.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "adjustment": "raw", "feed": "iex", "limit": 10000, "sort": "asc",
        },
        timeout=25,
    )
    response.raise_for_status()
    payload = response.json()
    return [row for row in (payload.get("bars") or {}).get(SYMBOL, []) if isinstance(row, dict)]


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _event_id(reaction: Mapping[str, Any]) -> str:
    material = "|".join(
        str(reaction.get(key) or "")
        for key in ("decision_available_at", "level_name", "direction", "status", "level")
    )
    return "spy-level-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _existing_event_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    identifiers: set[str] = set()
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if isinstance(row, Mapping) and row.get("candidate_id"):
                identifiers.add(str(row["candidate_id"]))
    except (OSError, ValueError, TypeError):
        return identifiers
    return identifiers


def append_reaction_events(report: Mapping[str, Any], *, ledger_path: Path = REACTION_LEDGER_PATH) -> int:
    """Append new completed-bar observations once, durably, for later outcome research."""
    seen = _existing_event_ids(ledger_path)
    events: list[dict[str, Any]] = []
    for reaction in report.get("reactions") or []:
        if not isinstance(reaction, Mapping):
            continue
        candidate_id = _event_id(reaction)
        if candidate_id in seen:
            continue
        events.append({
            "schema_version": 1,
            "candidate_id": candidate_id,
            "provider": "spy_mapped_level_reaction_shadow",
            "symbol": SYMBOL,
            "captured_at": report.get("generated_at"),
            "date": report.get("date"),
            "reaction": dict(reaction),
            "gap_context": dict(report.get("gap_context") or {}),
            "breadth_context": dict(report.get("breadth_context") or {}),
            "intermarket_context": dict(report.get("intermarket_context") or {}),
            "eligible_for_outcome_comparison": reaction.get("status") == "CONFIRMED_REACTION",
            "execution_enabled": False,
            "can_submit_orders": False,
        })
    if not events:
        return 0
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return len(events)


def write_report(
    report: Mapping[str, Any], *, report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH,
    event_ledger_path: Path = REACTION_LEDGER_PATH,
) -> int:
    appended = append_reaction_events(report, ledger_path=event_ledger_path)
    if isinstance(report, dict):
        report["new_reaction_event_count"] = appended
    _write_atomic(report_path, report)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(report), separators=(",", ":"), sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return appended


def build_report(now_et: datetime | None = None) -> dict[str, Any]:
    now_et = (now_et or datetime.now(ET)).astimezone(ET)
    try:
        report = evaluate_rows(
            fetch_spy_bars(now_et), now_et=now_et,
            breadth_context=breadth_context_from_report(_read_json(BREADTH_REPORT_PATH), session_date=now_et.date().isoformat()),
            intermarket_context=intermarket_context_from_radar(_read_json(INTRADAY_RADAR_REPORT_PATH)),
        )
        report["operational_health"] = "ok"
        return report
    except Exception as exc:
        return {
            "schema_version": 1, "provider": "spy_mapped_level_reaction_shadow", "symbol": SYMBOL,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "mode": "shadow_research_only", "operational_health": "degraded",
            "error": f"{type(exc).__name__}: {str(exc)[:200]}", "reactions": [], "active_reactions": [],
            "execution_enabled": False, "can_submit_orders": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--event-ledger-path", type=Path, default=REACTION_LEDGER_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report()
    write_report(report, report_path=args.report_path, log_path=args.log_path, event_ledger_path=args.event_ledger_path)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("operational_health") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
