from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import nightly_research_loop as loop


def test_build_tasks_green_creates_observe_task() -> None:
    tasks = loop.build_tasks(
        eod={"verdict": "green"},
        health={"summary": {"ok": 20, "missing": 0, "error": 0, "stale": 0}},
        grades={"items": [], "promotion_ready_count": 0},
        needs_review={"queue_count": 0},
        audit={"passed": True, "issue_count": 0},
        schedule={"passed": True, "issue_count": 0},
    )

    assert len(tasks) == 1
    assert tasks[0]["id"] == "observe-no-build"
    assert tasks[0]["allowed_scope"] == "read_only_or_tests_docs_reports"


def test_build_tasks_prioritizes_audit_issue() -> None:
    tasks = loop.build_tasks(
        eod={"verdict": "watch"},
        health={"summary": {"ok": 20, "missing": 0, "error": 0, "stale": 0}},
        grades={"items": [], "promotion_ready_count": 0},
        needs_review={"queue_count": 5},
        audit={"passed": False, "issue_count": 1},
        schedule={"passed": True, "issue_count": 0},
    )

    assert tasks[0]["id"] == "fix-execution-audit"
    assert tasks[0]["priority"] == "P0"
    assert any(task["id"] == "review-guard-queue" for task in tasks)


def test_build_tasks_prioritizes_option_position_integrity() -> None:
    tasks = loop.build_tasks(
        eod={
            "verdict": "action_required",
            "bot_status": {
                "status": "review_required",
                "option_position_integrity": {
                    "status": "review_required",
                    "missing_active_legs": ["IWM1"],
                    "untracked_broker_legs": ["IWM2", "IWM3"],
                },
            },
        },
        health={"summary": {"ok": 44, "missing": 0, "error": 0, "stale": 0}},
        grades={"items": [], "promotion_ready_count": 0},
        needs_review={"queue_count": 4},
        audit={"passed": True, "issue_count": 0},
        schedule={"passed": True, "issue_count": 0},
    )

    assert tasks[0]["id"] == "reconcile-options-position-integrity"
    assert tasks[0]["priority"] == "P0"
    assert "do not auto-close" in tasks[0]["suggested_action"]


def test_write_status_includes_forbidden_actions(tmp_path: Path) -> None:
    report = {
        "timestamp": "2026-06-30T23:00:00Z",
        "date": "2026-06-30",
        "source_verdict": "green",
        "headline": "Stack healthy.",
        "max_active_tasks": 1,
        "active_tasks": [{
            "priority": "P3",
            "title": "No build",
            "reason": "Green day.",
            "suggested_action": "Observe.",
            "allowed_scope": "read_only_or_tests_docs_reports",
        }],
        "backlog": [],
        "health": {"ok": 20},
        "grades": {"ops": {"A": 20}},
        "schedule_alignment": {"passed": True},
        "audit": {"passed": True},
        "needs_review": {"queue_count": 0},
        "forbidden_actions": loop.FORBIDDEN_ACTIONS,
        "stop_conditions": ["Stop after one active task."],
    }
    path = tmp_path / "STATUS.md"

    loop.write_status(report, path)

    text = path.read_text(encoding="utf-8")
    assert "Vibe-Trading STATUS" in text
    assert "Do not enable live trading." in text
    assert "Max active tasks: 1" in text


def test_write_report_round_trips_json(tmp_path: Path) -> None:
    path = tmp_path / "queue.json"
    report = {"date": "2026-06-30", "active_tasks": []}

    loop.write_report(report, path)

    assert json.loads(path.read_text(encoding="utf-8")) == report
