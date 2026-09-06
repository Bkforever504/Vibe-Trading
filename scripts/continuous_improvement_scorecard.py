#!/usr/bin/env python3
"""Build a daily/weekly accountability scorecard for scanner and alert quality.

This report is observational.  It measures discovery, timeliness, delivery, and
pattern-monitor health; it cannot promote a strategy or submit an order.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable
from zoneinfo import ZoneInfo
try:
    from scripts.alert_delivery_timing import first_complete_bar_after_delivery
except ModuleNotFoundError:
    from alert_delivery_timing import first_complete_bar_after_delivery

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]
VIBE_HOME = Path.home() / ".vibe-trading"
ALERT_EVENTS_PATH = VIBE_HOME / "data" / "simple_price_action_alert_events.jsonl"
COVERAGE_LEDGER_PATH = ROOT / "data" / "daily_move_coverage_review.jsonl"
ALERT_REPORT_PATH = VIBE_HOME / "reports" / "simple-price-action-alerts.json"
SPY_REACTION_PATH = VIBE_HOME / "reports" / "spy-level-reaction-shadow.json"
STRAT_PATH = VIBE_HOME / "reports" / "strat-30m-continuation-shadow.json"
REPORT_PATH = VIBE_HOME / "reports" / "continuous-improvement-scorecard.json"
LEDGER_PATH = ROOT / "data" / "continuous_improvement_scorecard.jsonl"
CORE_SYMBOLS = ("SPY", "QQQ", "IWM")
LATE_ALERT_SECONDS = 180


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _jsonl(path: Path) -> list[dict[str, Any]]:
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


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _pct(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _latest_by_date(rows: Iterable[dict[str, Any]], date_key: str = "date") -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = str(row.get(date_key) or "")[:10]
        if day:
            latest[day] = row
    return latest


def build_scorecard(
    *,
    day: str,
    alert_events: list[dict[str, Any]],
    alert_report: dict[str, Any],
    coverage_history: list[dict[str, Any]],
    scorecard_history: list[dict[str, Any]],
    spy_report: dict[str, Any],
    strat_report: dict[str, Any],
) -> dict[str, Any]:
    session_events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in alert_events:
        detected = _time(event.get("detected_at"))
        if detected is None or detected.astimezone(ET).date().isoformat() != day:
            continue
        event_id = str(event.get("event_id") or "")
        if event_id and event_id in seen:
            continue
        if event_id:
            seen.add(event_id)
        session_events.append(event)

    confirmed = [row for row in session_events if str(row.get("state")) == "CONFIRMED"]
    core = [row for row in session_events if str(row.get("symbol")) in CORE_SYMBOLS]
    core_confirmed = [row for row in core if str(row.get("state")) == "CONFIRMED"]
    latency_seconds: list[float] = []
    for row in session_events:
        detected = _time(row.get("delivered_at") or row.get("attempted_at") or row.get("detected_at"))
        completed = _time(row.get("bar_completed_at"))
        if detected and completed:
            if row.get("bar_timestamp_semantics") != "decision_available_at":
                # Legacy events copied Alpaca's 5m bar-start timestamp.
                completed = completed + timedelta(minutes=5)
            latency_seconds.append(max(0.0, (detected - completed).total_seconds()))
    delivered = sum(row.get("discord_delivered") is True for row in session_events)
    failed = sum(row.get("discord_delivered") is False for row in session_events)
    # Older rows recorded null on a failed send.  The current report is the
    # authoritative attempt counter until all historical rows use booleans.
    if str(alert_report.get("generated_at") or "")[:10] == day:
        failed = max(failed, int(alert_report.get("notification_failures") or 0))
        attempts = max(delivered + failed, int(alert_report.get("notification_attempts") or 0))
    else:
        attempts = delivered + failed

    coverage = _latest_by_date(coverage_history).get(day, {})
    coverage_summary = coverage.get("summary") if isinstance(coverage.get("summary"), dict) else {}
    discovery_recall = _pct(coverage_summary.get("source_discovery_recall_pct"))
    actionable_recall = _pct(coverage_summary.get("actionable_early_recall_pct"))
    per_symbol = Counter(str(row.get("symbol") or "UNKNOWN") for row in session_events)
    current_core = {
        str(row.get("symbol")) for row in (alert_report.get("signals") or [])
        if isinstance(row, dict) and str(row.get("symbol")) in CORE_SYMBOLS
    }
    observed_core = {str(row.get("symbol")) for row in core}.union(current_core)
    missing_core = [symbol for symbol in CORE_SYMBOLS if symbol not in observed_core]
    p95 = _percentile(latency_seconds, 0.95)

    failures: list[dict[str, Any]] = []
    if failed:
        failures.append({"stage": "delivery", "severity": "critical", "count": failed, "lesson": "Discord delivery failed; retry until acknowledged and keep the event visible on the dashboard."})
    if p95 is not None and p95 > LATE_ALERT_SECONDS:
        failures.append({"stage": "timeliness", "severity": "high", "count": sum(value > LATE_ALERT_SECONDS for value in latency_seconds), "lesson": "Detection-to-alert exceeded three minutes; reduce cadence lag or emit the watch before confirmation."})
    if missing_core:
        failures.append({"stage": "core_index_coverage", "severity": "critical", "symbols": missing_core, "lesson": "SPY, QQQ, and IWM must each remain in the real-time shadow alert lane."})
    if discovery_recall is not None and discovery_recall < 90:
        failures.append({"stage": "discovery", "severity": "high", "value_pct": discovery_recall, "lesson": "The covered-source mover recall was below 90%; inspect missing source and bar-budget cohorts."})
    strat_errors = sum(row.get("status") == "error" for row in (strat_report.get("scans") or []))
    if strat_errors:
        failures.append({"stage": "strat_30m_data", "severity": "high", "count": strat_errors, "lesson": "The 30-minute pattern monitor lost market data; keep its signals unavailable until a healthy scheduled refresh."})
    if spy_report and spy_report.get("operational_health") == "degraded":
        failures.append({"stage": "spy_level_data", "severity": "critical", "count": 1, "lesson": "The SPY level monitor is degraded; do not represent level reactions as current until its feed recovers."})

    critical = sum(row["severity"] == "critical" for row in failures)
    high = sum(row["severity"] == "high" for row in failures)
    grade = "F" if critical else "C" if high >= 2 else "B" if high else "A"
    prior_days = _latest_by_date(scorecard_history)
    previous = next((prior_days[key] for key in sorted(prior_days, reverse=True) if key < day), {})
    previous_daily = previous.get("daily") if isinstance(previous.get("daily"), dict) else {}

    return {
        "schema_version": 1,
        "provider": "continuous_improvement_scorecard",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": day,
        "mode": "shadow_accountability_only",
        "daily": {
            "grade": grade,
            "alert_events": len(session_events),
            "confirmed_events": len(confirmed),
            "core_index_events": len(core),
            "core_index_confirmed": len(core_confirmed),
            "core_symbols_seen": sorted(observed_core),
            "missing_core_symbols": missing_core,
            "discord_attempts": attempts,
            "discord_delivered": delivered,
            "discord_failures": failed,
            "delivery_success_pct": round(delivered / attempts * 100.0, 2) if attempts else None,
            "median_alert_latency_seconds": round(median(latency_seconds), 1) if latency_seconds else None,
            "p95_alert_latency_seconds": round(p95, 1) if p95 is not None else None,
            "late_alert_count": sum(value > LATE_ALERT_SECONDS for value in latency_seconds),
            "source_discovery_recall_pct": discovery_recall,
            "actionable_early_recall_pct": actionable_recall,
            "per_symbol_event_count": dict(sorted(per_symbol.items())),
        },
        "change_vs_previous_session": {
            "grade": previous_daily.get("grade"),
            "delivery_success_pct_delta": (
                round((_pct((delivered / attempts * 100.0) if attempts else None) or 0.0) - float(previous_daily.get("delivery_success_pct")), 2)
                if previous_daily.get("delivery_success_pct") is not None and attempts else None
            ),
            "p95_latency_seconds_delta": (
                round(float(p95) - float(previous_daily.get("p95_alert_latency_seconds")), 1)
                if p95 is not None and previous_daily.get("p95_alert_latency_seconds") is not None else None
            ),
            "discovery_recall_pct_delta": (
                round(discovery_recall - float(previous_daily.get("source_discovery_recall_pct")), 2)
                if discovery_recall is not None and previous_daily.get("source_discovery_recall_pct") is not None else None
            ),
        },
        "retained_lessons": [
            {
                "pattern": "SPX_trigger_break_next_candle_retest",
                "acceptance": "Momentum close through a mapped trigger, then the next completed candle opens beyond it and retests without closing back through it.",
                "entry_policy": "Alert the break as WATCH; upgrade after the retest hold. Mark extended entries NO_CHASE.",
                "targets": "Use the pre-mapped UT/DT ladder; never invent screenshot levels after the move.",
                "status": "mapped_level_lifecycle_shadow",
            },
            {
                "pattern": "NVDA_30m_2_1_2_reversal",
                "acceptance": "Completed directional 30m bar, completed inside bar, then an opposite 30m break of the inside bar.",
                "entry_policy": "Entry at the inside-bar break, stop beyond its opposite side, first target at the prior directional-bar extreme or a pre-mapped level.",
                "status": "shadow_challenger_requires_forward_outcomes",
            },
        ],
        "monitor_health": {
            "simple_price_action": alert_report.get("provider") or "available" if alert_report else "missing",
            "spy_level_reaction": spy_report.get("operational_health") or ("available" if spy_report else "missing"),
            "strat_30m": (
                strat_report.get("operational_health")
                or ("degraded" if any(row.get("status") == "error" for row in (strat_report.get("scans") or [])) else "available")
            ) if strat_report else "missing",
        },
        "failures": failures,
        "next_actions": [row["lesson"] for row in failures] or ["No critical gap detected; continue forward shadow measurement without changing parameters."],
        "governance": {
            "automatic_parameter_changes": False,
            "automatic_strategy_promotion": False,
            "minimum_forward_samples_before_review": 30,
            "execution_enabled": False,
            "can_submit_orders": False,
        },
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date")
    parser.add_argument("--alert-events", type=Path, default=ALERT_EVENTS_PATH)
    parser.add_argument("--coverage-ledger", type=Path, default=COVERAGE_LEDGER_PATH)
    parser.add_argument("--alert-report", type=Path, default=ALERT_REPORT_PATH)
    parser.add_argument("--spy-report", type=Path, default=SPY_REACTION_PATH)
    parser.add_argument("--strat-report", type=Path, default=STRAT_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--ledger-path", type=Path, default=LEDGER_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    day = args.date or datetime.now(ET).date().isoformat()
    history = _jsonl(args.ledger_path)
    report = build_scorecard(
        day=day,
        alert_events=_jsonl(args.alert_events),
        alert_report=_json(args.alert_report),
        coverage_history=_jsonl(args.coverage_ledger),
        scorecard_history=history,
        spy_report=_json(args.spy_report),
        strat_report=_json(args.strat_report),
    )
    _atomic(args.report_path, report)
    args.ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with args.ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Continuous improvement: grade={report['daily']['grade']} failures={len(report['failures'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
