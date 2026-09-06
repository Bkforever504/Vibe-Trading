#!/usr/bin/env python3
"""Reconcile governed decisions against post-decision completed bars."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.intraday_opportunity_radar import _credentials

VIBE_HOME = Path.home() / ".vibe-trading"
DECISION_LEDGER_PATH = ROOT / "data" / "governed_shadow_decision_ledger.jsonl"
OUTCOME_LEDGER_PATH = VIBE_HOME / "data" / "governed_shadow_outcomes.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "governed-shadow-outcomes.json"
ET = ZoneInfo("America/New_York")
HORIZON_MINUTES = 60


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
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


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolution_end(opened: datetime) -> tuple[datetime, bool]:
    normal_end = opened + timedelta(minutes=HORIZON_MINUTES)
    local = opened.astimezone(ET)
    close = datetime.combine(local.date(), time(16, 0), ET).astimezone(timezone.utc)
    return (max(close, opened), True) if close < normal_end else (normal_end, False)


def ready_decisions(decisions: Iterable[Mapping[str, Any]], existing_ids: set[str], *, now: datetime) -> list[dict[str, Any]]:
    ready: list[dict[str, Any]] = []
    for row in decisions:
        event_id = str(row.get("event_id") or "")
        candidate = row.get("candidate") if isinstance(row.get("candidate"), Mapping) else {}
        opened = _timestamp(candidate.get("bar_completed_at"))
        if not event_id or event_id in existing_ids or opened is None:
            continue
        if opened.astimezone(ET).time() >= time(16, 0):
            continue
        resolution_end, _ = _resolution_end(opened)
        if now >= resolution_end:
            ready.append(dict(row))
    return ready


def resolve_decision(decision: Mapping[str, Any], bars: Iterable[Mapping[str, Any]], *, now: datetime) -> dict[str, Any] | None:
    candidate = decision.get("candidate") if isinstance(decision.get("candidate"), Mapping) else {}
    opened = _timestamp(candidate.get("bar_completed_at"))
    direction = str(candidate.get("direction") or "").upper()
    entry, stop, target = (_number(candidate.get(key)) for key in ("trigger", "stop", "target"))
    if opened is None or direction not in {"LONG", "SHORT"} or None in {entry, stop, target}:
        return None
    end, session_truncated = _resolution_end(opened)
    if now < end:
        return None
    completed: list[dict[str, Any]] = []
    for raw in bars:
        stamp = _timestamp(raw.get("t") or raw.get("timestamp"))
        high, low, close = (_number(raw.get(key)) for key in ("h", "l", "c"))
        if stamp is None or None in {high, low, close}:
            continue
        if opened <= stamp and stamp + timedelta(minutes=5) <= end:
            completed.append({"timestamp": stamp, "high": high, "low": low, "close": close})
    completed.sort(key=lambda row: row["timestamp"])
    if not completed:
        return None
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    hit = "time_exit"
    exit_value = completed[-1]["close"]
    resolved_at = completed[-1]["timestamp"] + timedelta(minutes=5)
    for bar in completed:
        stop_hit = bar["low"] <= stop if direction == "LONG" else bar["high"] >= stop
        target_hit = bar["high"] >= target if direction == "LONG" else bar["low"] <= target
        if stop_hit and target_hit:
            hit, exit_value = "ambiguous_same_bar", None
            resolved_at = bar["timestamp"] + timedelta(minutes=5)
            break
        if stop_hit:
            hit, exit_value = "initial_stop", stop
            resolved_at = bar["timestamp"] + timedelta(minutes=5)
            break
        if target_hit:
            hit, exit_value = "target", target
            resolved_at = bar["timestamp"] + timedelta(minutes=5)
            break
    sign = 1.0 if direction == "LONG" else -1.0
    outcome_r = None if exit_value is None else sign * (exit_value - entry) / risk
    excursions = [sign * (bar["high"] - entry) for bar in completed] if direction == "LONG" else [entry - bar["low"] for bar in completed]
    adverse = [sign * (bar["low"] - entry) for bar in completed] if direction == "LONG" else [entry - bar["high"] for bar in completed]
    return {
        "schema_version": 1,
        "outcome_id": f"{decision.get('event_id')}|underlying-60m-v1",
        "decision_event_id": decision.get("event_id"),
        "candidate_key": decision.get("candidate_key"),
        "symbol": candidate.get("symbol"),
        "direction": direction,
        "setup": candidate.get("setup"),
        "grade": candidate.get("grade"),
        "governed_decision": decision.get("decision"),
        "outcome_use": "simulated_lifecycle" if decision.get("decision") == "shadow_accepted" else "veto_counterfactual",
        "opened_at": opened.isoformat().replace("+00:00", "Z"),
        "resolved_at": resolved_at.isoformat().replace("+00:00", "Z"),
        "planned_horizon_minutes": HORIZON_MINUTES,
        "observed_bar_count": len(completed),
        "session_truncated": session_truncated,
        "entry": entry,
        "stop": stop,
        "target": target,
        "terminal_event": hit,
        "exit_underlying": exit_value,
        "outcome_r": round(outcome_r, 4) if outcome_r is not None else None,
        "won": outcome_r > 0 if outcome_r is not None else None,
        "mfe_r": round(max(excursions) / risk, 4),
        "mae_r": round(min(adverse) / risk, 4),
        "reconciliation_status": "ambiguous_excluded" if hit == "ambiguous_same_bar" else "underlying_proxy_reconciled",
        "limitations": "Underlying completed-bar proxy; no option contract, spread, slippage, fee, or executable fill is inferred.",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def fetch_bars(symbols: Iterable[str], start: datetime, end: datetime) -> dict[str, list[dict[str, Any]]]:
    names = sorted({str(symbol).upper() for symbol in symbols if symbol})
    if not names:
        return {}
    response = requests.get(
        "https://data.alpaca.markets/v2/stocks/bars",
        headers=_credentials(),
        params={
            "symbols": ",".join(names), "timeframe": "5Min",
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": end.isoformat().replace("+00:00", "Z"),
            "adjustment": "raw", "feed": "iex", "limit": 10000, "sort": "asc",
        },
        timeout=25,
    )
    response.raise_for_status()
    payload = response.json()
    return {symbol: [row for row in rows if isinstance(row, dict)] for symbol, rows in (payload.get("bars") or {}).items()}


def run(*, now: datetime | None = None, decision_path: Path = DECISION_LEDGER_PATH, outcome_path: Path = OUTCOME_LEDGER_PATH, report_path: Path = REPORT_PATH) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    decisions = _read_jsonl(decision_path)
    outcomes = _read_jsonl(outcome_path)
    existing = {str(row.get("decision_event_id")) for row in outcomes}
    after_session_ineligible = 0
    for row in decisions:
        event_id = str(row.get("event_id") or "")
        candidate = row.get("candidate") if isinstance(row.get("candidate"), Mapping) else {}
        opened = _timestamp(candidate.get("bar_completed_at"))
        if event_id not in existing and opened is not None and opened.astimezone(ET).time() >= time(16, 0):
            after_session_ineligible += 1
    pending = ready_decisions(decisions, existing, now=current)
    resolved: list[dict[str, Any]] = []
    errors: list[str] = []
    if pending:
        starts = [_timestamp((row.get("candidate") or {}).get("bar_completed_at")) for row in pending]
        valid_starts = [value for value in starts if value is not None]
        try:
            grouped = fetch_bars(
                [str((row.get("candidate") or {}).get("symbol") or "") for row in pending],
                min(valid_starts), current,
            ) if valid_starts else {}
            for row in pending:
                symbol = str((row.get("candidate") or {}).get("symbol") or "").upper()
                outcome = resolve_decision(row, grouped.get(symbol, []), now=current)
                if outcome is not None:
                    resolved.append(outcome)
        except Exception as exc:
            errors.append(type(exc).__name__)
    if resolved:
        outcome_path.parent.mkdir(parents=True, exist_ok=True)
        with outcome_path.open("a", encoding="utf-8") as handle:
            for row in resolved:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        outcomes.extend(resolved)
    counts = defaultdict(int)
    for row in outcomes:
        counts[str(row.get("terminal_event") or "unknown")] += 1
    report = {
        "provider": "governed_shadow_outcome",
        "generated_at": current.isoformat().replace("+00:00", "Z"),
        "decision_count": len(decisions),
        "ready_for_reconciliation": len(pending),
        "newly_reconciled": len(resolved),
        "still_pending_or_missing_bars": len(pending) - len(resolved),
        "after_session_ineligible": after_session_ineligible,
        "total_reconciled": len(outcomes),
        "terminal_event_counts": dict(sorted(counts.items())),
        "errors": errors,
        "outcomes": outcomes[-100:],
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run()
    print(json.dumps({key: report[key] for key in ("decision_count", "ready_for_reconciliation", "newly_reconciled", "still_pending_or_missing_bars", "errors")}, sort_keys=True))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
