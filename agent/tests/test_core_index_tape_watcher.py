from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from scripts.core_index_tape_watcher import (
    build_observation,
    build_report,
    completed_minute_bars,
    persist_run,
)


ET = ZoneInfo("America/New_York")


def _bar(minute: int, open_: float, close: float, volume: int = 100_000) -> dict:
    return {
        "t": f"2026-09-04T13:{minute:02d}:00Z",
        "o": open_,
        "h": max(open_, close) + 0.05,
        "l": min(open_, close) - 0.05,
        "c": close,
        "v": volume,
    }


def test_completed_minute_bars_excludes_still_forming_provider_bar() -> None:
    rows = [_bar(30, 770.0, 769.8), _bar(31, 769.8, 769.7)]

    completed = completed_minute_bars(rows, datetime(2026, 9, 4, 9, 31, 30, tzinfo=ET))

    assert [row["t"] for row in completed] == ["2026-09-04T13:30:00Z"]


def test_two_completed_minutes_arm_bearish_index_pressure_before_five_minute_confirmation() -> None:
    rows = [_bar(30, 770.0, 769.5), _bar(31, 769.5, 769.0, 160_000)]

    observation = build_observation(
        "SPY",
        rows,
        now_et=datetime(2026, 9, 4, 9, 32, 5, tzinfo=ET),
        previous=None,
    )

    assert observation["state"] == "ARMED"
    assert observation["direction"] == "SHORT"
    assert observation["bar_completed_at"] == "2026-09-04T13:32:00Z"
    assert observation["detection_latency_seconds"] == 5.0
    assert observation["execution_enabled"] is False
    assert observation["can_submit_orders"] is False


def test_same_direction_second_transition_confirms_and_alerts_are_idempotent(tmp_path) -> None:
    calls: list[str] = []

    def sender(message: str) -> dict:
        calls.append(message)
        return {"delivered": True, "attempts": 1, "error_class": None}

    armed = build_observation(
        "QQQ",
        [_bar(30, 720.0, 719.55), _bar(31, 719.55, 719.05)],
        now_et=datetime(2026, 9, 4, 9, 32, 3, tzinfo=ET),
        previous=None,
    )
    report = {"generated_at": "2026-09-04T13:32:03Z", "observations": [armed]}
    state_path = tmp_path / "state.json"
    report_path = tmp_path / "report.json"
    event_path = tmp_path / "events.jsonl"

    clock = lambda: datetime.fromisoformat(report["generated_at"].replace("Z", "+00:00"))
    persist_run(report, state_path=state_path, report_path=report_path, event_path=event_path, alert=True, sender=sender, utc_clock=clock)
    persist_run(report, state_path=state_path, report_path=report_path, event_path=event_path, alert=True, sender=sender, utc_clock=clock)

    assert len(calls) == 1
    assert "ARMED" in calls[0]
    assert "No order placed" in calls[0]

    confirmed = build_observation(
        "QQQ",
        [_bar(30, 720.0, 719.55), _bar(31, 719.55, 719.05), _bar(32, 719.05, 718.65)],
        now_et=datetime(2026, 9, 4, 9, 33, 2, tzinfo=ET),
        previous=armed,
    )
    confirm_report = {"generated_at": "2026-09-04T13:33:02Z", "observations": [confirmed]}
    persist_run(confirm_report, state_path=state_path, report_path=report_path, event_path=event_path, alert=True, sender=sender, utc_clock=lambda: datetime(2026, 9, 4, 13, 33, 2, tzinfo=timezone.utc))

    assert confirmed["state"] == "CONFIRMED"
    assert len(calls) == 2
    assert "CONFIRMED" in calls[-1]


def test_new_session_does_not_inherit_prior_active_state() -> None:
    previous = {
        "session_date": "2026-09-03",
        "state": "CONFIRMED",
        "direction": "LONG",
        "bar_completed_at": "2026-09-03T14:00:00Z",
    }
    rows = [_bar(30, 770.0, 769.5), _bar(31, 769.5, 769.0)]

    observation = build_observation(
        "SPY", rows, now_et=datetime(2026, 9, 4, 9, 32, 5, tzinfo=ET), previous=previous
    )

    assert observation["previous_state"] == "NONE"
    assert observation["state"] == "ARMED"


def test_known_exchange_holiday_is_a_clean_noop(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.core_index_tape_watcher.fetch_completed_1m",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("provider must not be called")),
    )

    report = build_report(now_et=datetime(2026, 9, 7, 10, 0, tzinfo=ET), previous_state={})

    assert report["status"] == "market_closed"
    assert report["alerts_sent"] == 0


def test_qqq_tradingview_rollover_invalidates_long_and_confirms_short_above_session_vwap() -> None:
    """Sep-4 TradingView pattern: displacement, lower-high bounce, continuation."""
    rows = [
        {"t": "2026-09-04T13:30:00Z", "o": 719.16, "h": 719.40, "l": 718.50, "c": 719.05, "v": 4_000},
        {"t": "2026-09-04T13:55:00Z", "o": 721.10, "h": 721.46, "l": 721.005, "c": 721.46, "v": 1_480},
        {"t": "2026-09-04T13:56:00Z", "o": 721.45, "h": 721.61, "l": 721.45, "c": 721.48, "v": 581},
        {"t": "2026-09-04T13:57:00Z", "o": 721.615, "h": 721.66, "l": 721.615, "c": 721.625, "v": 324},
        {"t": "2026-09-04T13:58:00Z", "o": 721.74, "h": 721.84, "l": 721.73, "c": 721.73, "v": 872},
        {"t": "2026-09-04T13:59:00Z", "o": 721.76, "h": 721.76, "l": 721.48, "c": 721.645, "v": 1_278},
        {"t": "2026-09-04T14:00:00Z", "o": 721.77, "h": 721.77, "l": 721.52, "c": 721.60, "v": 2_407},
        {"t": "2026-09-04T14:01:00Z", "o": 721.50, "h": 721.50, "l": 721.03, "c": 721.06, "v": 2_658},
        {"t": "2026-09-04T14:02:00Z", "o": 721.12, "h": 721.34, "l": 721.03, "c": 721.10, "v": 1_131},
        {"t": "2026-09-04T14:03:00Z", "o": 721.27, "h": 721.51, "l": 721.145, "c": 721.375, "v": 1_010},
        {"t": "2026-09-04T14:04:00Z", "o": 721.33, "h": 721.36, "l": 721.19, "c": 721.25, "v": 1_057},
    ]
    long_state = {
        "session_date": "2026-09-04", "state": "CONFIRMED", "direction": "LONG",
        "bar_completed_at": "2026-09-04T14:01:00Z",
    }

    invalidated = build_observation(
        "QQQ", rows[:8], now_et=datetime(2026, 9, 4, 10, 2, 5, tzinfo=ET), previous=long_state,
    )
    armed = build_observation(
        "QQQ", rows[:9], now_et=datetime(2026, 9, 4, 10, 3, 5, tzinfo=ET), previous=invalidated,
    )
    waiting = build_observation(
        "QQQ", rows[:10], now_et=datetime(2026, 9, 4, 10, 4, 5, tzinfo=ET), previous=armed,
    )
    confirmed = build_observation(
        "QQQ", rows, now_et=datetime(2026, 9, 4, 10, 5, 5, tzinfo=ET), previous=waiting,
    )

    assert invalidated["state"] == "INVALIDATED"
    assert invalidated["reversal_direction"] == "SHORT"
    assert armed["state"] == "ARMED"
    assert armed["direction"] == "SHORT"
    assert confirmed["state"] == "CONFIRMED"
    assert confirmed["direction"] == "SHORT"
    assert confirmed["last_price"] > confirmed["session_vwap"]


def test_reclaimed_rolling_reversal_is_not_rearmed_from_same_session_high() -> None:
    rows = [
        {"t": "2026-09-04T13:30:00Z", "o": 719.0, "h": 719.2, "l": 718.8, "c": 719.0, "v": 1_000},
        {"t": "2026-09-04T13:58:00Z", "o": 721.6, "h": 721.84, "l": 721.5, "c": 721.73, "v": 1_000},
        {"t": "2026-09-04T13:59:00Z", "o": 721.73, "h": 721.76, "l": 721.48, "c": 721.64, "v": 1_000},
        {"t": "2026-09-04T14:00:00Z", "o": 721.64, "h": 721.70, "l": 721.45, "c": 721.55, "v": 1_000},
        {"t": "2026-09-04T14:01:00Z", "o": 721.55, "h": 721.58, "l": 721.00, "c": 721.05, "v": 2_000},
        {"t": "2026-09-04T14:02:00Z", "o": 721.05, "h": 721.30, "l": 721.00, "c": 721.10, "v": 1_000},
        {"t": "2026-09-04T14:03:00Z", "o": 721.25, "h": 721.50, "l": 721.10, "c": 721.35, "v": 1_000},
        {"t": "2026-09-04T14:04:00Z", "o": 721.35, "h": 721.38, "l": 721.15, "c": 721.20, "v": 1_000},
    ]
    armed = build_observation(
        "QQQ", rows[:-2], now_et=datetime(2026, 9, 4, 10, 3, 5, tzinfo=ET), previous=None,
    )
    confirmed = build_observation(
        "QQQ", rows, now_et=datetime(2026, 9, 4, 10, 5, 5, tzinfo=ET), previous=build_observation(
            "QQQ", rows[:-1], now_et=datetime(2026, 9, 4, 10, 4, 5, tzinfo=ET), previous=armed,
        ),
    )
    reclaimed_rows = [
        *rows,
        {"t": "2026-09-04T14:05:00Z", "o": 721.20, "h": 721.80, "l": 721.18, "c": 721.75, "v": 1_000},
    ]
    invalidated = build_observation(
        "QQQ", reclaimed_rows, now_et=datetime(2026, 9, 4, 10, 6, 5, tzinfo=ET), previous=confirmed,
    )
    retry_rows = [
        *reclaimed_rows,
        {"t": "2026-09-04T14:06:00Z", "o": 721.30, "h": 721.35, "l": 721.15, "c": 721.20, "v": 1_000},
    ]
    suppressed = build_observation(
        "QQQ", retry_rows, now_et=datetime(2026, 9, 4, 10, 7, 5, tzinfo=ET), previous=invalidated,
    )

    assert confirmed["state"] == "CONFIRMED"
    assert invalidated["state"] == "INVALIDATED"
    assert suppressed["reversal_direction"] == "NONE"
    assert suppressed["state"] == "WATCH"


def _armed():
    rows = [_bar(30, 720, 719.5), _bar(31, 719.5, 719)]
    now = datetime(2026, 9, 4, 9, 32, 5, tzinfo=ET)
    return rows, now, build_observation("QQQ", rows, now_et=now, previous=None)


def test_missing_and_stale_data_preserve_active_state_without_realerts():
    rows, now, armed = _armed()
    for payload, moment, quality in (([], now + timedelta(minutes=1), "missing"),
                                     (rows, now + timedelta(minutes=2), "stale")):
        observed = build_observation("QQQ", payload, now_et=moment, previous=armed)
        assert observed["state"] == "ARMED"
        assert observed["direction"] == "SHORT"
        assert observed["bar_completed_at"] == armed["bar_completed_at"]
        assert observed["data_status"] == quality
        assert not observed["transition"] and not observed["alertable"]


def test_same_bar_preserves_confirmed_state_and_cannot_realert():
    rows, now, armed = _armed()
    rows.append(_bar(32, 719, 718.5))
    confirmed = build_observation("QQQ", rows, now_et=now + timedelta(minutes=1), previous=armed)
    duplicate = build_observation("QQQ", rows, now_et=now + timedelta(minutes=1, seconds=5), previous=confirmed)
    assert confirmed["state"] == duplicate["state"] == "CONFIRMED"
    assert duplicate["data_status"] == "unchanged"
    assert not duplicate["transition"]


def test_gap_in_rows_or_observations_cannot_confirm():
    rows, now, armed = _armed()
    gap = build_observation("QQQ", [*rows, _bar(33, 719, 718)], now_et=now + timedelta(minutes=2), previous=armed)
    assert gap["state"] == "ARMED" and gap["data_status"] == "gap"
    resumed = build_observation("QQQ", [*rows, _bar(32, 719, 718.5), _bar(33, 718.5, 718)], now_et=now + timedelta(minutes=2), previous=armed)
    assert resumed["state"] == "ARMED"
    assert not resumed["transition"]


def test_invalid_ohlcv_and_previous_session_are_not_market_evidence():
    rows, now, _ = _armed()
    invalid = [{**rows[0], "h": 710}, {**rows[1], "v": -1},
               {**rows[0], "t": "2026-09-03T13:30:00Z"}, {**rows[0], "o": 0}]
    assert completed_minute_bars(invalid, now) == []


def test_missing_feed_is_degraded_even_while_prior_state_is_preserved(monkeypatch):
    _, now, armed = _armed()
    monkeypatch.setattr("scripts.core_index_tape_watcher.fetch_completed_1m", lambda *a, **kw: ({}, []))
    report = build_report(now_et=now + timedelta(minutes=2), previous_state={"observations": {"QQQ": armed}})
    assert report["status"] == "degraded"
    assert report["coverage"]["observed"] == 0
    assert next(row for row in report["observations"] if row["symbol"] == "QQQ")["state"] == "ARMED"


def test_rolling_reversal_invalidates_on_objective_opposite_velocity():
    rows = [_bar(30, 720, 720), _bar(31, 720, 720.2), _bar(32, 720.2, 721.2)]
    previous = {"session_date": "2026-09-04", "state": "CONFIRMED", "direction": "SHORT",
                "pressure_mode": "rolling_reversal", "reversal_extreme": 725,
                "active_reversal_id": "SHORT|test", "bar_completed_at": "2026-09-04T13:32:00Z"}
    observed = build_observation("QQQ", rows, now_et=datetime(2026, 9, 4, 9, 33, 5, tzinfo=ET), previous=previous)
    assert observed["state"] == "INVALIDATED"
    assert observed["reason"] == "opposite_one_minute_pressure"
    assert "SHORT|test" in observed["consumed_reversal_ids"]


def test_unconfirmed_rolling_reversal_expires_by_existing_setup_horizon():
    rows = [_bar(50, 720, 720), _bar(51, 720, 720), _bar(52, 720, 720)]
    previous = {"session_date": "2026-09-04", "state": "ARMED", "direction": "SHORT",
                "pressure_mode": "rolling_reversal", "reversal_extreme": 725,
                "active_reversal_id": "SHORT|test", "active_started_at": "2026-09-04T13:32:00Z",
                "bar_completed_at": "2026-09-04T13:52:00Z"}
    observed = build_observation("QQQ", rows, now_et=datetime(2026, 9, 4, 9, 53, 5, tzinfo=ET), previous=previous)
    assert observed["state"] == "INVALIDATED"
    assert observed["reason"] == "rolling_reversal_confirmation_expired"


def test_failed_alert_retry_expires_and_delivery_attempt_is_durable(tmp_path):
    _, now, armed = _armed()
    report = {"generated_at": now.isoformat(), "observations": [armed]}
    paths = dict(state_path=tmp_path / "state.json", report_path=tmp_path / "report.json", event_path=tmp_path / "events.jsonl")
    calls = []
    def fail(message):
        calls.append(message)
        raise TimeoutError("transport unavailable")
    persist_run(report, **paths, alert=True, sender=fail, utc_clock=lambda: now)
    events = [json.loads(line) for line in (tmp_path / "events_deliveries.jsonl").read_text().splitlines()]
    assert report["pending_delivery"] == 1
    assert events[0]["attempted_at"] == "2026-09-04T13:32:05Z"
    assert events[0]["delivered_at"] is None
    assert events[0]["delivery_result"]["error_class"] == "TimeoutError"
    persist_run(report, **paths, alert=True, sender=fail, utc_clock=lambda: now + timedelta(minutes=2))
    assert len(calls) == 1
    assert report["pending_delivery"] == 0
    assert report["dropped_delivery_reasons"] == {"expired": 1}


def test_confirmed_transition_supersedes_failed_armed_retry(tmp_path):
    rows, now, armed = _armed()
    paths = dict(state_path=tmp_path / "state.json", report_path=tmp_path / "report.json", event_path=tmp_path / "events.jsonl")
    persist_run({"generated_at": now.isoformat(), "observations": [armed]}, **paths, alert=True,
                sender=lambda _: {"delivered": False, "attempts": 1}, utc_clock=lambda: now)
    confirmed = build_observation("QQQ", [*rows, _bar(32, 719, 718.5)], now_et=now + timedelta(minutes=1), previous=armed)
    report = {"generated_at": (now + timedelta(minutes=1)).isoformat(), "observations": [confirmed]}
    calls = []
    def success(message):
        calls.append(message)
        return {"delivered": True, "attempts": 1, "discord_message_id": "123456789",
                "discord_delivered_ts": "2026-09-04T13:33:05Z",
                "ack_receipt_ts": "2026-09-04T13:33:05Z"}
    persist_run(report, **paths, alert=True, sender=success, utc_clock=lambda: now + timedelta(minutes=1))
    assert len(calls) == 1 and "CONFIRMED" in calls[0]
    assert report["dropped_delivery_reasons"] == {"superseded": 1}
    delivered = json.loads((tmp_path / "events_deliveries.jsonl").read_text().splitlines()[-1])
    assert delivered["delivered_at"] == "2026-09-04T13:33:05Z"
    assert delivered["delivery_timestamp_semantics"] == "discord_message_timestamp"
    assert delivered["execution_enabled"] is False
