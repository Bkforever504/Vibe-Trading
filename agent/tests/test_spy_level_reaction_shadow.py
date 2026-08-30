from __future__ import annotations

from datetime import datetime
from pathlib import Path
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


def test_gap_breadth_and_intermarket_context_are_frozen_without_creating_authority() -> None:
    breadth = monitor.breadth_context_from_report(
        {"date": "2026-08-28", "breadth": {"status": "ok", "uptrend_status": "mixed", "pct_above_50dma": 52.0}},
        session_date="2026-08-28",
    )
    intermarket = monitor.intermarket_context_from_radar({
        "generated_at": "2026-08-28T14:00:00Z",
        "coverage": {"market_context_snapshot": {
            "status": "available", "qqq_vs_spy_pct": 0.24, "qqq_spy_regime": "qqq_leading_spy",
            "sector_leaders": [{"etf": "XLK", "vs_spy_pct": 0.31}],
        }},
    })

    report = monitor.evaluate_rows(_rows(), now_et=NOW, breadth_context=breadth, intermarket_context=intermarket)

    assert report["gap_context"]["fill_bucket"] in {"unfilled", "filled_within_15m", "filled_within_30m", "filled_within_60m", "filled_after_60m", "flat_open"}
    assert report["breadth_context"]["regime"] == "mixed"
    assert report["breadth_context"]["authority"] == "challenger_only_no_gate_or_sizing_effect"
    assert report["intermarket_context"]["qqq_spy_regime"] == "qqq_leading_spy"
    assert report["execution_enabled"] is False


def test_reaction_ledger_dedupes_completed_bar_observations(tmp_path: Path) -> None:
    report = monitor.evaluate_rows(_rows(), now_et=NOW)
    ledger = tmp_path / "reactions.jsonl"

    assert monitor.append_reaction_events(report, ledger_path=ledger) >= 1
    assert monitor.append_reaction_events(report, ledger_path=ledger) == 0
    rows = [line for line in ledger.read_text(encoding="utf-8").splitlines() if line]
    assert rows
