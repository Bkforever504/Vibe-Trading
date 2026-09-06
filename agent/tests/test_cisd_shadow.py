from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from agent.analytics.cisd_shadow import detect_cisd_lifecycle
from scripts.cisd_retest_shadow import aggregate_completed_5m, append_unique, run_live_shadow


def bars(values):
    return [
        {"timestamp": f"2026-09-04T14:{index:02d}:00Z", "open": o, "high": h, "low": l, "close": c}
        for index, (o, h, l, c) in enumerate(values)
    ]


def bullish_sequence():
    prefix = [(100, 101, 99, 100.2)] * 11
    return bars(prefix + [
        (100.0, 100.2, 99.3, 99.5),
        (99.5, 99.7, 98.8, 99.0),
        (99.0, 99.3, 98.4, 98.7),  # pivot low; bearish run level is 100
        (98.7, 99.4, 98.6, 99.2),  # right-hand completed bar makes pivot knowable
        (99.2, 100.5, 99.1, 100.3),  # confirmation
        (100.4, 100.6, 99.95, 100.2),  # first held retest
    ])


def test_pending_never_becomes_discord_candidate():
    events = detect_cisd_lifecycle(bullish_sequence()[:-2], symbol="SPY", timeframe="1m", atr_multiplier=0.1)
    armed = next(row for row in events if row["state"] == "ARMED" and row["direction"] == "LONG")
    assert armed["discord_shadow_candidate"] is False
    assert armed["execution_enabled"] is False
    assert armed["can_submit_orders"] is False


def test_confirmation_then_first_retest_ready():
    events = detect_cisd_lifecycle(bullish_sequence(), symbol="SPY", timeframe="1m", atr_multiplier=0.1)
    confirmed = [row for row in events if row["state"] == "CONFIRMED" and row["direction"] == "LONG"]
    assert confirmed[0]["reason"] == "completed_bar_closed_through_cisd_level"
    assert confirmed[0]["retest_ready"] is False
    assert confirmed[1]["reason"] == "confirmed_level_retest_held"
    assert confirmed[1]["retest_ready"] is True
    assert confirmed[1]["discord_shadow_candidate"] is True


def test_creation_pivot_breach_invalidates_confirmed_setup():
    sequence = bullish_sequence() + bars([(100.0, 100.2, 98.0, 98.2)])[0:1]
    # Restore strict timestamp order for the appended bar.
    sequence[-1]["timestamp"] = "2026-09-04T14:17:00Z"
    events = detect_cisd_lifecycle(sequence, symbol="SPY", timeframe="1m", atr_multiplier=0.1)
    invalid = [row for row in events if row["reason"] == "creation_pivot_breached"]
    assert invalid and invalid[-1]["previous_state"] == "CONFIRMED"


def test_missing_or_malformed_bars_fail_honestly():
    with pytest.raises(ValueError, match="timestamp"):
        detect_cisd_lifecycle([{"open": 1, "high": 2, "low": 0, "close": 1}], symbol="SPY", timeframe="1m")
    with pytest.raises(ValueError, match="ohlc"):
        detect_cisd_lifecycle(
            [{"timestamp": "1", "open": 1, "high": 0, "low": 2, "close": 1}], symbol="SPY", timeframe="1m"
        )


def test_module_has_no_broker_notifier_or_order_imports():
    paths = [
        Path(__file__).parents[1] / "analytics" / "cisd_shadow.py",
        Path(__file__).parents[2] / "scripts" / "cisd_retest_shadow.py",
    ]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        assert not any(token in name.lower() for name in imported for token in ("alpaca", "broker", "notifier", "order"))


def test_five_minute_aggregation_requires_complete_contiguous_bucket():
    rows = [
        {"timestamp": f"2026-09-04T14:{minute:02d}:00Z", "open": 10, "high": 11 + minute, "low": 9, "close": 10 + minute}
        for minute in range(31, 36)
    ]
    result = aggregate_completed_5m(rows)
    assert len(result) == 1
    assert result[0]["timestamp"] == "2026-09-04T14:35:00Z"
    assert aggregate_completed_5m(rows[:-1]) == []


def test_event_ledger_is_idempotent(tmp_path):
    event = {"signal_id": "cisd_retest_shadow", "symbol": "SPY", "timeframe": "1m", "state": "ARMED", "reason": "x", "direction": "LONG", "bar_completed_at": "t", "cisd_level": 1}
    path = tmp_path / "events.jsonl"
    assert append_unique(path, [event]) == 1
    assert append_unique(path, [event]) == 0


def test_weekend_live_shadow_makes_no_provider_call(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("provider must not be called while market is closed")
    monkeypatch.setattr("scripts.cisd_retest_shadow.fetch_completed_1m", forbidden)
    now = datetime(2026, 9, 6, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    report = run_live_shadow(now_et=now)
    assert report["status"] == "market_closed"
    assert report["execution_enabled"] is False


def test_exchange_holiday_live_shadow_makes_no_provider_call(monkeypatch):
    monkeypatch.setattr(
        "scripts.cisd_retest_shadow.fetch_completed_1m",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider must not be called on a holiday")),
    )
    report = run_live_shadow(now_et=datetime(2026, 9, 7, 12, 0, tzinfo=ZoneInfo("America/New_York")))
    assert report["status"] == "market_closed"


def test_disabled_configuration_is_effective_rollback(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "scripts.cisd_retest_shadow.fetch_completed_1m",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("disabled scanner must not fetch")),
    )
    path = tmp_path / "config.json"
    path.write_text(
        '{"enabled":false,"shadow_only":true,"execution_enabled":false,'
        '"can_submit_orders":false,"discord_delivery_enabled":false}',
        encoding="utf-8",
    )
    report = run_live_shadow(
        now_et=datetime(2026, 9, 8, 12, 0, tzinfo=ZoneInfo("America/New_York")),
        config_path=path,
    )
    assert report["status"] == "disabled"


def test_authority_configuration_cannot_be_flipped(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"enabled":true,"shadow_only":true,"execution_enabled":true,'
        '"can_submit_orders":false,"discord_delivery_enabled":false}',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="authority_configuration_invalid"):
        run_live_shadow(config_path=path)
