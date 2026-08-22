from __future__ import annotations

import json
from pathlib import Path

from scripts.simple_price_action_alerts import (
    build_report,
    compact_signal,
    format_notification,
    send_state_change_alerts,
)


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
