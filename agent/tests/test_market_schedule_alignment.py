from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import market_schedule_alignment as alignment


def _rows_from_expected(overrides: dict[str, set[str]] | None = None) -> list[dict[str, str]]:
    overrides = overrides or {}
    rows: list[dict[str, str]] = []
    for task, times in alignment.EXPECTED_TASKS.items():
        for hhmm in overrides.get(task, times):
            hour, minute = [int(part) for part in hhmm.split(":")]
            suffix = "AM" if hour < 12 else "PM"
            hour12 = hour % 12 or 12
            rows.append({
                "TaskName": task,
                "Start Time": f"{hour12}:{minute:02d}:00 {suffix}",
                "Status": "Ready",
            })
    return rows


def test_build_report_passes_when_expected_times_present() -> None:
    report = alignment.build_report(_rows_from_expected())

    assert report["passed"] is True
    assert report["issue_count"] == 0
    assert report["aligned_count"] == report["task_count"]


def test_build_report_flags_missing_expected_time() -> None:
    bad_task = r"\Flip-Bot-Entry"
    report = alignment.build_report(_rows_from_expected({bad_task: {"08:40"}}))

    assert report["passed"] is False
    assert any(issue["issue"] == "missing_expected_times" and issue["task"] == bad_task for issue in report["issues"])


def test_build_report_flags_uncovered_options_entry_window() -> None:
    task = r"\IWM-Bot-Entry"
    report = alignment.build_report(_rows_from_expected({task: {"09:45"}}))

    uncovered = [
        issue for issue in report["issues"]
        if issue.get("issue") == "entry_window_uncovered"
    ]
    assert report["passed"] is False
    assert {issue["window_et"] for issue in uncovered} == {
        "09:45-10:30",
        "15:00-15:45",
    }


def test_build_report_flags_order_violation() -> None:
    report = alignment.build_report(_rows_from_expected({
        r"\VibeTrade\PreOpenSentimentLogger": {"08:50"},
        r"\Flip-Bot-Entry": {"08:35"},
    }))

    assert report["passed"] is False
    assert any(issue.get("issue") == "order_violation" for issue in report["issues"])


def test_parse_time_handles_task_scheduler_format() -> None:
    assert alignment._parse_time_to_minutes("8:35:00 AM") == 8 * 60 + 35
    assert alignment._parse_time_to_minutes("1:45:00 PM") == 13 * 60 + 45


def _override_status(
    rows: list[dict[str, str]], task: str, status: str, last_run_time: str = ""
) -> list[dict[str, str]]:
    for row in rows:
        if row["TaskName"] == task:
            row["Status"] = status
            row["Last Run Time"] = last_run_time
    return rows


def test_recently_running_task_is_not_an_issue() -> None:
    from datetime import datetime

    task = r"\VibeTrade\MarketScheduleAlignment"
    now = datetime(2026, 7, 24, 19, 58, 30)
    rows = _override_status(_rows_from_expected(), task, "Running", "07/24/2026 07:58:05 PM")

    report = alignment.build_report(rows, now=now)

    assert report["passed"] is True
    assert not any(issue.get("task") == task for issue in report["issues"])
    row = next(r for r in report["tasks"] if r["task"] == task)
    assert row["aligned"] is True


def test_long_running_task_is_flagged_as_stuck() -> None:
    from datetime import datetime

    task = r"\VibeTrade\GEXScanner"
    now = datetime(2026, 7, 24, 12, 0, 0)
    rows = _override_status(_rows_from_expected(), task, "Running", "07/24/2026 08:35:00 AM")

    report = alignment.build_report(rows, now=now)

    assert report["passed"] is False
    assert any(
        issue.get("task") == task and issue.get("issue") == "task_running_too_long"
        for issue in report["issues"]
    )


def test_disabled_task_is_still_not_ready() -> None:
    task = r"\VibeTrade\GEXScanner"
    rows = _override_status(_rows_from_expected(), task, "Disabled")

    report = alignment.build_report(rows)

    assert report["passed"] is False
    assert any(
        issue.get("task") == task and issue.get("issue") == "task_not_ready"
        for issue in report["issues"]
    )


def test_parse_last_run_rejects_never_run_sentinel() -> None:
    assert alignment._parse_last_run_datetime("11/30/1999 12:00:00 AM") is None
    assert alignment._parse_last_run_datetime("N/A") is None
    assert alignment._parse_last_run_datetime("7/24/2026 7:58:05 PM") is not None
