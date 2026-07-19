#!/usr/bin/env python3
"""Generate the safe nightly research loop handoff.

This is not an autonomous coding agent and not a trading loop. It reads the
daily review reports, writes STATUS.md, and produces a capped research queue for
Codex/Claude to review the next morning.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
STATUS_PATH = ROOT / "STATUS.md"
REPORT_PATH = REPORT_DIR / "nightly-research-queue.json"
LOG_PATH = ROOT / "data" / "nightly_research_queue_log.jsonl"

MAX_ACTIVE_TASKS = 1
MAX_QUEUE_ITEMS = 8

FORBIDDEN_ACTIONS = [
    "Do not enable live trading.",
    "Do not change risk thresholds, max contracts, kill switches, or manual-reset files.",
    "Do not promote a scanner into an execution gate without rules/signal_promotion_rules.md.",
    "Do not wire social/X/PMXT/copy-trader/prediction-market context directly to orders.",
    "Do not add a new scanner unless the EOD summary identifies a specific evidence gap.",
]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _task(task_id: str, title: str, reason: str, action: str, priority: str = "P2") -> dict[str, Any]:
    return {
        "id": task_id,
        "priority": priority,
        "title": title,
        "reason": reason,
        "suggested_action": action,
        "allowed_scope": "read_only_or_tests_docs_reports",
        "requires_kenny_approval": False,
    }


def build_tasks(
    *,
    eod: dict[str, Any],
    health: dict[str, Any],
    grades: dict[str, Any],
    needs_review: dict[str, Any],
    audit: dict[str, Any],
    schedule: dict[str, Any],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    bot_status = eod.get("bot_status") if isinstance(eod.get("bot_status"), dict) else {}
    option_integrity = (
        bot_status.get("option_position_integrity")
        if isinstance(bot_status.get("option_position_integrity"), dict)
        else {}
    )
    if bot_status.get("status") == "review_required" or option_integrity.get("status") == "review_required":
        tasks.append(_task(
            "reconcile-options-position-integrity",
            "Reconcile options broker positions with trade state",
            (
                f"Missing active legs={len(option_integrity.get('missing_active_legs') or [])}; "
                f"untracked broker legs={len(option_integrity.get('untracked_broker_legs') or [])}."
            ),
            "Inspect broker positions and bot-status-snapshot.json; keep entries blocked and do not auto-close or rewrite state.",
            "P0",
        ))
    health_summary = health.get("summary") if isinstance(health.get("summary"), dict) else {}
    if health_summary.get("missing", 0) or health_summary.get("error", 0) or health_summary.get("stale", 0):
        tasks.append(_task(
            "fix-health-red",
            "Investigate unhealthy scheduled outputs",
            f"Health summary is {health_summary}.",
            "Open signal-stack-health.json, inspect failing rows, fix only task/log/report plumbing.",
            "P0",
        ))
    if schedule.get("passed") is False or schedule.get("issue_count", 0):
        tasks.append(_task(
            "fix-schedule-alignment",
            "Fix market schedule alignment",
            f"Schedule alignment issues={schedule.get('issue_count')}.",
            "Fix Task Scheduler timing only; do not alter strategy logic.",
            "P0",
        ))
    if audit.get("passed") is False or audit.get("issue_count", 0):
        tasks.append(_task(
            "fix-execution-audit",
            "Fix execution audit issue",
            f"Execution audit issues={audit.get('issue_count')}.",
            "Remove accidental order wiring/live flags from non-execution scripts.",
            "P0",
        ))
    queue_count = int(needs_review.get("queue_count") or 0)
    if queue_count:
        tasks.append(_task(
            "review-guard-queue",
            "Review guard-block queue",
            f"Needs Review Queue has {queue_count} item(s).",
            "Classify queue items as protective vs possibly too strict; do not loosen guards.",
            "P1",
        ))
    grade_items = grades.get("items") if isinstance(grades.get("items"), list) else []
    weak_ops = [
        item for item in grade_items
        if item.get("ops_grade") not in {"A", "B"} or item.get("freshness") in {"missing", "stale"}
    ]
    if weak_ops:
        tasks.append(_task(
            "inspect-weak-ops-grades",
            "Inspect weak operational grades",
            f"{len(weak_ops)} component(s) have weak ops grade/freshness.",
            "Fix stale/missing/bad-log issues only.",
            "P1",
        ))
    promotion_ready = int(grades.get("promotion_ready_count") or 0)
    if promotion_ready:
        tasks.append(_task(
            "promotion-review",
            "Run formal promotion review",
            f"{promotion_ready} component(s) are promotion-ready by grades.",
            "Apply rules/signal_promotion_rules.md with Codex + Claude review and Kenny approval.",
            "P1",
        ))
    verdict = str(eod.get("verdict") or "")
    if verdict == "green" and not tasks:
        tasks.append(_task(
            "observe-no-build",
            "No build: collect another clean evidence day",
            "EOD summary is green and no queue/audit/health issue is open.",
            "Read reports only. Do not add new scanners or gates.",
            "P3",
        ))
    elif verdict == "green":
        tasks.append(_task(
            "maintain-discipline",
            "Maintain evidence discipline",
            "EOD summary is green, but review items exist.",
            "Handle the highest-priority review item only, then stop.",
            "P2",
        ))
    tasks.sort(key=lambda item: {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(str(item["priority"]), 9))
    return tasks[:MAX_QUEUE_ITEMS]


def build_report(day: str | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    eod = _read_json(REPORT_DIR / "daily-eod-summary.json")
    health = _read_json(REPORT_DIR / "signal-stack-health.json")
    grades = _read_json(REPORT_DIR / "signal-stack-grades.json")
    needs_review = _read_json(REPORT_DIR / "needs-review-queue.json")
    audit = _read_json(REPORT_DIR / "execution-gate-audit.json")
    schedule = _read_json(REPORT_DIR / "market-schedule-alignment.json")
    tasks = build_tasks(eod=eod, health=health, grades=grades, needs_review=needs_review, audit=audit, schedule=schedule)
    active = tasks[:MAX_ACTIVE_TASKS]
    return {
        "date": day,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "nightly_research_loop",
        "mode": "read_only",
        "execution_enabled": False,
        "max_active_tasks": MAX_ACTIVE_TASKS,
        "active_tasks": active,
        "backlog": tasks[MAX_ACTIVE_TASKS:],
        "source_verdict": eod.get("verdict"),
        "headline": ((eod.get("plain_english") or {}) if isinstance(eod.get("plain_english"), dict) else {}).get("headline"),
        "bot_status": eod.get("bot_status", {}),
        "health": health.get("summary", {}),
        "grades": {
            "ops": grades.get("by_ops_grade", {}),
            "evidence": grades.get("by_grade", {}),
            "maturity": grades.get("by_maturity_stage", {}),
            "promotion_ready_count": grades.get("promotion_ready_count", 0),
        },
        "schedule_alignment": {
            "passed": schedule.get("passed"),
            "aligned_count": schedule.get("aligned_count"),
            "task_count": schedule.get("task_count"),
            "issue_count": schedule.get("issue_count"),
        },
        "audit": {
            "passed": audit.get("passed"),
            "issue_count": audit.get("issue_count"),
            "warning_count": audit.get("warning_count"),
        },
        "needs_review": {
            "queue_count": needs_review.get("queue_count", 0),
            "by_priority": needs_review.get("by_priority", {}),
            "by_reason": needs_review.get("by_reason", {}),
        },
        "forbidden_actions": FORBIDDEN_ACTIONS,
        "stop_conditions": [
            "Stop after one active task.",
            "Stop if tests fail and report the failure.",
            "Stop if the task would require live trading, risk, or gate changes.",
            "Stop if the task needs data that is not present yet.",
        ],
        "warnings": [
            "This queue is a handoff, not an autonomous executor.",
            "Agents may propose diffs, but Kenny reviews every execution-impacting change.",
        ],
    }


def write_status(report: dict[str, Any], path: Path = STATUS_PATH) -> Path:
    active = report.get("active_tasks", [])
    backlog = report.get("backlog", [])
    lines = [
        "# Vibe-Trading STATUS",
        "",
        f"Updated: {report['timestamp']}",
        f"Date: {report['date']}",
        f"Verdict: {report.get('source_verdict') or 'unknown'}",
        "",
        "## Headline",
        "",
        str(report.get("headline") or "No EOD headline available."),
        "",
        "## Active Task Cap",
        "",
        f"Max active tasks: {report['max_active_tasks']}",
        "",
        "## Next Safe Task",
        "",
    ]
    if active:
        task = active[0]
        lines.extend([
            f"- Priority: {task['priority']}",
            f"- Title: {task['title']}",
            f"- Reason: {task['reason']}",
            f"- Suggested action: {task['suggested_action']}",
            f"- Allowed scope: {task['allowed_scope']}",
        ])
    else:
        lines.append("- No active task.")
    lines.extend([
        "",
        "## Backlog",
        "",
    ])
    if backlog:
        lines.extend(f"- [{task['priority']}] {task['title']}: {task['reason']}" for task in backlog)
    else:
        lines.append("- Empty.")
    lines.extend([
        "",
        "## Current State",
        "",
        f"- Health: {report.get('health')}",
        f"- Grades: {report.get('grades')}",
        f"- Schedule: {report.get('schedule_alignment')}",
        f"- Audit: {report.get('audit')}",
        f"- Needs review: {report.get('needs_review')}",
        "",
        "## Forbidden Actions",
        "",
    ])
    lines.extend(f"- {item}" for item in report["forbidden_actions"])
    lines.extend([
        "",
        "## Stop Conditions",
        "",
    ])
    lines.extend(f"- {item}" for item in report["stop_conditions"])
    lines.extend([
        "",
        "## Morning Command",
        "",
        "```powershell",
        "uv run --no-project python scripts\\daily_eod_summary.py --print",
        "uv run --no-project python scripts\\nightly_research_loop.py --print",
        "```",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), default=str) + "\n")
    return path


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    print("\nNightly Research Loop | read-only")
    print("=" * 72)
    print(f"date={report['date']} verdict={report.get('source_verdict')} active={len(report['active_tasks'])}")
    for task in report["active_tasks"]:
        print(f"{task['priority']} {task['title']}: {task['suggested_action']}")
    print(f"STATUS: {STATUS_PATH}")
    print(f"JSON:   {REPORT_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--status-path", type=Path, default=STATUS_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_report(args.date)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    write_status(report, args.status_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Nightly research loop wrote {args.status_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
