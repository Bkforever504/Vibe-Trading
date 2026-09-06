from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from scripts import priority_swing_observation as swing
from scripts.priority_focus_universe import PRIORITY_FOCUS_UNIVERSE


ET = ZoneInfo("America/New_York")


def _frame(*, breakout: bool = False) -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-09-04", periods=65)
    rows = []
    for index in range(65):
        close = 100 + index * 0.25
        rows.append({"open": close - 0.2, "high": close + 0.4, "low": close - 0.4, "close": close, "volume": 1_000_000})
    if breakout:
        prior_high = max(row["high"] for row in rows[-21:-1])
        rows[-1].update({"open": prior_high - 0.1, "high": prior_high + 1.0, "low": prior_high - 0.3, "close": prior_high + 0.7, "volume": 1_500_000})
    frame = pd.DataFrame(rows, index=dates)
    frame.attrs["data_source"] = "fixture_adjusted_daily"
    return frame


def test_completed_daily_cutoff_excludes_open_session_and_includes_closed_session() -> None:
    frame = _frame()
    before_close = swing.completed_adjusted_daily(frame, as_of_et=datetime(2026, 9, 4, 15, 59, tzinfo=ET))
    after_close = swing.completed_adjusted_daily(frame, as_of_et=datetime(2026, 9, 4, 16, 1, tzinfo=ET))
    assert str(before_close.index[-1].date()) == "2026-09-03"
    assert str(after_close.index[-1].date()) == "2026-09-04"


def test_confirmed_row_is_unvalidated_and_never_execution_eligible() -> None:
    row = swing.evaluate_symbol(
        "DELL", _frame(breakout=True),
        as_of_et=datetime(2026, 9, 4, 16, 5, tzinfo=ET), previous=None,
    )
    assert row["state"] == "CONFIRMED"
    assert row["validation_status"] == "unvalidated_observation"
    assert row["strict_execution_eligible"] is False
    assert row["completed_daily_evidence"]["latest_completed_date"] == "2026-09-04"
    assert row["trigger"] > row["invalidation"]
    assert row["execution_enabled"] is False
    assert row["can_submit_orders"] is False
    assert not any(key in row for key in ("universe_id", "universe_hash", "spec_hash"))


def test_report_contract_uses_priority_config_without_frozen_universe_claim() -> None:
    now = datetime(2026, 9, 4, 16, 5, tzinfo=ET)
    frames = {symbol: _frame(breakout=symbol == "DELL") for symbol in PRIORITY_FOCUS_UNIVERSE}
    report = swing.build_report(mode="scan", frames=frames, as_of_et=now, previous_state={})
    assert report["schema_version"] == "priority-swing-observation-v1"
    assert report["provider"] == "priority_swing_observation"
    assert report["universe_source"] == "priority_swing_observation_v1_config"
    assert report["priority_symbols"] == list(PRIORITY_FOCUS_UNIVERSE)
    assert len(report["observations"]) == len(PRIORITY_FOCUS_UNIVERSE)
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert "universe_id" not in report
    assert "universe_hash" not in report


def test_revalidation_preserves_signal_date_and_emits_idempotent_invalidation(tmp_path) -> None:
    now = datetime(2026, 9, 4, 16, 5, tzinfo=ET)
    prior = {
        "observations": {
            "DELL": {"state": "CONFIRMED", "signal_date": "2026-09-03", "trigger": 115.0, "invalidation": 110.0},
        },
        "alerted_transition_ids": [], "pending_alerts": [],
    }
    falling = _frame()
    falling.iloc[-1, falling.columns.get_loc("close")] = 90.0
    falling.iloc[-1, falling.columns.get_loc("low")] = 89.0
    report = swing.build_report(mode="revalidate", frames={"DELL": falling}, as_of_et=now, previous_state=prior, symbols=["DELL"])
    row = report["observations"][0]
    assert row["state"] == "INVALIDATED"
    assert row["previous_state"] == "CONFIRMED"
    assert row["signal_date"] == "2026-09-03"
    assert row["continuing_setup"] is False
    assert len(report["transition_events"]) == 1

    ledger = tmp_path / "events.jsonl"
    state = tmp_path / "state.json"
    output = tmp_path / "report.json"
    swing.persist_run(report, report_path=output, state_path=state, event_path=ledger, alert=False)
    swing.persist_run(report, report_path=output, state_path=state, event_path=ledger, alert=False)
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_failed_optional_alert_remains_pending_for_retry(tmp_path) -> None:
    report = swing.build_report(
        mode="scan", frames={"DELL": _frame(breakout=True)}, symbols=["DELL"],
        as_of_et=datetime(2026, 9, 4, 16, 5, tzinfo=ET), previous_state={},
    )
    state_path, report_path, event_path = tmp_path / "state.json", tmp_path / "report.json", tmp_path / "events.jsonl"
    swing.persist_run(
        report, report_path=report_path, state_path=state_path, event_path=event_path, alert=True,
        sender=lambda _: {"delivered": False, "attempts": 3, "error_class": "http_429"},
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(state["pending_alerts"]) == 1
    assert report["notification_attempts"] == 3
    assert report["notification_failures"] == 1

    replay = {**report, "transition_events": []}
    swing.persist_run(
        replay, report_path=report_path, state_path=state_path, event_path=event_path, alert=True,
        sender=lambda _: {"delivered": True, "attempts": 1, "error_class": None},
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["pending_alerts"] == []
    assert report_path.exists()


def test_existing_equity_runner_invokes_priority_swing_in_both_modes() -> None:
    root = swing.ROOT
    runner = (root / "scripts" / "run_equity_ignition_continuation_shadow.ps1").read_text(encoding="utf-8")
    registration = (root / "scripts" / "register_equity_ignition_continuation_shadow_task.ps1").read_text(encoding="utf-8")
    assert "priority_swing_observation.py --mode $Mode" in runner
    assert 'run_equity_ignition_continuation_shadow.ps1' in registration
    assert "EquityIgnitionContinuationShadow" in registration
    assert "EquityIgnitionContinuationRevalidate" in registration
