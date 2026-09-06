from __future__ import annotations

from datetime import datetime, timezone

import json
from scripts import discord_alert_chart_review as review
from scripts import spy_level_reaction_shadow as spy_levels
from scripts.discord_alert_chart_review import evaluate_alert


def _alert(**overrides):
    row = {
        "symbol": "QQQ", "direction": "SHORT", "setup": "rollover",
        "grade": "B+", "entry": 100.0, "stop": 101.0, "target": 98.0,
        "attempted_at": "2026-09-04T14:01:30Z", "source": "governed",
    }
    row.update(overrides)
    return row


def test_execution_review_never_credits_price_action_before_discord_delivery() -> None:
    bars = [
        {"t": "2026-09-04T14:01:00Z", "o": 100.0, "h": 102.0, "l": 97.0, "c": 98.0},
        {"t": "2026-09-04T14:02:00Z", "o": 100.5, "h": 101.1, "l": 100.2, "c": 100.8},
    ]

    result = evaluate_alert(
        _alert(), bars, now=datetime(2026, 9, 4, 15, 2, tzinfo=timezone.utc),
    )

    assert result["status"] == "invalidated_before_entry"
    assert result["entry_filled"] is False


def test_execution_review_reprices_a_chased_fill_instead_of_using_hindsight_trigger() -> None:
    bars = [
        {"t": "2026-09-04T14:02:00Z", "o": 99.5, "h": 99.7, "l": 98.8, "c": 99.0},
        {"t": "2026-09-04T14:03:00Z", "o": 99.0, "h": 99.1, "l": 97.9, "c": 98.0},
    ]

    result = evaluate_alert(
        _alert(), bars, now=datetime(2026, 9, 4, 15, 2, tzinfo=timezone.utc),
    )

    assert result["status"] == "evaluated"
    assert result["fill"] == 99.5
    assert result["slipped_from_trigger"] is True
    assert result["outcome_r"] == 1.0


def test_mapped_level_alerts_are_persisted_and_evaluated(tmp_path, monkeypatch) -> None:
    event_path = tmp_path / "spy-events.jsonl"
    event = spy_levels.record_alert_delivery(
        {"level_name": "prior_day_high", "state": "ARMED", "direction": "SHORT", "entry": 100.0, "stop": 101.0, "target": 98.0, "bar_completed_at": "2026-09-04T14:00:00Z"},
        {"delivered": True, "attempts": 1, "error_class": None}, event_path=event_path,
        attempted_at="2026-09-04T14:03:20Z",
    )
    monkeypatch.setattr(review, "SPY_LEVEL_EVENTS", event_path)
    monkeypatch.setattr(review, "GOVERNED_EVENTS", tmp_path / "none1")
    monkeypatch.setattr(review, "DECISION_LEDGER", tmp_path / "none2")
    monkeypatch.setattr(review, "BPLUS_LOG", tmp_path / "none3")
    monkeypatch.setattr(review, "APLUS_LOG", tmp_path / "none5")
    monkeypatch.setattr(review, "DAILY_MAP_EVENTS", tmp_path / "none4")

    alerts = review.delivered_alerts("2026-09-04")
    result = evaluate_alert(alerts[0], [{"t": "2026-09-04T14:04:00Z", "o": 99.8, "h": 100.0, "l": 97.9, "c": 98.0}], now=datetime(2026, 9, 4, 15, 4, tzinfo=timezone.utc))

    assert json.loads(event_path.read_text())["event_id"] == event["event_id"]
    assert alerts[0]["attempted_at"] == "2026-09-04T14:03:20Z"
    assert alerts[0]["delivery_timestamp_quality"] == "attempt_only"
    assert result["first_eligible_bar"] == "2026-09-04T14:04:00Z"


def test_truncated_bar_history_cannot_be_scored_as_a_time_exit():
    result = evaluate_alert(_alert(), [{"t": "2026-09-04T14:02:00Z", "o": 100.0, "h": 100.2, "l": 99.8, "c": 99.9}], now=datetime(2026, 9, 4, 16, tzinfo=timezone.utc))
    assert result["status"] == "incomplete_bar_history"
    assert result.get("outcome_r") is None


def test_stop_gap_is_priced_at_open_and_can_lose_more_than_one_r():
    bars = [
        {"t": "2026-09-04T14:02:00Z", "o": 100.0, "h": 100.2, "l": 99.8, "c": 100.0},
        {"t": "2026-09-04T14:03:00Z", "o": 102.0, "h": 102.2, "l": 101.8, "c": 102.0},
    ]
    result = evaluate_alert(_alert(), bars, now=datetime(2026, 9, 4, 16, tzinfo=timezone.utc))
    assert result["outcome_r"] == -2.0


def test_missing_minute_before_target_cannot_hide_a_stop():
    bars = [
        {"t": "2026-09-04T14:02:00Z", "o": 100.0, "h": 100.2, "l": 99.8, "c": 100.0},
        {"t": "2026-09-04T14:04:00Z", "o": 99.0, "h": 99.2, "l": 97.8, "c": 98.0},
    ]
    result = evaluate_alert(_alert(), bars, now=datetime(2026, 9, 4, 16, tzinfo=timezone.utc))
    assert result["status"] == "incomplete_bar_history"


def test_api_pagination_retains_symbols_on_later_pages(monkeypatch):
    calls = []
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"bars": {"SPY": [{"t": "first"}]}, "next_page_token": "page2"} if len(calls) == 1 else {"bars": {"QQQ": [{"t": "second"}]}, "next_page_token": None}
    def get(*args, **kwargs):
        calls.append(kwargs["params"])
        return Response()
    monkeypatch.setattr(review.requests, "get", get)
    monkeypatch.setattr(review, "_credentials", lambda: {})
    bars = review.fetch_bars(["SPY", "QQQ"], "2026-09-04")
    assert set(bars) == {"SPY", "QQQ"}
    assert calls[1]["page_token"] == "page2"


def test_report_statistics_count_duplicate_plan_once(monkeypatch):
    rows = [_alert(alert_id="one", delivered_at="2026-09-04T14:01:30Z", delivery_timestamp_quality="exact"), _alert(alert_id="two", delivered_at="2026-09-04T14:02:30Z", delivery_timestamp_quality="exact", source="aplus_spotlight")]
    monkeypatch.setattr(review, "delivered_alerts", lambda _: rows)
    monkeypatch.setattr(review, "fetch_bars", lambda *_: {"QQQ": [{"t": "2026-09-04T14:02:00Z", "o": 100.0, "h": 100.2, "l": 97.8, "c": 98.0}]})
    report = review.build_report("2026-09-04", now=datetime(2026, 9, 4, 16, tzinfo=timezone.utc))
    assert report["summary"]["evaluated"] == 1
    assert report["summary"]["duplicate_trade_alerts"] == 1
    assert report["alerts"][1]["calibration_eligible"] is False


def test_aplus_partial_delivery_only_reviews_acknowledged_receipt(monkeypatch):
    setup = {"fingerprint": "sent", "symbol": "SPY", "direction": "bullish", "entry": 100, "invalidation": 99, "target": 102}
    log = {"timestamp": "2026-09-04T14:02:00Z", "setups": [setup, {**setup, "fingerprint": "failed"}], "notification": {"status": "partial", "results": [{"fingerprint": "sent", "result": {"sent": True}, "delivered_at": "2026-09-04T14:01:20Z"}, {"fingerprint": "failed", "result": {"sent": False}}]}}
    monkeypatch.setattr(review, "_read_jsonl", lambda path: [log] if path == review.APLUS_LOG else [])
    alerts = review.delivered_alerts("2026-09-04")
    assert len(alerts) == 1
    assert alerts[0]["source"] == "aplus_spotlight"
    assert alerts[0]["delivered_at"] == "2026-09-04T14:01:20Z"
    assert alerts[0]["delivery_timestamp_quality"] == "exact"


def test_provider_failure_is_visible_and_never_scores(monkeypatch):
    monkeypatch.setattr(review, "delivered_alerts", lambda _: [_alert()])
    def fail(*_):
        raise review.requests.Timeout("sensitive transport detail")
    monkeypatch.setattr(review, "fetch_bars", fail)
    report = review.build_report("2026-09-04", now=datetime(2026, 9, 4, 16, tzinfo=timezone.utc))
    assert report["feed_status"] == "missing"
    assert report["feed_error_class"] == "Timeout"
    assert report["summary"]["evaluated"] == 0
