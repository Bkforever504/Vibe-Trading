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
