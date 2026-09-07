#!/usr/bin/env python3
"""Build fail-honest institutional-confluence evidence for shadow decisions.

This adapter never invents options flow, dark-pool activity, dealer positioning,
or order-book data.  It records whether each independent source is actually
available and fresh, while separately measuring repeated completed-bar price
confirmations.  The output is evidence only and has no order authority.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_IMPORT_ROOT = Path(__file__).resolve().parent.parent
if str(_IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(_IMPORT_ROOT))
from scripts.options_nbbo_evidence import analyze


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
ALERTS_PATH = REPORT_DIR / "simple-price-action-alerts.json"
CZT_PATH = REPORT_DIR / "czt-order-flow-shadow.json"
GEX_LOG_PATH = ROOT / "data" / "gex_scan_log.jsonl"
REPORT_PATH = REPORT_DIR / "institutional-confluence-shadow.json"
NBBO_PATH = ROOT / "data" / "databento" / "options_nbbo_candidate_quotes.jsonl"
REPEAT_WINDOW_MINUTES = 10
GEX_MAX_AGE_HOURS = 8
BAR_PROXY_MAX_AGE_MINUTES = 15


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(as_of: datetime, observed_at: Any) -> float | None:
    parsed = _parse_time(observed_at)
    return max(0.0, (as_of - parsed).total_seconds()) if parsed else None


def repeat_confirmation(events: list[dict[str, Any]], candidate: dict[str, Any]) -> dict[str, Any]:
    """Count unique, same-direction completed bars ending at the candidate."""
    end = _parse_time(candidate.get("bar_completed_at"))
    if end is None:
        return {"count": 0, "span_minutes": 0.0, "qualifies": False, "reason": "candidate_time_missing"}
    start = end - timedelta(minutes=REPEAT_WINDOW_MINUTES)
    symbol = str(candidate.get("symbol") or "").upper()
    direction = str(candidate.get("direction") or "").upper()
    timestamps = {
        parsed
        for row in events
        if isinstance(row, dict)
        and row.get("state") == "CONFIRMED"
        and str(row.get("symbol") or "").upper() == symbol
        and str(row.get("direction") or "").upper() == direction
        and (parsed := _parse_time(row.get("bar_completed_at"))) is not None
        and start <= parsed <= end
    }
    ordered = sorted(timestamps)
    span = (ordered[-1] - ordered[0]).total_seconds() / 60.0 if len(ordered) > 1 else 0.0
    return {
        "count": len(ordered),
        "span_minutes": round(span, 2),
        "qualifies": len(ordered) >= 3 and span >= 5.0,
        "window_minutes": REPEAT_WINDOW_MINUTES,
        "provenance": "same_symbol_same_direction_unique_completed_price_bars",
        "independent_source": False,
    }


def _latest_gex(symbol: str, as_of: datetime, rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [row for row in rows if (_parse_time(row.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)) <= as_of]
    latest = max(eligible, key=lambda row: _parse_time(row.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc), default={})
    observed = latest.get("timestamp")
    scan = next((item for item in latest.get("scans") or [] if isinstance(item, dict) and str(item.get("symbol") or "").upper() == symbol), {})
    age = _age_seconds(as_of, observed)
    fresh = age is not None and age <= GEX_MAX_AGE_HOURS * 3600
    available = bool(scan.get("status") == "ok" and fresh and scan.get("gex_wall"))
    direction = str(scan.get("direction") or "").upper()
    if direction not in {"LONG", "SHORT"}:
        direction = None
    return {
        "name": "gamma_open_interest_proxy",
        "available": available,
        "fresh": fresh,
        "observed_at": observed,
        "age_seconds": round(age, 1) if age is not None else None,
        "status": "available" if available else str(scan.get("status") or "missing"),
        "direction": direction,
        "reason": None if available else str(scan.get("error") or ("stale" if scan and not fresh else "missing")),
        "facts": {"gex_wall": scan.get("gex_wall"), "net_gex_regime": scan.get("net_gex_regime"), "open_interest_coverage": scan.get("open_interest_coverage")},
        "independent_source": True,
        "dealer_positioning_observed": False,
    }


def _bar_proxy(symbol: str, direction: str, as_of: datetime, report: dict[str, Any]) -> dict[str, Any]:
    snapshot = next((item for item in report.get("snapshots") or [] if isinstance(item, dict) and str(item.get("symbol") or "").upper() == symbol), {})
    age = _age_seconds(as_of, snapshot.get("as_of"))
    fresh = age is not None and age <= BAR_PROXY_MAX_AGE_MINUTES * 60
    observed_direction = {"CALL": "LONG", "PUT": "SHORT"}.get(str(snapshot.get("shadow_direction") or "").upper())
    available = bool(snapshot and fresh)
    return {
        "name": "ohlcv_condition_zone_trigger_proxy",
        "available": available,
        "fresh": fresh,
        "observed_at": snapshot.get("as_of"),
        "age_seconds": round(age, 1) if age is not None else None,
        "status": "aligned" if available and snapshot.get("czt_aligned") else "available_not_aligned" if available else "stale_or_missing",
        "direction": observed_direction,
        "contradicts_candidate": bool(available and observed_direction and observed_direction != direction),
        "facts": {"condition": snapshot.get("condition"), "trigger": snapshot.get("trigger"), "zone": snapshot.get("zone")},
        "independent_source": False,
        "limitations": "OHLCV-derived and correlated with technical candidate; not true order flow",
    }


def build_report(*, as_of: datetime | None = None, alerts: dict[str, Any] | None = None,
                 gex_rows: list[dict[str, Any]] | None = None, czt: dict[str, Any] | None = None,
                 nbbo_rows: list[dict[str, Any]] | None = None, nbbo_status: str | None = None) -> dict[str, Any]:
    now = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    alerts = alerts if alerts is not None else _read_json(ALERTS_PATH)
    gex_rows = gex_rows if gex_rows is not None else _read_jsonl(GEX_LOG_PATH)
    czt = czt if czt is not None else _read_json(CZT_PATH)
    nbbo_rows = nbbo_rows if nbbo_rows is not None else _read_jsonl(NBBO_PATH)
    events = [row for row in alerts.get("recent_events") or [] if isinstance(row, dict)]
    latest: dict[str, dict[str, Any]] = {}
    for row in events:
        if row.get("state") == "CONFIRMED":
            latest[str(row.get("symbol") or "").upper()] = row
    cards: list[dict[str, Any]] = []
    for symbol, candidate in sorted(latest.items()):
        direction = str(candidate.get("direction") or "").upper()
        candidate_time = _parse_time(candidate.get("bar_completed_at")) or now
        gex = _latest_gex(symbol, candidate_time, gex_rows)
        bar_proxy = _bar_proxy(symbol, direction, candidate_time, czt)
        repeat = repeat_confirmation(events, candidate)
        evidence = analyze(nbbo_rows, symbol, as_of=candidate_time)
        if nbbo_status in {"not_configured", "budget_exceeded", "timeout", "missing"}:
            evidence = {**evidence, "status": nbbo_status, "available": False, "fresh": False, "direction": "NEUTRAL"}
        nbbo_direction = str(evidence.get("direction") or "NEUTRAL")
        nbbo_contradiction = bool(evidence.get("available") and nbbo_direction in {"LONG", "SHORT"} and nbbo_direction != direction)
        nbbo = {
            "name": "nbbo_options_flow", "available": evidence.get("available") is True,
            "fresh": evidence.get("fresh") is True, "observed_at": evidence.get("observed_at").isoformat().replace("+00:00", "Z") if isinstance(evidence.get("observed_at"), datetime) else evidence.get("observed_at"),
            "age_seconds": evidence.get("age_seconds"),
            "status": "contradicts" if nbbo_contradiction else "aligned" if evidence.get("available") and nbbo_direction == direction else "neutral" if evidence.get("available") else str(evidence.get("status") or "missing"),
            "direction": nbbo_direction, "contradicts_candidate": nbbo_contradiction,
            "facts": {**(evidence.get("evidence_numeric") or {}), "aligned_signal_count": evidence.get("aligned_signal_count"), "quote_contract_count": evidence.get("quote_contract_count")},
            "unusual_prints": evidence.get("unusual_prints") or [], "independent_source": True,
            "reason": None if evidence.get("available") else str(evidence.get("status") or "missing"),
            "limitations": evidence.get("limitations"), "execution_enabled": False, "can_submit_orders": False,
        }
        unavailable = [
            {"name": "dark_pool_prints", "available": False, "fresh": False, "reason": "no_verified_normalized_feed", "independent_source": True},
            {"name": "vanna_exposure", "available": False, "fresh": False, "reason": "no_verified_normalized_feed", "independent_source": True},
        ]
        sources = [gex, bar_proxy, nbbo, *unavailable]
        independent_available = sum(bool(source.get("available") and source.get("fresh") and source.get("independent_source")) for source in sources)
        independent_aligned = sum(bool(source.get("available") and source.get("fresh") and source.get("independent_source") and source.get("direction") == direction) for source in sources)
        contradictions = [source["name"] for source in sources if source.get("contradicts_candidate")]
        recommendation = "contradiction_observed" if contradictions else "confluence_observed" if independent_aligned >= 2 else "insufficient_independent_evidence"
        cards.append({
            "symbol": symbol,
            "direction": direction,
            "candidate_bar_completed_at": candidate.get("bar_completed_at"),
            "repeat_confirmation": repeat,
            "sources": sources,
            "independent_sources_available": independent_available,
            "independent_sources_aligned": independent_aligned,
            "independent_sources_required_for_confluence": 2,
            "contradictions": contradictions,
            "recommendation": recommendation,
            "alert_visibility_preserved": True,
            "execution_enabled": False,
            "can_submit_orders": False,
        })
    return {
        "provider": "institutional_confluence_shadow",
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "mode": "shadow_evidence_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "cards": cards,
        "summary": {
            "candidates": len(cards),
            "confluence_observed": sum(card["recommendation"] == "confluence_observed" for card in cards),
            "insufficient_independent_evidence": sum(card["recommendation"] == "insufficient_independent_evidence" for card in cards),
            "contradictions": sum(bool(card["contradictions"]) for card in cards),
            "repeat_confirmed": sum(bool(card["repeat_confirmation"]["qualifies"]) for card in cards),
        },
        "warnings": [
            "Missing institutional feeds remain unavailable; they are never inferred from price bars.",
            "Repeated price confirmations improve timing context but are not independent evidence.",
            "This report cannot suppress scanner visibility or submit orders.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    if args.print_output:
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
