#!/usr/bin/env python3
"""Plain-English end-of-day summary across the full trading system.

This is a read-only executive summary. It pulls together health, grades, audit,
activity, and review queue outputs so the daily check is one report instead of
five tabs.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
LOG_PATH = ROOT / "data" / "daily_eod_summary_log.jsonl"
REPORT_PATH = REPORT_DIR / "daily-eod-summary.json"
TEXT_PATH = REPORT_DIR / "daily-eod-summary.txt"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _grade_counts(grades: dict[str, Any]) -> dict[str, Any]:
    items = grades.get("items") if isinstance(grades.get("items"), list) else []
    weak = [
        item for item in items
        if item.get("ops_grade") not in {"A", "B"} or item.get("freshness") in {"missing", "stale"}
    ]
    top_evidence = sorted(
        items,
        key=lambda item: float(item.get("evidence_score") or item.get("score") or 0),
        reverse=True,
    )[:5]
    return {
        "ops": grades.get("by_ops_grade", {}),
        "evidence": grades.get("by_grade", {}),
        "maturity": grades.get("by_maturity_stage", {}),
        "promotion_ready_count": grades.get("promotion_ready_count", 0),
        "weak_ops": [
            {
                "name": item.get("name"),
                "ops_grade": item.get("ops_grade"),
                "freshness": item.get("freshness"),
                "sample_count": item.get("sample_count"),
            }
            for item in weak[:10]
        ],
        "top_evidence": [
            {
                "name": item.get("name"),
                "evidence_grade": item.get("evidence_grade") or item.get("grade"),
                "evidence_score": item.get("evidence_score") or item.get("score"),
                "sample_count": item.get("sample_count"),
                "signal_count": item.get("signal_count"),
                "maturity_stage": item.get("maturity_stage"),
            }
            for item in top_evidence
        ],
    }


def _activity_counts(events: list[dict[str, str]]) -> dict[str, Any]:
    by_type = Counter(event.get("event_type", "") for event in events)
    by_source = Counter(event.get("source", "") for event in events)
    trades = [event for event in events if event.get("event_type") == "trade"]
    guard_blocks = [event for event in events if event.get("event_type") == "guard_block"]
    pnls: list[float] = []
    for event in trades:
        try:
            if event.get("pnl") not in (None, ""):
                pnls.append(float(event["pnl"]))
        except ValueError:
            pass
    return {
        "event_count": len(events),
        "by_type": dict(by_type),
        "top_sources": dict(by_source.most_common(8)),
        "trade_count": len(trades),
        "guard_block_count": len(guard_blocks),
        "realized_pnl_from_csv": round(sum(pnls), 2) if pnls else 0.0,
        "guard_reasons": dict(Counter(event.get("reason", "") for event in guard_blocks if event.get("reason"))),
    }


def _make_verdict(
    health: dict[str, Any],
    grades: dict[str, Any],
    audit: dict[str, Any],
    activity: dict[str, Any],
    needs_review: dict[str, Any],
    schedule: dict[str, Any] | None = None,
    bot_status: dict[str, Any] | None = None,
) -> tuple[str, list[str], list[str]]:
    positives: list[str] = []
    concerns: list[str] = []
    actions: list[str] = []

    health_summary = health.get("summary") if isinstance(health.get("summary"), dict) else {}
    if health_summary.get("error", 0) or health_summary.get("missing", 0):
        concerns.append(f"Health has missing/error rows: {health_summary}.")
        actions.append("Inspect signal-stack-health.json before trusting scanner output.")
    else:
        positives.append("All scheduled signal outputs are present and healthy.")

    if audit.get("passed") is False or audit.get("issue_count", 0):
        concerns.append("Execution audit found order-wiring or live-flag issues.")
        actions.append("Stop promotion work and fix execution-gate-audit findings first.")
    else:
        positives.append("Execution audit passed with no blocking issues.")

    schedule = schedule or {}
    if schedule.get("passed") is False or schedule.get("issue_count", 0):
        concerns.append("Market schedule alignment has timing issues.")
        actions.append("Fix market-schedule-alignment findings before the next open.")
    elif schedule:
        positives.append("Market open, close, and EOD task timing are aligned.")

    bot_status = bot_status or {}
    option_integrity = (
        bot_status.get("option_position_integrity")
        if isinstance(bot_status.get("option_position_integrity"), dict)
        else {}
    )
    integrity_status = option_integrity.get("status")
    if bot_status.get("status") == "review_required" or integrity_status == "review_required":
        concerns.append("Options broker positions do not reconcile with durable trade state.")
        actions.append("Keep new options entries blocked and reconcile missing/untracked legs before trading.")
    elif integrity_status == "ok":
        positives.append("Options broker positions reconcile with durable trade state.")

    grade_counts = _grade_counts(grades)
    if grade_counts["weak_ops"]:
        concerns.append(f"{len(grade_counts['weak_ops'])} components have weak ops freshness/grade.")
        actions.append("Review weak_ops list in daily-eod-summary.json.")
    else:
        positives.append("Operational grades are clean.")

    promotion_ready = int(grade_counts.get("promotion_ready_count") or 0)
    if promotion_ready:
        actions.append(f"{promotion_ready} components are promotion-review candidates; apply rules/signal_promotion_rules.md.")
    else:
        positives.append("No scanner is prematurely promotion-ready.")

    if int(needs_review.get("queue_count") or 0):
        actions.append(f"Review {needs_review.get('queue_count')} guard-block queue items.")
    else:
        positives.append("No manual guard review items are open.")

    if activity.get("guard_block_count", 0) > 20:
        concerns.append(f"Guard blocks are elevated: {activity['guard_block_count']}.")
        actions.append("Check whether blocks are protective duplicates or repeated near-miss opportunities.")

    hard_stop = bool(
        audit.get("issue_count", 0)
        or bot_status.get("status") == "review_required"
        or integrity_status == "review_required"
    )
    if not concerns:
        verdict = "green"
        actions.append("Let the system keep collecting evidence. Do not add new gates yet.")
    elif not hard_stop and len(concerns) <= 2:
        verdict = "watch"
        actions.append("Fix review items, then keep collecting evidence.")
    else:
        verdict = "action_required"

    return verdict, positives, concerns + actions


def build_report(day: str | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    health = _read_json(REPORT_DIR / "signal-stack-health.json")
    grades = _read_json(REPORT_DIR / "signal-stack-grades.json")
    audit = _read_json(REPORT_DIR / "execution-gate-audit.json")
    schedule = _read_json(REPORT_DIR / "market-schedule-alignment.json")
    needs_review = _read_json(REPORT_DIR / "needs-review-queue.json")
    outcome = _read_json(REPORT_DIR / "daily-outcome-review.json")
    bot_status = _read_json(REPORT_DIR / "bot-status-snapshot.json")
    activity_path = REPORT_DIR / f"daily-bot-activity-{day}.csv"
    activity = _activity_counts(_read_csv(activity_path))
    grade_summary = _grade_counts(grades)
    verdict, positives, next_actions = _make_verdict(
        health,
        grades,
        audit,
        activity,
        needs_review,
        schedule,
        bot_status,
    )
    return {
        "date": day,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "daily_eod_summary",
        "mode": "read_only",
        "execution_enabled": False,
        "verdict": verdict,
        "plain_english": {
            "headline": _headline(verdict, activity, grade_summary),
            "positives": positives,
            "next_actions": next_actions,
        },
        "health": health.get("summary", {}),
        "grades": grade_summary,
        "audit": {
            "passed": audit.get("passed"),
            "issue_count": audit.get("issue_count"),
            "warning_count": audit.get("warning_count"),
        },
        "schedule_alignment": {
            "passed": schedule.get("passed"),
            "issue_count": schedule.get("issue_count"),
            "warning_count": schedule.get("warning_count"),
            "aligned_count": schedule.get("aligned_count"),
            "task_count": schedule.get("task_count"),
        },
        "activity": activity,
        "outcome": {
            "verdict": outcome.get("verdict"),
            "review_score": outcome.get("review_score"),
            "posture": outcome.get("posture"),
            "market_force": outcome.get("market_force_classification"),
            "realized_pnl": ((outcome.get("event_summary") or {}) if isinstance(outcome.get("event_summary"), dict) else {}).get("realized_pnl"),
        },
        "bot_status": {
            "status": bot_status.get("status"),
            "status_flags": bot_status.get("status_flags", []),
            "option_position_integrity": bot_status.get("option_position_integrity", {}),
        },
        "needs_review": {
            "queue_count": needs_review.get("queue_count", 0),
            "by_priority": needs_review.get("by_priority", {}),
            "by_reason": needs_review.get("by_reason", {}),
        },
        "warnings": [
            "Read-only summary. No bot settings are changed.",
            "A green verdict means operate and observe, not enable live trading.",
        ],
    }


def _headline(verdict: str, activity: dict[str, Any], grades: dict[str, Any]) -> str:
    if verdict == "green":
        return (
            f"Stack healthy. {activity.get('event_count', 0)} events logged, "
            f"{activity.get('trade_count', 0)} trades, {activity.get('guard_block_count', 0)} guard blocks. "
            f"Ops grades {grades.get('ops', {})}; evidence still building."
        )
    if verdict == "watch":
        return "Stack is mostly healthy, but there are review items to inspect before adding new logic."
    return "Action required before trusting today's stack output."


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), default=str) + "\n")
    return path


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def write_text(report: dict[str, Any], path: Path = TEXT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"Daily EOD Summary | {report['date']}",
        "=" * 72,
        f"Verdict: {report['verdict']}",
        report["plain_english"]["headline"],
        "",
        "What Looks Good:",
    ]
    lines.extend(f"- {item}" for item in report["plain_english"]["positives"])
    lines.extend(["", "Next Actions:"])
    lines.extend(f"- {item}" for item in report["plain_english"]["next_actions"])
    lines.extend([
        "",
        f"Health: {report['health']}",
        f"Schedule: {report.get('schedule_alignment')}",
        f"Grades: ops={report['grades'].get('ops')} evidence={report['grades'].get('evidence')} maturity={report['grades'].get('maturity')}",
        f"Activity: {report['activity']}",
        "",
        "Read-only summary. No settings changed.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    print("\nDaily EOD Summary | read-only")
    print("=" * 72)
    print(f"verdict={report['verdict']} date={report['date']}")
    print(report["plain_english"]["headline"])
    print("\nNext actions:")
    for item in report["plain_english"]["next_actions"]:
        print(f"- {item}")
    print(f"\nJSON: {REPORT_PATH}")
    print(f"TXT:  {TEXT_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--text-path", type=Path, default=TEXT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_report(args.date)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    write_text(report, args.text_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Daily EOD summary logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
