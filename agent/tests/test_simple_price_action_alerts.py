from __future__ import annotations

import json
from pathlib import Path

from scripts import simple_price_action_alerts as alerts

from scripts.simple_price_action_alerts import (
    build_report,
    compact_daily_map_signal,
    compact_signal,
    format_notification,
    record_current_signals,
    send_state_change_alerts,
)


def test_discord_sender_executes_http_post_when_webhook_exists(monkeypatch) -> None:
    observed = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["body"] = request.data
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr(alerts, "webhook_url", lambda: "https://discord.invalid/webhook")
    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)

    assert alerts._post_discord("SPY confirmed") is True
    assert observed["url"] == "https://discord.invalid/webhook"
    assert json.loads(observed["body"])["content"] == "SPY confirmed"
    assert observed["timeout"] == 10


def _candidate(**overrides):
    row = {
        "symbol": "TEST",
        "state": "precision_watch",
        "grade": "A-",
        "score": 82,
        "direction": "bullish",
        "setup": "opening_range_breakout",
        "price": 11.2,
        "hard_gates": {
            "price_floor": True,
            "completed_5m_structure": True,
            "underlying_spread": True,
            "dollar_liquidity": True,
            "meaningful_move_or_activity": True,
        },
        "price_action_confirmation": {
            "state": "bullish_confirmed",
            "pattern": "breakout_retest_hold",
            "bar_completed_at": "2026-08-20T15:00:00Z",
        },
        "trade_levels": {
            "confirmation_trigger": 11.1,
            "invalidation": 10.8,
            "target_2r": 11.7,
        },
    }
    row.update(overrides)
    return row


def test_green_requires_confirmation_and_every_quality_gate() -> None:
    signal = compact_signal(_candidate())

    assert signal["state"] == "CONFIRMED"
    assert signal["color"] == "GREEN"
    assert signal["trigger"] == 11.1
    assert signal["can_submit_orders"] is False


def test_wait_is_yellow_when_closed_bar_has_not_confirmed() -> None:
    signal = compact_signal(_candidate(price_action_confirmation={"state": "waiting", "pattern": "no_closed_bar_confirmation"}))

    assert signal["state"] == "WAIT"
    assert signal["color"] == "YELLOW"


def test_confirmed_pattern_stays_yellow_when_quality_score_is_too_low() -> None:
    signal = compact_signal(_candidate(score=68))

    assert signal["state"] == "WAIT"
    assert signal["decisive_reason"] == "setup_quality_below_B_plus"


def test_loaded_execution_review_blocks_green_until_manual_review_is_eligible() -> None:
    report = build_report(
        {"ranked_candidates": [_candidate()]},
        {"plans": [{
            "symbol": "TEST",
            "decision_contract": {"outcome": "do_not_take", "reasons": ["same_time_rvol_below_1"]},
        }]},
    )

    signal = report["signals"][0]
    assert signal["state"] == "WAIT"
    assert signal["color"] == "YELLOW"
    assert signal["decisive_reason"] == "manual_execution_review_not_eligible"
    assert signal["execution_review_outcome"] == "do_not_take"


def test_core_index_confirmation_is_visible_despite_grade_and_manual_review() -> None:
    report = build_report(
        {"ranked_candidates": [_candidate(symbol="SPY", score=63, grade="B-")]},
        {"plans": [{
            "symbol": "SPY",
            "decision_contract": {"outcome": "do_not_take", "reasons": ["candidate_only"]},
        }]},
    )

    signal = report["signals"][0]
    assert signal["state"] == "CONFIRMED"
    assert signal["lane"] == "CORE_INDEX_SHADOW"
    assert signal["always_visible"] is True
    assert signal["index_proxy_for"] == ["SPX", "SPXW"]
    assert signal["execution_enabled"] is False


def test_core_index_wait_alert_is_sent_once_then_confirmation_alerts(tmp_path: Path) -> None:
    waiting = build_report({"ranked_candidates": [_candidate(
        symbol="QQQ",
        score=65,
        state="watch",
        price_action_confirmation={"state": "waiting", "pattern": "level_retest_pending"},
    )]})
    confirmed = build_report({"ranked_candidates": [_candidate(symbol="QQQ", score=65, state="watch")]})
    messages: list[str] = []
    sender = lambda message: messages.append(message) or True
    state_path = tmp_path / "core-state.json"

    assert send_state_change_alerts(waiting, state_path=state_path, sender=sender) == 1
    assert send_state_change_alerts(waiting, state_path=state_path, sender=sender) == 0
    assert send_state_change_alerts(confirmed, state_path=state_path, sender=sender) == 1
    assert "YELLOW WAIT | QQQ" in messages[0]
    assert "GREEN CONFIRMED | QQQ" in messages[1]


def test_failed_core_delivery_is_not_acknowledged_and_retries(tmp_path: Path) -> None:
    waiting = build_report({"ranked_candidates": [_candidate(
        symbol="IWM",
        score=64,
        state="watch",
        price_action_confirmation={"state": "waiting", "pattern": "level_retest_pending"},
    )]})
    state_path = tmp_path / "retry-state.json"

    event_path = tmp_path / "events.jsonl"
    assert send_state_change_alerts(
        waiting,
        state_path=state_path,
        sender=lambda _message: False,
        event_path=event_path,
    ) == 0
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert "IWM" not in persisted["states"]
    assert waiting["notification_attempts"] == 1
    assert waiting["notification_failures"] == 1
    event = json.loads(event_path.read_text(encoding="utf-8").splitlines()[0])
    assert event["symbol"] == "IWM"
    assert event["discord_delivered"] is False
    assert event["execution_enabled"] is False

    messages: list[str] = []
    assert send_state_change_alerts(
        waiting,
        state_path=state_path,
        sender=lambda message: messages.append(message) or True,
    ) == 1
    assert len(messages) == 1


def test_failed_liquidity_gate_is_red_even_with_price_confirmation() -> None:
    gates = dict(_candidate()["hard_gates"])
    gates["underlying_spread"] = False

    signal = compact_signal(_candidate(hard_gates=gates))

    assert signal["state"] == "INVALID"
    assert signal["color"] == "RED"
    assert signal["decisive_reason"] == "underlying_spread"


def test_notifications_are_state_change_only(tmp_path: Path) -> None:
    report = build_report({"ranked_candidates": [_candidate()]})
    messages: list[str] = []
    sender = lambda message: messages.append(message) or True
    state_path = tmp_path / "state.json"

    assert send_state_change_alerts(report, state_path=state_path, sender=sender) == 1
    assert send_state_change_alerts(report, state_path=state_path, sender=sender) == 0
    assert "GREEN CONFIRMED" in messages[0]
    assert "No order placed" in messages[0]
    assert json.loads(state_path.read_text(encoding="utf-8"))["states"] == {"TEST": "CONFIRMED"}


def test_notification_clearly_labels_score_as_non_probability() -> None:
    message = format_notification(compact_signal(_candidate()))

    assert "not win probability" in message


def test_spy_notification_labels_spx_proxy() -> None:
    message = format_notification(compact_signal(_candidate(symbol="SPY", score=63, grade="B-")))

    assert "proxy for SPX,SPXW" in message


def test_core_confirmation_does_not_repeat_on_every_new_bar(tmp_path: Path) -> None:
    first = build_report({"ranked_candidates": [_candidate(symbol="SPY", score=63, grade="B-")]})
    second_candidate = _candidate(symbol="SPY", score=63, grade="B-")
    second_candidate["price_action_confirmation"]["bar_completed_at"] = "2026-08-20T15:05:00Z"
    second = build_report({"ranked_candidates": [second_candidate]})
    state_path = tmp_path / "state.json"

    assert send_state_change_alerts(first, state_path=state_path, sender=lambda _message: True) == 1
    assert send_state_change_alerts(second, state_path=state_path, sender=lambda _message: True) == 0


def test_core_symbols_are_reserved_before_signal_cap() -> None:
    candidates = [_candidate(symbol=f"T{index:02d}", score=99 - index / 10) for index in range(30)]
    candidates.extend([_candidate(symbol=symbol, score=50, grade="C") for symbol in ("SPY", "QQQ", "IWM")])

    report = build_report({"ranked_candidates": candidates})

    symbols = {row["symbol"] for row in report["signals"]}
    assert len(report["signals"]) == 24
    assert {"SPY", "QQQ", "IWM"}.issubset(symbols)


def test_priority_focus_observation_is_reserved_but_execution_disqualification_remains() -> None:
    crowded = [_candidate(symbol=f"T{index:02d}", score=99 - index / 10) for index in range(30)]
    gates = dict(_candidate()["hard_gates"])
    gates["underlying_spread"] = False
    crowded.append(_candidate(symbol="DELL", score=60, grade="C", hard_gates=gates))

    report = build_report(
        {"ranked_candidates": crowded},
        {"plans": [{
            "symbol": "DELL",
            "decision_contract": {"outcome": "do_not_take", "reasons": ["underlying_spread"]},
        }]},
    )

    dell = next(row for row in report["signals"] if row["symbol"] == "DELL")
    assert dell["always_visible"] is True
    assert dell["observation_visible"] is True
    assert dell["execution_review_eligible"] is False
    assert dell["state"] == "INVALID"
    assert dell["lane"] == "PRIORITY_FOCUS_SHADOW"
    assert dell["execution_enabled"] is False
    assert dell["can_submit_orders"] is False


def test_bar_start_is_normalized_to_decision_time() -> None:
    signal = compact_signal(_candidate())
    assert signal["bar_completed_at"] == "2026-08-20T15:05:00Z"


def test_completed_daily_map_confirmation_enters_governed_candidate_contract() -> None:
    row = {
        "symbol": "SPY",
        "nearest_level": {
            "price": 650.0, "type": "prior_day_high", "source": "last_completed_daily_bar",
            "provenance": "reproducible_public_completed_bar", "distance_points": 0.25,
            "external_unverified": False,
        },
        "confirmation_3m": {
            "state": "CONFIRMED", "direction": "LONG", "reason": "completed_reclaim_up",
            "trigger": 650.0, "invalidation": 649.5, "next_target": 651.0,
            "bar_completed_at": "2026-09-04T14:36:00Z",
        },
    }
    signal = compact_daily_map_signal(row)
    assert signal is not None
    assert signal["state"] == "CONFIRMED"
    assert signal["lane"] == "DAILY_MAP_3M_SHADOW"
    assert signal["trigger"] == 650.0
    assert signal["stop"] == 649.5
    assert signal["target"] == 651.0
    assert signal["execution_enabled"] is False


def test_current_candidates_are_recorded_without_discord_and_are_idempotent(tmp_path: Path) -> None:
    report = build_report({"ranked_candidates": [_candidate()]})
    path = tmp_path / "events.jsonl"

    assert record_current_signals(report, path) == 1
    assert record_current_signals(report, path) == 0
    event = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert event["record_kind"] == "candidate_observation"
    assert event["discord_delivered"] is None
    assert event["state"] == "CONFIRMED"
    assert event["can_submit_orders"] is False
