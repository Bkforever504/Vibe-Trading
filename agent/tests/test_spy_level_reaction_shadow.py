from __future__ import annotations

from datetime import datetime, timedelta
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


def _feature_rows(*, start_hour: int = 9, start_minute: int = 30) -> list[dict]:
    rows = [
        _bar(27, 9, 30, 100.0, 101.0, 99.0, 100.0),
        _bar(27, 9, 35, 100.0, 100.8, 99.2, 100.2),
    ]
    start = datetime(2026, 8, 28, start_hour, start_minute, tzinfo=ET)
    for index in range(15):
        timestamp = start + timedelta(minutes=index * 5)
        open_ = 99.5 + index * 0.1
        rows.append(_bar(28, timestamp.hour, timestamp.minute, open_, open_ + 0.15, open_ - 0.10, open_ + 0.05))
    # The last completed bar rejects the known prior-day high; it is still a
    # normal completed 5-minute reaction rather than a synthetic future bar.
    last = rows[-1]
    last.update({"o": 100.95, "h": 101.04, "l": 100.30, "c": 100.48})
    return rows


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


def test_level_lifecycle_is_completed_bar_context_not_trade_authority() -> None:
    report = monitor.evaluate_rows(_rows(), now_et=NOW)

    lifecycle = next(row for row in report["level_lifecycles"] if row["level_name"] == "previous_day_high")
    assert lifecycle["state"] in {"RETEST_HELD_BELOW", "ACCEPTED_BELOW"}
    assert lifecycle["touch_count"] >= 1
    assert lifecycle["bar_basis"] == "completed_5m_only"
    assert lifecycle["authority"] == "context_only_no_rank_alert_sizing_or_execution_authority"
    assert lifecycle["execution_enabled"] is False
    assert lifecycle["can_submit_orders"] is False


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


def test_break_then_next_completed_bar_retest_hold_is_classified_bullishly() -> None:
    rows = [
        _bar(28, 9, 30, 99.5, 99.8, 99.3, 99.7),
        _bar(28, 9, 35, 99.7, 100.5, 99.6, 100.4),
        _bar(28, 9, 40, 100.3, 100.7, 99.98, 100.5),
    ]
    level_map = {"levels": [{"name": "trigger", "price": 100.0, "role": "resistance", "source": "test"}]}

    lifecycle = monitor.classify_level_lifecycles(level_map, rows)[0]

    assert lifecycle["state"] == "RETEST_HELD_ABOVE"
    assert lifecycle["retest_basis"]["break_bar_at"].endswith("09:35:00-04:00")
    assert lifecycle["decision_available_at"].endswith("09:45:00-04:00")


def test_break_then_next_completed_bar_retest_hold_is_classified_bearishly() -> None:
    rows = [
        _bar(28, 9, 30, 100.5, 100.7, 100.2, 100.3),
        _bar(28, 9, 35, 100.3, 100.4, 99.5, 99.6),
        _bar(28, 9, 40, 99.7, 100.02, 99.3, 99.5),
    ]
    level_map = {"levels": [{"name": "trigger", "price": 100.0, "role": "support", "source": "test"}]}

    lifecycle = monitor.classify_level_lifecycles(level_map, rows)[0]

    assert lifecycle["state"] == "RETEST_HELD_BELOW"
    assert lifecycle["decision_available_at"].endswith("09:45:00-04:00")


def test_lifecycle_ledger_dedupes_retest_decisions(tmp_path: Path) -> None:
    report = {
        "generated_at": "2026-08-28T14:00:00Z",
        "date": "2026-08-28",
        "level_lifecycles": [{
            "level_name": "trigger", "level": 100.0, "state": "RETEST_HELD_ABOVE",
            "decision_available_at": "2026-08-28T09:45:00-04:00",
        }],
    }
    ledger = tmp_path / "lifecycles.jsonl"

    assert monitor.append_lifecycle_events(report, ledger_path=ledger) == 1
    assert monitor.append_lifecycle_events(report, ledger_path=ledger) == 0


def test_spy0dte_whole_dollar_and_completed_bar_features_are_frozen_context() -> None:
    report = monitor.evaluate_rows(_feature_rows(), now_et=NOW)

    whole_dollars = [row for row in report["level_map"]["levels"] if row["name"].startswith("whole_dollar_")]
    assert [row["price"] for row in whole_dollars] == [98.0, 99.0, 100.0, 101.0, 102.0]
    assert all(row["spy0dte_feature_provenance"] == monitor.SPY0DTE_FEATURE_PROVENANCE for row in whole_dollars)
    assert next(row for row in whole_dollars if row["price"] == 101.0)["touch_sequence"] == "second"
    assert all(row["touch_count_basis"] == "completed_current_rth_5m" for row in report["level_map"]["levels"])
    reaction = next(row for row in report["reactions"] if row["level_name"] == "previous_day_high")
    features = reaction["spy0dte_features"]
    assert features["provenance"] == monitor.SPY0DTE_FEATURE_PROVENANCE
    assert features["touch_count"] >= 1
    assert features["touch_sequence"] in {"first", "second", "third", "fourth_or_later"}
    assert features["rsi_14_status"] == "available"
    assert features["rsi_14_completed_5m"] is not None
    assert features["raw_approach_return_30m_points"] is not None
    assert features["atr_14_completed_5m_points"] is not None
    assert features["atr_normalized_approach_speed"] is not None
    assert features["early_session_eligible"] is True
    assert report["spy0dte_feature_contract"]["authority"] == "shadow_context_only_no_gate_or_sizing_effect"
    assert reaction["execution_enabled"] is False
    assert reaction["can_submit_orders"] is False


def test_spy0dte_cutoff_uses_completed_bar_decision_time() -> None:
    report = monitor.evaluate_rows(_feature_rows(start_hour=10, start_minute=0), now_et=NOW)

    reaction = next(row for row in report["reactions"] if row["level_name"] == "previous_day_high")
    assert reaction["decision_available_at"].endswith("11:15:00-04:00")
    assert reaction["spy0dte_features"]["early_session_eligible"] is True

    late_rows = _feature_rows(start_hour=10, start_minute=5)
    late_report = monitor.evaluate_rows(late_rows, now_et=NOW)
    late_reaction = next(row for row in late_report["reactions"] if row["level_name"] == "previous_day_high")
    assert late_reaction["decision_available_at"].endswith("11:20:00-04:00")
    assert late_reaction["spy0dte_features"]["early_session_eligible"] is False
