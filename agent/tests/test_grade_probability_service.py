from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.grade_probability_service import build_calibration


def _rows(count: int, *, start: datetime, family: str = "range_break_retest") -> list[dict]:
    rows = []
    for index in range(count):
        grade = "A" if index % 2 == 0 else "B"
        win = index % 5 != 0 if grade == "A" else index % 3 == 0
        rows.append({
            "plan_id": str(index),
            "resolved_at": (start + timedelta(days=index)).isoformat(),
            "setup_family": family,
            "regime": "trend",
            "grade": grade,
            "outcome_r": 1.0 if win else -1.0,
        })
    return rows


def test_calibration_is_chronological_bounded_and_manual_only() -> None:
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    report = build_calibration(_rows(140, start=now - timedelta(days=200)), now=now)

    assert report["method"].startswith("expanding_date_window_isotonic")
    assert report["groups"][0]["sample_size"] >= 30
    bucket = next(row for row in report["buckets"] if row["grade"] == "A")
    assert 0 <= bucket["probability"]["lower_bound"] <= bucket["probability"]["value"] <= 1
    assert bucket["probability"]["sample_size"] == 70
    assert bucket["probability"]["independent_dates"] == 70
    assert bucket["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_calibration_refuses_small_or_recent_buckets() -> None:
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    old = _rows(20, start=now - timedelta(days=50))
    recent = [{**old[0], "plan_id": "recent", "resolved_at": (now - timedelta(hours=1)).isoformat()}]
    report = build_calibration([*old, *recent], now=now)

    assert report["skipped_outcomes"] == 1
    assert all(row["calibration_status"] == "not_calibrated" for row in report["buckets"])
