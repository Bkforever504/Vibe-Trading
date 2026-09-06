#!/usr/bin/env python3
"""Five-session, fail-closed operational readiness gate.

This report measures whether the research pipeline collected complete data. It
never evaluates profitability and can never authorize or submit an order.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from scripts.signal_stack_health_report import is_expected_market_session
except ModuleNotFoundError:
    from signal_stack_health_report import is_expected_market_session


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "operational-readiness-gate.json"
HEALTH_PATH = VIBE_HOME / "reports" / "signal-stack-health.json"
RADAR_PATH = VIBE_HOME / "health" / "radar_coverage.json"
HISTORY_PATH = ROOT / "data" / "operational_readiness_history.jsonl"
ET = ZoneInfo("America/New_York")
REQUIRED_PASSING_SESSIONS = 5


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("session_date"):
            rows.append(value)
    return rows


def _market_session_expected(session_date: date, health: dict[str, Any]) -> bool:
    session = health.get("market_session")
    if isinstance(session, dict) and isinstance(session.get("expected"), bool):
        return bool(session["expected"])
    return is_expected_market_session(session_date)


def _summary_clean(health: dict[str, Any]) -> bool:
    summary = health.get("summary")
    if not isinstance(summary, dict) or not summary:
        return False
    return sum(int(summary.get(key) or 0) for key in ("stale", "missing", "error")) == 0


def _radar_clean(radar: dict[str, Any], session_date: str) -> bool:
    if str(radar.get("date_checked") or "") != session_date:
        return False
    try:
        rows = int(radar.get("row_count") or 0)
        minimum = int(radar.get("min_rows") or 0)
    except (TypeError, ValueError):
        return False
    return str(radar.get("status") or "").lower() == "ok" and minimum > 0 and rows >= minimum


def _latest_by_date(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, Any]] = {}
    for row in history:
        key = str(row.get("session_date") or "")
        if key:
            by_date[key] = row
    return [by_date[key] for key in sorted(by_date)]


def build_report(
    health: dict[str, Any],
    radar: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    session_date: date,
    required_sessions: int = REQUIRED_PASSING_SESSIONS,
) -> dict[str, Any]:
    date_key = session_date.isoformat()
    expected = _market_session_expected(session_date, health)
    stack_clean = _summary_clean(health)
    radar_clean = _radar_clean(radar, date_key)
    session_passed = bool(expected and stack_clean and radar_clean)

    current = {
        "session_date": date_key,
        "expected_market_session": expected,
        "session_passed": session_passed,
        "signal_stack_clean": stack_clean,
        "radar_coverage_clean": radar_clean,
        "health_summary": health.get("summary") if isinstance(health.get("summary"), dict) else {},
        "radar_row_count": radar.get("row_count"),
        "radar_min_rows": radar.get("min_rows"),
    }
    eligible_history = _latest_by_date([
        *history,
        current,
    ] if expected else history)
    observed = [row for row in eligible_history if row.get("expected_market_session") is not False]
    recent = observed[-required_sessions:]
    passing_count = sum(1 for row in recent if row.get("session_passed") is True)
    prerequisite_passed = len(recent) == required_sessions and passing_count == required_sessions

    blockers: list[str] = []
    if not expected:
        blockers.append("No operational observation is recorded on a non-market session.")
    if expected and not radar_clean:
        blockers.append("Radar coverage did not meet the dated post-session minimum.")
    if expected and not stack_clean:
        blockers.append("Signal stack contains stale, missing, or error states.")
    if len(recent) < required_sessions:
        blockers.append(f"Need {required_sessions} distinct passing sessions; observed={len(recent)}.")
    elif not prerequisite_passed:
        blockers.append(f"Last {required_sessions} sessions are not all clean; passing={passing_count}.")

    status = "passed" if prerequisite_passed else "observing" if session_passed or not expected else "blocked"
    return {
        "provider": "operational_readiness_gate",
        "mode": "read_only_governance",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "execution_enabled": False,
        "can_submit_orders": False,
        "live_trading_ready": False,
        "operational_prerequisite_passed": prerequisite_passed,
        "required_passing_sessions": required_sessions,
        "passing_sessions_in_window": passing_count,
        "observed_sessions_in_window": len(recent),
        "current_session": current,
        "recent_sessions": recent,
        "blockers": blockers,
        "interpretation": "Operational integrity is necessary but never sufficient for live trading or profitability.",
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def record_session(report: dict[str, Any], path: Path) -> None:
    current = report.get("current_session")
    if not isinstance(current, dict) or current.get("expected_market_session") is not True:
        return
    rows = _latest_by_date([*_read_history(path), current])
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-date", help="YYYY-MM-DD ET; defaults to today ET")
    parser.add_argument("--required-sessions", type=int, default=REQUIRED_PASSING_SESSIONS)
    parser.add_argument("--health-path", type=Path, default=HEALTH_PATH)
    parser.add_argument("--radar-path", type=Path, default=RADAR_PATH)
    parser.add_argument("--history-path", type=Path, default=HISTORY_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--no-record", action="store_true")
    args = parser.parse_args()
    session_date = date.fromisoformat(args.session_date) if args.session_date else datetime.now(ET).date()
    history = _read_history(args.history_path)
    report = build_report(
        _read_json(args.health_path),
        _read_json(args.radar_path),
        history,
        session_date=session_date,
        required_sessions=max(1, args.required_sessions),
    )
    write_report(report, args.report_path)
    if not args.no_record:
        record_session(report, args.history_path)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
