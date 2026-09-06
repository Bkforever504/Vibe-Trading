from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from scripts import daily_level_map_shadow as subject


ET = ZoneInfo("America/New_York")


def _minute(stamp: datetime, close: float, *, open_: float | None = None, high: float | None = None, low: float | None = None) -> dict:
    return {
        "t": stamp.isoformat(), "o": close if open_ is None else open_,
        "h": close + 0.05 if high is None else high, "l": close - 0.05 if low is None else low,
        "c": close, "v": 100,
    }


def _daily(end: date = date(2026, 9, 3), count: int = 30) -> pd.DataFrame:
    dates = pd.bdate_range(end=end, periods=count)
    rows = []
    for index in range(count):
        close = 100.0 + index
        rows.append({"open": close - 0.5, "high": close + 1.0, "low": close - 1.0, "close": close, "volume": 1_000})
    return pd.DataFrame(rows, index=dates)


def _bar(start: datetime, open_: float, high: float, low: float, close: float) -> dict:
    return {
        "timestamp": start, "completed_at": start + timedelta(minutes=3),
        "open": open_, "high": high, "low": low, "close": close, "volume": 300,
    }


def test_three_minute_bars_require_all_minutes_and_completion() -> None:
    start = datetime(2026, 9, 4, 9, 30, tzinfo=ET)
    rows = [_minute(start + timedelta(minutes=i), 100 + i) for i in range(3)]
    assert subject.completed_three_minute_bars(rows, as_of=start + timedelta(minutes=2, seconds=59)) == []
    bars = subject.completed_three_minute_bars(rows, as_of=start + timedelta(minutes=3))
    assert len(bars) == 1
    assert bars[0]["open"] == 100
    assert bars[0]["close"] == 102
    assert bars[0]["completed_at"] == start + timedelta(minutes=3)
    assert subject.completed_three_minute_bars(rows[::2], as_of=start + timedelta(minutes=4)) == []


def test_level_map_uses_only_prior_daily_and_labels_custom_input() -> None:
    now = datetime(2026, 9, 4, 10, 0, tzinfo=ET)
    daily = _daily()
    # A same-day daily row must never leak into the level map.
    daily.loc[pd.Timestamp("2026-09-04")] = {"open": 900, "high": 999, "low": 1, "close": 950, "volume": 10}
    minutes = [
        _minute(datetime(2026, 9, 3, 16, 0, tzinfo=ET), 127, high=128, low=126),
        _minute(datetime(2026, 9, 4, 8, 0, tzinfo=ET), 129, high=130, low=128),
    ]
    custom = [{
        "symbol": "SPY", "name": "zoom_level", "price": 131.25, "role": "resistance",
        "session_date": "2026-09-04", "created_at": "2026-09-04T08:00:00-04:00", "source": "user_zoom_notes",
    }]
    result = subject.build_public_level_map("SPY", daily, minutes, now_et=now, custom_levels=custom)
    by_name = {row["name"]: row for row in result["levels"]}
    assert by_name["prior_day_high"]["price"] == 130.0
    assert by_name["overnight_high"]["price"] == 130.0
    assert by_name["premarket_low"]["price"] == 128.0
    assert by_name["zoom_level"]["external_unverified"] is True
    assert by_name["zoom_level"]["provenance"] == "typed_external_input_not_formula_inference"
    assert result["proprietary_formula_inferred"] is False
    assert result["daily_bias"]["state"] == "BULLISH"


def test_lifecycle_distinguishes_watch_armed_confirmed_late_and_invalidated() -> None:
    start = datetime(2026, 9, 4, 9, 30, tzinfo=ET)
    support = {"name": "support", "price": 100.0, "role": "support", "source": "test", "external_unverified": False}
    resistance = {"name": "resistance", "price": 100.0, "role": "resistance", "source": "test", "external_unverified": False}

    watch = subject.classify_lifecycle(support, [_bar(start, 100.25, 100.3, 100.12, 100.15)], daily_atr=2.0)
    assert watch["state"] == "WATCH"

    armed = subject.classify_lifecycle(support, [_bar(start, 100.1, 100.15, 99.95, 100.02)], daily_atr=2.0)
    assert armed["state"] == "ARMED"

    confirmed = subject.classify_lifecycle(
        resistance,
        [_bar(start, 99.7, 99.8, 99.6, 99.7), _bar(start + timedelta(minutes=3), 100.15, 100.25, 99.8, 100.2)],
        daily_atr=2.0,
    )
    assert confirmed["state"] == "CONFIRMED"
    assert confirmed["direction"] == "LONG"
    assert confirmed["reason"] == "completed_reclaim_up"

    late = subject.classify_lifecycle(
        {**support, "role": "two_sided"},
        [_bar(start, 100, 100.1, 99.9, 100), _bar(start + timedelta(minutes=3), 100.9, 101, 100.8, 100.9)],
        daily_atr=2.0,
    )
    assert late["state"] == "LATE"

    invalid = subject.classify_lifecycle(support, [_bar(start, 100.0, 100.05, 99.7, 99.8)], daily_atr=2.0)
    assert invalid["state"] == "INVALIDATED"


def test_report_contract_is_shadow_only_and_append_log_is_idempotent(tmp_path) -> None:
    now = datetime(2026, 9, 4, 9, 33, tzinfo=ET)
    minute = [_minute(datetime(2026, 9, 4, 9, 30, tzinfo=ET) + timedelta(minutes=i), 128.9 + i * 0.05) for i in range(3)]
    report = subject.build_report(
        now_et=now, symbols=["SPY"], daily_frames={"SPY": _daily()}, minute_frames={"SPY": minute},
        custom_level_path=tmp_path / "missing.json",
    )
    assert report["schema_version"] == "daily-level-map-shadow-v1"
    assert report["status"] == "ok"
    assert report["shadow_only"] is True
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["symbols"][0]["confirmation_3m"]["state"] in subject.ALERT_STATES | {"DORMANT"}
    assert "magnet/magnitude" in report["warning"]
    path = tmp_path / "events.jsonl"
    first = subject.append_candidates(report, path)
    second = subject.append_candidates(report, path)
    assert first >= 1
    assert second == 0
    event = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert event["execution_enabled"] is False
    assert event["can_submit_orders"] is False


def test_premarket_contract_exposes_nearest_level_without_claiming_3m_confirmation(tmp_path) -> None:
    now = datetime(2026, 9, 4, 8, 45, tzinfo=ET)
    minute = [_minute(datetime(2026, 9, 4, 8, 43, tzinfo=ET), 129.2)]
    report = subject.build_report(
        now_et=now, symbols=["SPY"], daily_frames={"SPY": _daily()}, minute_frames={"SPY": minute},
        custom_level_path=tmp_path / "missing.json",
    )
    row = report["symbols"][0]
    assert report["status"] == "ok"
    assert report["coverage"]["completed_3m_expected_now"] is False
    assert row["nearest_level"] is not None
    assert row["confirmation_3m"]["state"] == "PREMARKET"
    assert row["confirmation_3m"]["direction"] == "NONE"


def test_failed_alert_transition_is_not_acknowledged_and_retries(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    lifecycle = {
        "level_name": "prior_day_high", "level": 100.0, "level_role": "resistance",
        "level_source": "last_completed_daily_bar", "external_unverified": False,
        "state": "WATCH", "direction": "LONG", "last_price": 99.8,
        "reason": "approaching_mapped_level", "bar_completed_at": "2026-09-04T09:33:00-04:00",
    }
    report = {"generated_at": "2026-09-04T13:33:01Z", "observations": [{"symbol": "SPY", "daily_bias": {"state": "BULLISH"}, "lifecycles": [lifecycle]}]}
    assert subject.send_state_change_alerts(
        report, state_path=state_path,
        sender=lambda _: {"delivered": False, "attempts": 3, "error_class": "http_429"},
    ) == 0
    assert report["notification_attempts"] == 3
    assert report["notification_transitions"] == 1
    assert report["notification_failures"] == 1
    assert report["notification_error_classes"] == {"http_429": 1}
    assert "webhook" not in json.dumps(report.get("notification_results") or []).lower()
    assert json.loads(state_path.read_text(encoding="utf-8"))["states"] == {}

    assert subject.send_state_change_alerts(
        report, state_path=state_path,
        sender=lambda _: {"delivered": True, "attempts": 2, "error_class": None},
    ) == 1
    assert report["notification_attempts"] == 2
    assert json.loads(state_path.read_text(encoding="utf-8"))["states"]["SPY|prior_day_high|100.0"] == "WATCH"
    assert subject.send_state_change_alerts(
        report, state_path=state_path,
        sender=lambda _: {"delivered": True, "attempts": 1, "error_class": None},
    ) == 0
    assert report["notification_attempts"] == 0


def test_direct_alert_transition_is_persisted_with_delivery_and_chart_fields(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    event_path = tmp_path / "events.jsonl"
    lifecycle = {
        "level_name": "prior_day_high", "level": 100.0, "level_role": "resistance",
        "level_source": "last_completed_daily_bar", "external_unverified": False,
        "state": "ARMED", "direction": "SHORT", "last_price": 99.8,
        "reason": "rejected_mapped_resistance", "bar_completed_at": "2026-09-04T09:33:00-04:00",
    }
    report = {
        "generated_at": "2026-09-04T13:33:05Z",
        "symbols": [{
            "symbol": "SPY", "nearest_level": {"type": "prior_day_high", "price": 100.0},
            "confirmation_3m": {"state": "ARMED", "trigger": 99.8, "invalidation": 100.1, "next_target": 99.0},
        }],
        "observations": [{
            "symbol": "SPY", "daily_bias": {"state": "BEARISH"}, "lifecycles": [lifecycle],
            "completed_3m_bar_count": 1, "confirmation_3m_fresh": True,
        }],
    }

    assert subject.send_state_change_alerts(
        report, state_path=state_path, event_path=event_path,
        sender=lambda _message: {"delivered": True, "attempts": 1, "error_class": None},
    ) == 1
    event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[0])
    assert event["delivered"] is True
    assert event["attempted_at"]
    assert event["bar_completed_at"] == "2026-09-04T09:33:00-04:00"
    assert event["trigger"] == 99.8
    assert event["stop"] == 100.1
    assert event["target"] == 99.0


def test_default_alert_transport_uses_governed_retry_result(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "state.json"
    observed: list[str] = []

    def governed_delivery(message: str) -> dict:
        observed.append(message)
        return {"delivered": False, "attempts": 3, "error_class": "ConnectionError"}

    monkeypatch.setattr(subject.governed_shadow_alert, "deliver", governed_delivery)
    lifecycle = {
        "level_name": "prior_day_high", "level": 100.0, "level_role": "resistance",
        "level_source": "last_completed_daily_bar", "external_unverified": False,
        "state": "WATCH", "direction": "LONG", "last_price": 99.8,
        "reason": "approaching_mapped_level", "bar_completed_at": "2026-09-04T09:33:00-04:00",
    }
    report = {
        "generated_at": "2026-09-04T13:33:01Z",
        "symbols": [{
            "symbol": "SPY", "nearest_level": {"type": "prior_day_high", "price": 100.0},
            "confirmation_3m": {"state": "WATCH", "trigger": 100.0},
        }],
        "observations": [{
            "symbol": "SPY", "daily_bias": {"state": "BULLISH"}, "lifecycles": [lifecycle],
            "completed_3m_bar_count": 1, "confirmation_3m_fresh": True,
        }],
    }

    assert subject.send_state_change_alerts(report, state_path=state_path) == 0
    assert len(observed) == 1
    assert report["notification_attempts"] == 3
    assert report["notification_error_classes"] == {"ConnectionError": 1}
    assert json.loads(state_path.read_text(encoding="utf-8"))["states"] == {}


def test_external_expiration_is_explicitly_invalidated() -> None:
    level = {
        "name": "expired", "price": 100.0, "role": "two_sided", "source": "user",
        "external_unverified": True, "expired": True,
    }
    result = subject.classify_lifecycle(level, [], daily_atr=2.0)
    assert result["state"] == "INVALIDATED"
    assert result["reason"] == "external_level_expired"


def test_report_is_partial_when_rth_confirmation_feed_is_missing(tmp_path) -> None:
    report = subject.build_report(
        now_et=datetime(2026, 9, 4, 10, 0, tzinfo=ET), symbols=["SPY"],
        daily_frames={"SPY": _daily()}, minute_frames={"SPY": []},
        custom_level_path=tmp_path / "missing.json",
    )
    assert report["status"] == "partial"
    assert report["coverage"]["completed_3m_expected_now"] is True
    assert report["coverage"]["completed_3m_available"] == 0


def test_stale_intraday_bar_marks_report_partial_and_suppresses_direct_alert(tmp_path) -> None:
    start = datetime(2026, 9, 4, 9, 30, tzinfo=ET)
    minute = [_minute(start + timedelta(minutes=i), 128.9 + i * 0.05) for i in range(3)]
    report = subject.build_report(
        now_et=datetime(2026, 9, 4, 15, 0, tzinfo=ET), symbols=["SPY"],
        daily_frames={"SPY": _daily()}, minute_frames={"SPY": minute},
        custom_level_path=tmp_path / "missing.json",
    )
    assert report["status"] == "partial"
    assert report["coverage"]["completed_3m_available"] == 1
    assert report["coverage"]["completed_3m_fresh"] == 0
    messages = []
    assert subject.send_state_change_alerts(
        report, state_path=tmp_path / "state.json", sender=lambda message: messages.append(message) or True,
    ) == 0
    assert messages == []


def test_postmarket_stale_intraday_state_cannot_emit_direct_alert(tmp_path) -> None:
    start = datetime(2026, 9, 4, 9, 30, tzinfo=ET)
    minute = [_minute(start + timedelta(minutes=i), 128.9 + i * 0.05) for i in range(3)]
    report = subject.build_report(
        now_et=datetime(2026, 9, 4, 17, 0, tzinfo=ET), symbols=["SPY"],
        daily_frames={"SPY": _daily()}, minute_frames={"SPY": minute},
        custom_level_path=tmp_path / "missing.json",
    )
    messages = []
    assert report["session_state"] == "postmarket"
    assert subject.send_state_change_alerts(
        report, state_path=tmp_path / "state.json", sender=lambda message: messages.append(message) or True,
    ) == 0
    assert messages == []


def test_malformed_custom_level_is_reported_not_silently_accepted(tmp_path) -> None:
    path = tmp_path / "custom.json"
    path.write_text(json.dumps({"schema_version": 1, "levels": [{"symbol": "SPY", "price": 100}]}), encoding="utf-8")
    levels, errors = subject.load_custom_levels(path, now_et=datetime(2026, 9, 4, 8, 0, tzinfo=ET))
    assert levels == []
    assert errors == ["custom_level_0:missing_required_fields"]


def test_dashboard_contract_has_deterministic_2r_target_when_no_higher_level_exists() -> None:
    observation = {
        "symbol": "SPY", "status": "available", "daily_bias": {"state": "BULLISH"},
        "levels": [{"name": "prior_day_high", "price": 100.0, "role": "resistance", "source": "daily"}],
        "lifecycles": [{
            "level_name": "prior_day_high", "level": 100.0, "level_role": "resistance",
            "level_source": "daily", "external_unverified": False, "zone": 0.1,
            "state": "CONFIRMED", "direction": "LONG", "reason": "completed_reclaim_up",
            "last_price": 100.2, "distance_points": 0.2,
            "bar_completed_at": "2026-09-04T09:36:00-04:00",
        }],
    }
    contract = subject._dashboard_symbol_contract(observation)
    assert contract["confirmation_3m"]["invalidation"] == 99.9
    assert contract["confirmation_3m"]["next_target"] == 100.2
    assert contract["confirmation_3m"]["next_target_type"] == "risk_projection_2r"
