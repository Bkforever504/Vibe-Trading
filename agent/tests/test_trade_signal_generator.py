from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from scripts.trade_signal_generator import build_report, load_signal_for_symbol, send_signal_alerts, validate_signal_for_consumer


NOW = datetime(2026, 8, 19, 14, 50, tzinfo=timezone.utc)


def _event_report(*, entry_age_minutes: int = 5, outcome: str = "open") -> dict:
    entry_time = NOW - timedelta(minutes=entry_age_minutes)
    return {
        "date": "2026-08-19",
        "generated_at": (NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "candidates": [
            {
                "symbol": "MRNA",
                "eligible": True,
                "direction": "bull",
                "entry_time": entry_time.isoformat(),
                "entry": 125.0,
                "stop": 119.0,
                "target": 137.0,
                "formula_version": "event_gap_or15_break_vwap_same_slot_volume_v2",
                "gap_pct": 90.0,
                "volume_ratio": 2.4,
                "directional_relative_pct": 8.0,
                "vwap_extension_pct": 2.0,
                "post_entry_outcome": {"status": outcome},
            }
        ],
    }


def _event_report_with_discovery(*, source_date: str = "2026-08-19") -> dict:
    report = _event_report()
    report["candidates"][0]["discovery_provenance"] = {
        "symbol": "MRNA",
        "as_of": source_date,
        "sources": ["social_trending", "deep_liquid_universe"],
        "authority": "discovery_only_no_directional_or_execution_authority",
    }
    return report


def _radar_report() -> dict:
    return {
        "date": "2026-08-19",
        "observations": [{"symbol": "MRNA", "lane": "event_gap", "state": "exceptional_event_watch", "priority": "high"}],
    }


def test_current_completed_sequence_creates_paper_consumer_signal() -> None:
    report = build_report(event_report=_event_report(), radar_report=_radar_report(), now=NOW)
    signal = report["ready_signals"][0]
    assert signal["symbol"] == "MRNA"
    assert signal["entry"] == 125.0
    assert signal["stop"] == 119.0
    assert signal["targets"][0]["price"] == 137.0
    assert signal["reward_risk"] == 2.0
    assert signal["paper_consumable"] is True
    assert signal["execution_enabled"] is False
    assert signal["can_submit_orders"] is False


def test_same_session_social_or_deep_discovery_can_feed_mechanical_signal() -> None:
    report = build_report(
        event_report=_event_report_with_discovery(),
        radar_report={},
        now=NOW,
    )

    signal = report["ready_signals"][0]
    assert signal["source_health"]["discovery_sources"] == [
        "deep_liquid_universe",
        "social_trending",
    ]
    assert signal["source_health"]["discovery_is_nomination_only"] is True
    assert signal["execution_enabled"] is False
    assert signal["can_submit_orders"] is False


def test_stale_or_unknown_discovery_cannot_feed_signal() -> None:
    stale = build_report(
        event_report=_event_report_with_discovery(source_date="2026-08-18"),
        radar_report={},
        now=NOW,
    )
    unknown_report = _event_report_with_discovery()
    unknown_report["candidates"][0]["discovery_provenance"]["sources"] = ["unverified_chat_tip"]
    unknown = build_report(event_report=unknown_report, radar_report={}, now=NOW)

    assert "same_session_approved_discovery" in stale["blocked_signals"][0]["blockers"]
    assert "same_session_approved_discovery" in unknown["blocked_signals"][0]["blockers"]


def test_stale_trigger_is_blocked() -> None:
    report = build_report(event_report=_event_report(entry_age_minutes=20), radar_report=_radar_report(), now=NOW)
    assert report["ready_signals"] == []
    assert "trigger_current" in report["blocked_signals"][0]["blockers"]


def test_resolved_candidate_cannot_be_consumed() -> None:
    report = build_report(event_report=_event_report(outcome="target"), radar_report=_radar_report(), now=NOW)
    assert report["ready_signals"] == []
    assert "trade_not_already_resolved" in report["blocked_signals"][0]["blockers"]


def test_consumer_revalidates_artifact_age(tmp_path) -> None:
    report = build_report(event_report=_event_report(), radar_report=_radar_report(), now=NOW)
    path = tmp_path / "signals.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    current = load_signal_for_symbol("MRNA", path=path, now=NOW + timedelta(minutes=2))
    assert current["consumer_valid"] is True
    valid, blockers = validate_signal_for_consumer(current, now=NOW + timedelta(minutes=30))
    assert valid is False
    assert "signal_artifact_stale" in blockers
    assert "signal_trigger_stale" in blockers


def test_confirmed_signal_alert_is_deduplicated(tmp_path) -> None:
    report = build_report(event_report=_event_report(), radar_report=_radar_report(), now=NOW)
    messages: list[str] = []
    sender = lambda message: messages.append(message) is None
    state = tmp_path / "alerts.json"
    assert send_signal_alerts(report, state_path=state, sender=sender) == 1
    assert send_signal_alerts(report, state_path=state, sender=sender) == 0
    assert "entry=`125.0`" in messages[0]


def test_bottom_reversal_plan_is_visible_but_cannot_bypass_trigger_revalidation() -> None:
    bottom_report = {
        "candidates": [
            {
                "symbol": "PFE",
                "stage": "armed_next_session",
                "next_session_plan": {"status": "armed", "entry_trigger": 25.5, "invalidation": 24.0, "target_2r": 28.5},
            }
        ]
    }
    report = build_report(
        event_report=_event_report(),
        radar_report=_radar_report(),
        bottom_report=bottom_report,
        now=NOW,
    )
    row = next(item for item in report["watchlist"] if item["symbol"] == "PFE")
    assert row["lane"] == "bottom_reversal"
    assert row["priority"] == "high"
    assert row["paper_consumable"] is False
    assert report["execution_enabled"] is False
