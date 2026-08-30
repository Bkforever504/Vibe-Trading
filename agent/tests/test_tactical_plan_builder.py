from __future__ import annotations

from datetime import datetime, timezone

from scripts.tactical_plan_builder import build_tactical_plan


NOW = datetime(2026, 8, 25, 13, 43, tzinfo=timezone.utc)


def _candidate(direction: str, entry: float, stop: float, target: float) -> dict:
    return {
        "symbol": "SPY",
        "direction": direction,
        "setup": "range_break_retest",
        "actionability": "wait",
        "grade": "A-",
        "decision_score": 86.0,
        "entry": entry,
        "stop": stop,
        "target": target,
        "blockers": [],
        "source": "live_opportunities",
        "source_labels": ["alpaca_iex_websocket", "completed_5m_bars"],
        "trade_plan": {
            "entry_trigger": entry,
            "invalidation": stop,
            "targets": [{"name": "target_1", "price": target}],
            "entry_timing": {
                "status": "awaiting_completed_bar",
                "confirmation_timeframe": "5m",
                "earliest_review_at": "2026-08-25T13:45:00Z",
                "eta_minutes": 2.0,
                "eta_definition": "Earliest legitimate recheck, not a predicted fill time or guarantee.",
                "entry_trigger": entry,
                "entry_zone": {"status": "exact_source_trigger", "low": entry, "high": entry},
                "invalidation": stop,
                "target": target,
                "confirmation_required": "Wait for a completed 5m close, then a hold or retest.",
                "why": ["completed-bar structure and location align"],
                "cancel_if": [],
                "execution_enabled": False,
                "can_submit_orders": False,
            },
        },
        "evidence": {"trade_levels": {"confirmation_trigger": entry}},
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def test_two_sided_plan_exposes_exact_levels_eta_and_no_trade_zone() -> None:
    report = build_tactical_plan(
        [_candidate("bullish", 769.0, 768.0, 772.0), _candidate("bearish", 768.0, 769.0, 765.0)],
        primary_symbol="SPY",
        market_state={"classification": "gap_up", "source_labels": ["market_force"]},
        now=NOW,
    )

    assert report["status"] == "WAIT_FOR_CONFIRMATION"
    assert report["bull_case"]["trigger"] == 769.0
    assert report["bear_case"]["trigger"] == 768.0
    assert report["bull_case"]["entry_timing"]["eta_minutes"] == 2.0
    assert report["no_trade_zone"] == {
        "status": "available",
        "low": 768.0,
        "high": 769.0,
        "instruction": "Stand aside while price remains between the bearish and bullish triggers.",
    }
    assert report["cross_checks"]["level_consistency"] == "pass"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_level_conflict_fails_closed_instead_of_showing_actionable_plan() -> None:
    bullish = _candidate("bullish", 769.0, 768.0, 772.0)
    bullish["evidence"]["trade_levels"]["confirmation_trigger"] = 779.0

    report = build_tactical_plan([bullish], primary_symbol="SPY", now=NOW)

    assert report["status"] == "INVALID_SOURCE_CONFLICT"
    assert report["bull_case"]["state"] == "INVALID"
    assert report["cross_checks"]["level_consistency"] == "fail"
    assert report["cross_checks"]["conflicts"][0]["field"] == "bull_case.trigger"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_invalid_stop_and_target_geometry_force_stand_aside() -> None:
    candidate = _candidate("bullish", 101.0, 100.0, 102.0)
    candidate["stop"] = 101.5
    candidate["target"] = 100.5
    candidate["trade_plan"]["invalidation"] = 101.5
    candidate["trade_plan"]["targets"] = [{"name": "target_1", "price": 100.5}]

    report = build_tactical_plan([candidate], primary_symbol="SPY", now=NOW)

    assert report["status"] == "INVALID_SOURCE_CONFLICT"
    assert report["decision"] == "STAND_ASIDE"
    reasons = {row["reason"] for row in report["cross_checks"]["conflicts"]}
    assert "bullish_stop_must_be_below_trigger" in reasons
    assert "bullish_target_must_be_above_trigger" in reasons
