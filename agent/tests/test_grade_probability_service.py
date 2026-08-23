from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.grade_probability_service import build_calibration
from scripts.pattern_grader_outcome_resolver import resolve_rows


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


def test_real_pattern_resolver_output_is_accepted_by_calibration() -> None:
    trigger = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
    detection = {
        "detection_id": "pd-one",
        "pattern_id": "range_break_retest",
        "setup_family": "range_break_retest",
        "symbol": "SPY",
        "direction": "bullish",
        "trigger_bar_ts": trigger.isoformat().replace("+00:00", "Z"),
        "trigger": 100.0,
        "invalidation": 99.0,
        "grade": "A",
        "regime": "trend",
    }
    bars = [
        {"t": "2026-07-01T14:05:00Z", "o": 100, "h": 101.2, "l": 100, "c": 101},
        {"t": "2026-07-01T14:10:00Z", "o": 101, "h": 102.2, "l": 100.8, "c": 102},
    ]
    outcomes, warnings = resolve_rows(
        [detection],
        [],
        now=trigger + timedelta(hours=2),
        bar_loader=lambda *_args: bars,
    )

    report = build_calibration(
        outcomes,
        now=datetime(2026, 8, 22, tzinfo=timezone.utc),
        minimum_bucket_n=1,
    )

    assert warnings == []
    assert report["eligible_outcomes"] == 1
    assert report["skipped_outcomes"] == 0
    assert report["buckets"][0]["setup_family"] == "range_break_retest"
