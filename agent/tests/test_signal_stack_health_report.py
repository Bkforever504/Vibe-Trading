from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import signal_stack_health_report as report


def test_latest_jsonl_ignores_bad_lines_and_returns_latest(tmp_path: Path) -> None:
    path = tmp_path / "sample.jsonl"
    path.write_text(
        '{"date":"2026-06-29","value":1}\n'
        'not-json\n'
        '{"date":"2026-06-30","value":2}\n',
        encoding="utf-8",
    )

    latest, count, warning = report._latest_jsonl(path)

    assert latest == {"date": "2026-06-30", "value": 2}
    assert count == 2
    assert warning == "invalid_json_lines=1"


def test_build_report_flags_missing_stale_error_and_ok(monkeypatch, tmp_path: Path) -> None:
    ok_log = tmp_path / "ok.jsonl"
    ok_log.write_text('{"date":"2026-06-30","primary":{"action":"flat"}}\n', encoding="utf-8")
    stale_log = tmp_path / "stale.jsonl"
    stale_log.write_text('{"date":"2026-06-29"}\n', encoding="utf-8")
    error_log = tmp_path / "error.jsonl"
    error_log.write_text(
        json.dumps({"date": "2026-06-30", "scans": [{"symbol": "IWM", "status": "error", "error": "no chain"}]}) + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        report,
        "SIGNALS",
        [
            {"name": "OK", "task": "ok-task", "log": ok_log, "kind": "close"},
            {"name": "Stale", "task": "stale-task", "log": stale_log, "kind": "close"},
            {"name": "Missing", "task": "missing-task", "log": tmp_path / "missing.jsonl", "kind": "morning"},
            {"name": "Error", "task": "error-task", "log": error_log, "kind": "morning"},
        ],
    )
    monkeypatch.setattr(
        report,
        "_task_status",
        lambda task: {"available": True, "status": "Ready", "next_run_time": "6/30/2026 3:20:00 PM"},
    )

    built = report.build_report(today=date(2026, 6, 30))

    assert built["summary"] == {"ok": 1, "stale": 1, "missing": 1, "error": 1, "disabled": 0}
    statuses = {item["name"]: item["health"] for item in built["items"]}
    assert statuses == {"OK": "ok", "Stale": "stale", "Missing": "missing", "Error": "error"}


def test_build_report_classifies_disabled_task_as_disabled_not_stale(monkeypatch, tmp_path: Path) -> None:
    old_log = tmp_path / "disabled.jsonl"
    old_log.write_text('{"date":"2026-07-16"}\n', encoding="utf-8")
    monkeypatch.setattr(
        report,
        "SIGNALS",
        [{"name": "Disabled Bot", "task": "disabled-task", "log": old_log, "kind": "intraday"}],
    )
    monkeypatch.setattr(
        report,
        "_task_status",
        lambda task: {"available": True, "status": "Disabled", "next_run_time": "N/A", "last_run_time": ""},
    )

    built = report.build_report(today=date(2026, 7, 24))

    assert built["summary"] == {"ok": 0, "stale": 0, "missing": 0, "error": 0, "disabled": 1}
    assert built["items"][0]["health"] == "disabled"
    assert "task_status=Disabled" in built["items"][0]["warnings"]


def test_build_report_ready_task_with_old_log_is_still_stale(monkeypatch, tmp_path: Path) -> None:
    old_log = tmp_path / "ready.jsonl"
    old_log.write_text('{"date":"2026-07-16"}\n', encoding="utf-8")
    monkeypatch.setattr(
        report,
        "SIGNALS",
        [{"name": "Ready Bot", "task": "ready-task", "log": old_log, "kind": "intraday"}],
    )
    monkeypatch.setattr(
        report,
        "_task_status",
        lambda task: {"available": True, "status": "Ready", "next_run_time": ""},
    )

    built = report.build_report(today=date(2026, 7, 24))

    assert built["items"][0]["health"] == "stale"
    assert built["summary"]["stale"] == 1


def test_build_report_treats_pre_scheduled_today_run_as_pending_ok(monkeypatch, tmp_path: Path) -> None:
    log = tmp_path / "morning.jsonl"
    log.write_text('{"date":"2026-07-03"}\n', encoding="utf-8")
    monkeypatch.setattr(
        report,
        "SIGNALS",
        [{"name": "Morning", "task": "morning-task", "log": log, "kind": "morning"}],
    )
    monkeypatch.setattr(
        report,
        "_task_status",
        lambda task: {"available": True, "status": "Ready", "next_run_time": "7/6/2026 8:35:00 AM"},
    )

    built = report.build_report(today=date(2026, 7, 6), now=datetime(2026, 7, 6, 6, 15))

    assert built["summary"] == {"ok": 1, "stale": 0, "missing": 0, "error": 0, "disabled": 0}
    assert built["items"][0]["health"] == "ok"
    assert built["items"][0]["warnings"] == ["pending_today latest_date=2026-07-03"]


def test_market_mastery_signals_are_registered_for_health() -> None:
    names = {signal["name"]: signal for signal in report.SIGNALS}

    assert names["Candlestick Context"]["log"].name == "candlestick_context_log.jsonl"
    assert names["Higher Timeframe Map"]["log"].name == "higher_timeframe_market_map_log.jsonl"
    assert names["Market Catalyst Calendar"]["log"].name == "market_catalyst_calendar_log.jsonl"
    assert names["Daily Edge Orchestrator"]["log"].name == "daily_edge_orchestrator_log.jsonl"
    assert names["Kronos Market Forecaster"]["log"].name == "kronos_market_forecast_log.jsonl"
    assert names["Options Surface Intelligence"]["log"].name == "options_surface_intelligence_log.jsonl"
    assert names["Flip Feature Ablation"]["log"].name == "flip_feature_ablation_log.jsonl"
    assert names["Edge Trial Ledger"]["log"].name == "edge_trial_ledger_report_log.jsonl"
    assert names["Flip Equity Curve"]["log"].name == "flip_equity_curve_log.jsonl"


def test_signal_health_registry_has_unique_names() -> None:
    names = [signal["name"] for signal in report.SIGNALS]

    assert len(names) == len(set(names))


def test_strategy_staleness_alerts_after_threshold(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    trades.write_text(json.dumps([
        {
            "strategy": "0dte", "orb_entry_pattern": "breakout_retest",
            "entry_date": "2026-07-01", "exit_date": "2026-07-01", "status": "closed",
        }
    ]), encoding="utf-8")
    shadow = tmp_path / "shadow.jsonl"
    shadow.write_text("", encoding="utf-8")

    result = report.build_strategy_staleness(
        today=date(2026, 7, 17), trades_path=trades, shadow_path=shadow
    )

    assert result["orb_continuation"]["alert"] is True
    assert result["orb_continuation"]["days_since_last_entry"] > 5
    assert result["orb_extension_reversal"]["alert"] is False
    assert result["orb_extension_reversal"]["note"] == "no_observations_yet"
