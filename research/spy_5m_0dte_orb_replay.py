#!/usr/bin/env python3
"""Preregistered replay for the published 5-minute SPY 0DTE ORB hypothesis.

This is deliberately a research harness, not a trade signal. It detects the
first closed-minute break of the 09:30--09:35 range and evaluates an option
path only when the caller supplies timestamped bid/ask quotes. Bare option
bars, midpoint assumptions, and missing paths remain non-executable evidence.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "spy-5m-0dte-orb-shadow.json"
ET = ZoneInfo("America/New_York")
MWF = {0, 2, 4}
COMMISSION_ROUND_TRIP = 1.32


def _stamp(value: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp.replace(tzinfo=ET) if stamp.tzinfo is None else stamp.astimezone(ET)


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _bars(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in rows:
        stamp = _stamp(raw.get("t") or raw.get("timestamp"))
        values = {key: _number(raw.get(key) if key in raw else raw.get({"o": "open", "h": "high", "l": "low", "c": "close"}[key])) for key in ("o", "h", "l", "c")}
        if stamp is None or any(value is None for value in values.values()):
            continue
        result.append({"t": stamp, **{key: float(value) for key, value in values.items()}})
    return sorted(result, key=lambda row: row["t"])


def detect_signals(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return one causal first-break signal per eligible M/W/F session."""
    bars = _bars(rows)
    by_day: dict[Any, list[dict[str, Any]]] = {}
    for bar in bars:
        by_day.setdefault(bar["t"].date(), []).append(bar)
    signals: list[dict[str, Any]] = []
    for day, session in sorted(by_day.items()):
        if day.weekday() not in MWF:
            continue
        rth = [bar for bar in session if time(9, 30) <= bar["t"].time() < time(16, 0)]
        opening = [bar for bar in rth if time(9, 30) <= bar["t"].time() < time(9, 35)]
        later = [bar for bar in rth if bar["t"].time() >= time(9, 35)]
        if len(opening) != 5 or not later:
            continue
        high, low = max(bar["h"] for bar in opening), min(bar["l"] for bar in opening)
        for bar in later:
            direction = "call" if bar["c"] > high else "put" if bar["c"] < low else None
            if direction is None:
                continue
            decision_at = bar["t"] + timedelta(minutes=1)
            signals.append({
                "date": day.isoformat(),
                "signal_bar_completed_at": decision_at.isoformat(),
                "direction": direction,
                "opening_range_high": round(high, 4),
                "opening_range_low": round(low, 4),
                "underlying_break_close": round(bar["c"], 4),
                "contract_selection": "ATM_0DTE_at_decision_time_required",
                "status": "awaiting_timestamped_option_bid_ask",
                "authority": "shadow_replay_only_no_rank_alert_sizing_or_execution_authority",
                "execution_enabled": False,
                "can_submit_orders": False,
            })
            break
    return signals


def replay_option_path(signal: Mapping[str, Any], quotes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Evaluate +100%/-50% premium exits using executable quote sides only."""
    decision_at = _stamp(signal.get("signal_bar_completed_at"))
    if decision_at is None:
        return {"status": "unavailable", "reason": "invalid_signal_timestamp"}
    path = []
    for raw in quotes:
        stamp = _stamp(raw.get("t") or raw.get("timestamp"))
        bid, ask = _number(raw.get("bid")), _number(raw.get("ask"))
        if stamp is None or bid is None or ask is None or bid <= 0 or ask < bid:
            continue
        if stamp >= decision_at:
            path.append({"t": stamp, "bid": bid, "ask": ask})
    if not path:
        return {"status": "unavailable", "reason": "timestamped_option_bid_ask_required"}
    entry = path[0]["ask"]
    target, stop = entry * 2.0, entry * 0.5
    exit_quote, outcome = path[-1], "time_stop_or_path_end"
    for quote in path[1:]:
        # A quote may cross both thresholds between samples. Stop-first is the
        # conservative, preregistered resolution rather than a favorable fill.
        if quote["bid"] <= stop:
            exit_quote, outcome = quote, "stop"
            break
        if quote["bid"] >= target:
            exit_quote, outcome = quote, "target"
            break
        if quote["t"].time() >= time(15, 30):
            exit_quote, outcome = quote, "time_stop"
            break
    exit_bid = exit_quote["bid"]
    pnl = (exit_bid - entry) * 100.0 - COMMISSION_ROUND_TRIP
    return {
        "status": "resolved_executable_quote_path",
        "entry_at": path[0]["t"].isoformat(),
        "entry_ask": round(entry, 4),
        "exit_at": exit_quote["t"].isoformat(),
        "exit_bid": round(exit_bid, 4),
        "outcome": outcome,
        "gross_return_pct": round((exit_bid / entry - 1.0) * 100.0, 3),
        "net_return_pct_after_commission": round(((exit_bid - entry) * 100.0 - COMMISSION_ROUND_TRIP) / (entry * 100.0) * 100.0, 3),
        "pnl_dollars_per_contract": round(pnl, 2),
        "quote_method": "timestamped_bid_entry_ask_exit_bid",
    }


def build_report(underlying_rows: Iterable[Mapping[str, Any]], option_quotes: Mapping[str, Iterable[Mapping[str, Any]]] | None = None) -> dict[str, Any]:
    signals = detect_signals(underlying_rows)
    option_quotes = option_quotes or {}
    outcomes: list[dict[str, Any]] = []
    for signal in signals:
        key = f"{signal['date']}|{signal['direction']}"
        outcomes.append({**signal, "option_outcome": replay_option_path(signal, option_quotes.get(key, []))})
    resolved = [row for row in outcomes if row["option_outcome"].get("status") == "resolved_executable_quote_path"]
    return {
        "schema_version": 1,
        "provider": "spy_5m_0dte_orb_replay",
        "mode": "shadow_replay_only",
        "published_rule_source": "Options Cafe 5-minute SPY 0DTE ORB; independently specified for replay",
        "rules": {
            "opening_range": "09:30-09:35 ET completed one-minute bars",
            "entry": "first closed-minute break, decision available the following minute",
            "sessions": "Monday/Wednesday/Friday only as a frozen challenger",
            "option_exit": "-50% bid stop, +100% bid target, 15:30 ET time stop",
            "same_quote_priority": "stop_before_target",
        },
        "signal_count": len(signals),
        "resolved_option_quote_paths": len(resolved),
        "outcomes": outcomes,
        "promotion_blockers": [
            "minimum_30_forward_or_chronological_holdout_sessions_required",
            "licensed_opra_nbbo_or_equivalent_executable_quote_coverage_required",
            "independent_cost_aware_replay_required",
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="JSON with underlying_bars and optional option_quotes_by_signal")
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    report = build_report(payload.get("underlying_bars") or [], payload.get("option_quotes_by_signal") or {})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"signals": report["signal_count"], "resolved": report["resolved_option_quote_paths"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
