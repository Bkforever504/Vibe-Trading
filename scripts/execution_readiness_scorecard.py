#!/usr/bin/env python3
"""Report live-execution readiness without changing any execution setting."""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

try:
    from scripts.order_authority_invariant import static_violations
    from scripts.signal_stack_health_report import is_expected_market_session
except ModuleNotFoundError:
    from order_authority_invariant import static_violations
    from signal_stack_health_report import is_expected_market_session

VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "execution-readiness.json"
HISTORY_PATH = VIBE_HOME / "data" / "execution_readiness_daily_inputs.jsonl"
CHART_PATH = VIBE_HOME / "reports" / "discord-alert-chart-review.json"
NOMINATION_PATH = VIBE_HOME / "reports" / "grade-recalibration-nominations.json"
DRILL_PATH = VIBE_HOME / "reports" / "kill-switch-drill.json"
SIZING_PATH = VIBE_HOME / "reports" / "sizing-policy-verification.json"
REQUIRED = 30


def _streak(rows: list[Mapping[str, Any]], predicate: Any, *, as_of: date, calendar_days: bool = False) -> int:
    by_day: dict[date, Mapping[str, Any]] = {}
    for row in rows:
        try:
            day = date.fromisoformat(str(row.get("date")))
        except ValueError:
            continue
        if day > as_of:
            continue
        # Repeated snapshots are one day. Conflicting snapshots do not prove
        # a clean day and cannot replace a failed measurement with a pass.
        if day in by_day and dict(by_day[day]) != dict(row):
            by_day[day] = {"date": day.isoformat(), "conflicting_snapshots": True}
        else:
            by_day[day] = row
    count = 0
    cursor = as_of
    while by_day:
        if not calendar_days and not is_expected_market_session(cursor):
            cursor -= timedelta(days=1)
            continue
        row = by_day.get(cursor)
        if row is None or row.get("conflicting_snapshots") or not predicate(row):
            break
        count += 1
        cursor -= timedelta(days=1)
    return count


def _criterion(name: str, count: int, required: int = REQUIRED) -> dict[str, Any]:
    return {"name": name, "status": "PASS" if count >= required else "PENDING", "observed": count, "required": required, "days_remaining": max(0, required - count)}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def build_scorecard(sessions: Iterable[Mapping[str, Any]], *, chart_report: Mapping[str, Any], nominations: Mapping[str, Any], kill_switch_drill: Mapping[str, Any], sizing_policy: Mapping[str, Any] | None = None, as_of: date | None = None) -> dict[str, Any]:
    as_of = as_of or datetime.now(timezone.utc).date()
    rows = sorted([dict(row) for row in sessions if row.get("date")], key=lambda row: str(row["date"]))
    clean = _streak(rows, lambda row: row.get("clean_shadow_session") is True and row.get("delivery_timestamp_evaluation") is True, as_of=as_of)
    authority = _streak(rows, lambda row: type(row.get("order_authority_violations")) is int and row["order_authority_violations"] == 0, as_of=as_of, calendar_days=True)
    latency = _streak(rows, lambda row: _finite(row.get("median_discord_latency_seconds")) and 0 <= row["median_discord_latency_seconds"] < 10, as_of=as_of)
    # Explicit target avoids selecting whichever grade happens to pass today.
    target_grade = str((sizing_policy or {}).get("target_grade") or "A+").upper()
    grade_rows = [row for row in chart_report.get("by_grade") or [] if isinstance(row, Mapping) and str(row.get("grade") or "").upper() == target_grade]
    target = grade_rows[0] if len(grade_rows) == 1 else {}
    count = target.get("count")
    outcome_pass = (str(chart_report.get("provider") or "").endswith("post_discord_delivery") and type(count) is int and count >= REQUIRED and _finite(target.get("positive_pct")) and 55 <= target["positive_pct"] <= 100 and _finite(target.get("median_r")) and target["median_r"] >= 0.5)
    review_pass = bool(nominations.get("human_review_completed") is True and nominations.get("human_review_accepted") is True)
    drill_pass = kill_switch_drill.get("status") == "PASS" and kill_switch_drill.get("end_to_end") is True
    sizing = sizing_policy or {}
    sizing_pass = (sizing.get("status") == "PASS" and sizing.get("human_review_accepted") is True and sizing.get("enforcement_verified") is True and bool(sizing.get("evidence_id")) and _finite(sizing.get("max_account_risk_fraction")) and 0 < sizing["max_account_risk_fraction"] <= 0.01 and _finite(sizing.get("three_loss_day_multiplier")) and 0 < sizing["three_loss_day_multiplier"] <= 0.5)
    criteria = [
        _criterion("SESSIONS", clean),
        _criterion("ORDER_AUTHORITY", authority),
        _criterion("DELIVERY_LATENCY", latency),
        {"name": "TARGET_GRADE_OUTCOMES", "status": "PASS" if outcome_pass else "FAIL", "grade": target_grade, "sample_size": count, "minimum_samples": REQUIRED, "positive_pct": target.get("positive_pct"), "median_r": target.get("median_r"), "days_remaining": 0},
        {"name": "GRADE_RECALIBRATION_HUMAN_REVIEW", "status": "PASS" if review_pass else "PENDING", "days_remaining": 0},
        {"name": "KILL_SWITCH_DRILL", "status": "PASS" if drill_pass else "PENDING", "days_remaining": 0},
        {"name": "SIZING_POLICY", "status": "PASS" if sizing_pass else "PENDING", "reason": "verified_policy" if sizing_pass else "verified_sizing_policy_evidence_missing", "max_account_risk_fraction": sizing.get("max_account_risk_fraction"), "three_loss_day_multiplier": sizing.get("three_loss_day_multiplier"), "days_remaining": 0},
    ]
    return {"provider": "execution_readiness_scorecard", "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "as_of": as_of.isoformat(), "authority_streak_unit": "calendar_days", "session_streak_unit": "market_sessions", "status": "PASS" if all(row["status"] == "PASS" for row in criteria) else "NOT_READY", "criteria": criteria, "automatic_promotion": False, "human_promotion_required": True, "execution_enabled": False, "can_submit_orders": False}


def _json(path: Path) -> dict[str, Any]:
    try: value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError): return {}
    return value if isinstance(value, dict) else {}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try: lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError: return []
    rows=[]
    for line in lines:
        try: value=json.loads(line)
        except json.JSONDecodeError: continue
        if isinstance(value, dict): rows.append(value)
    return rows


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--history",type=Path,default=HISTORY_PATH); parser.add_argument("--report",type=Path,default=REPORT_PATH)
    args=parser.parse_args(); chart=_json(CHART_PATH); sessions=_jsonl(args.history)
    now = datetime.now(ZoneInfo("America/New_York"))
    today = now.date().isoformat()
    by_day={str(row.get("date")):row for row in sessions if row.get("date")}
    current = dict(by_day.get(today) or {"date": today})
    # A check performed today proves nothing about an old chart session.
    previous = current.get("order_authority_violations")
    current["order_authority_violations"] = max(previous if type(previous) is int else 0, len(static_violations()))
    if chart.get("session_date") == today and now.hour >= 16:
        summary = chart.get("summary") or {}
        current.update({"clean_shadow_session": bool(summary.get("evaluated")) and not any(int(value or 0) for key, value in (summary.get("status_counts") or {}).items() if "missing" in key or "no_bars" in key), "delivery_timestamp_evaluation": str(chart.get("provider") or "").endswith("post_discord_delivery"), "median_discord_latency_seconds": summary.get("median_transport_seconds")})
    by_day[today] = current
    sessions = [by_day[key] for key in sorted(by_day)]
    args.history.parent.mkdir(parents=True,exist_ok=True)
    temp = args.history.with_suffix(".jsonl.tmp")
    temp.write_text("".join(json.dumps(row,sort_keys=True,separators=(",",":"))+"\n" for row in sessions),encoding="utf-8")
    temp.replace(args.history)
    report=build_scorecard(sessions,chart_report=chart,nominations=_json(NOMINATION_PATH),kill_switch_drill=_json(DRILL_PATH),sizing_policy=_json(SIZING_PATH),as_of=now.date()); args.report.parent.mkdir(parents=True,exist_ok=True); temp=args.report.with_suffix(".json.tmp"); temp.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8"); temp.replace(args.report); print(json.dumps({"status":report["status"],"criteria":{r["name"]:r["status"] for r in report["criteria"]}})); return 0


if __name__ == "__main__": raise SystemExit(main())
