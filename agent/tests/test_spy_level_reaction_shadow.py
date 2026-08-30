from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts import spy_level_reaction_shadow as monitor


ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 8, 28, 10, 0, tzinfo=ET)


def _bar(day: int, hour: int, minute: int, open_: float, high: float, low: float, close: float) -> dict:
    return {
        "t": datetime(2026, 8, day, hour, minute, tzinfo=ET).isoformat(),
        "o": open_, "h": high, "l": low, "c": close, "v": 1000,
    }


def _rows(latest_close: float = 100.48) -> list[dict]:
    return [
        _bar(27, 9, 30, 100.0, 101.0, 99.0, 100.0),
        _bar(27, 9, 35, 100.0, 100.8, 99.2, 100.2),
        _bar(28, 4, 0, 99.3, 100.0, 98.0, 99.0),
        _bar(28, 9, 30, 99.3, 100.0, 99.0, 99.5),
        _bar(28, 9, 35, 99.5, 100.2, 99.4, 100.0),
        _bar(28, 9, 40, 100.0, 100.1, 99.7, 99.9),
        _bar(28, 9, 45, 100.95, 101.04, 100.3, latest_close),
    ]


def test_maps_pre_session_levels_and_confirms_only_target_sized_rejection() -> None:
    report = monitor.evaluate_rows(_rows(), now_et=NOW)

    mapped = {row["name"]: row["price"] for row in report["level_map"]["levels"]}
    assert mapped["previous_day_high"] == 101.0
    assert mapped["premarket_low"] == 98.0
    confirmed = next(row for row in report["active_reactions"] if row["level_name"] == "previous_day_high")
    assert confirmed["direction"] == "bearish"
    assert confirmed["status"] == "CONFIRMED_REACTION"
    assert confirmed["reaction_points"] == 0.52
    assert confirmed["bar_basis"] == "completed_5m_only"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_extended_reaction_is_explicitly_no_chase_not_a_stronger_signal() -> None:
    report = monitor.evaluate_rows(_rows(latest_close=99.9), now_et=NOW)

    reaction = next(row for row in report["reactions"] if row["level_name"] == "previous_day_high")
    assert reaction["status"] == "EXTENDED_NO_CHASE"
    assert report["active_reactions"] == []
    assert report["summary"]["extended_no_chase"] >= 1


def test_report_disclaims_option_premium_prediction() -> None:
    report = monitor.evaluate_rows(_rows(), now_et=NOW)

    assert "options_premium_target_pct" not in report
    assert any("options-premium" in warning for warning in report["limitations"])
