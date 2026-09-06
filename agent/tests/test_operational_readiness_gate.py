from __future__ import annotations

from datetime import date

from scripts import operational_readiness_gate as gate


def _health(*, stale: int = 0, missing: int = 0, error: int = 0, expected: bool = True) -> dict:
    return {
        "summary": {"ok": 60, "stale": stale, "missing": missing, "error": error},
        "market_session": {"expected": expected},
    }


def _radar(day: str, *, rows: int = 78, minimum: int = 70, status: str = "ok") -> dict:
    return {"date_checked": day, "row_count": rows, "min_rows": minimum, "status": status}


def test_five_distinct_clean_sessions_pass_operational_prerequisite() -> None:
    history = [
        {"session_date": f"2026-08-{day:02d}", "expected_market_session": True, "session_passed": True}
        for day in (24, 25, 26, 27)
    ]
    report = gate.build_report(
        _health(), _radar("2026-08-28"), history, session_date=date(2026, 8, 28)
    )
    assert report["operational_prerequisite_passed"] is True
    assert report["passing_sessions_in_window"] == 5
    assert report["live_trading_ready"] is False
    assert report["can_submit_orders"] is False


def test_one_stale_signal_blocks_and_resets_five_session_window() -> None:
    history = [
        {"session_date": f"2026-08-{day:02d}", "expected_market_session": True, "session_passed": True}
        for day in (24, 25, 26, 27)
    ]
    report = gate.build_report(
        _health(stale=1), _radar("2026-08-28"), history, session_date=date(2026, 8, 28)
    )
    assert report["status"] == "blocked"
    assert report["operational_prerequisite_passed"] is False
    assert report["passing_sessions_in_window"] == 4


def test_wrong_date_or_low_radar_count_blocks_session() -> None:
    wrong_date = gate.build_report(
        _health(), _radar("2026-08-27"), [], session_date=date(2026, 8, 28)
    )
    low_count = gate.build_report(
        _health(), _radar("2026-08-28", rows=19, minimum=20), [], session_date=date(2026, 8, 28)
    )
    assert wrong_date["current_session"]["radar_coverage_clean"] is False
    assert low_count["current_session"]["session_passed"] is False


def test_weekend_does_not_record_a_failure() -> None:
    report = gate.build_report(
        _health(expected=False), {}, [], session_date=date(2026, 8, 30)
    )
    assert report["status"] == "observing"
    assert report["current_session"]["expected_market_session"] is False
    assert report["observed_sessions_in_window"] == 0
