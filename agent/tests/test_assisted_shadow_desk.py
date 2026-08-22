from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.assisted_shadow_edge_report import build_report
from strategies.assisted_shadow_desk import (
    AssistedShadowError,
    create_packet,
    load_states,
    record_decision,
    resolve_outcome,
)


NOW = datetime(2026, 8, 17, 14, 0, tzinfo=timezone.utc)


def candidate(*, side: str = "buy", observed_at: str = "2026-08-17T14:00:00Z") -> dict:
    if side == "buy":
        entry, stop, target = 6500.0, 6490.0, 6520.0
    else:
        entry, stop, target = 6500.0, 6510.0, 6480.0
    return {
        "symbol": "MES",
        "strategy": "confirmed_pullback",
        "side": side,
        "entry": entry,
        "stop": stop,
        "target": target,
        "quantity": 1,
        "point_value": 5.0,
        "estimated_round_trip_cost": 2.48,
        "observed_at": observed_at,
        "context": {"trend": "aligned", "structure": "retest"},
    }


def test_packet_is_frozen_non_executable_and_decision_binds_digest(tmp_path: Path) -> None:
    journal = tmp_path / "desk.jsonl"
    packet = create_packet(candidate(), journal=journal, now=NOW)
    assert packet["execution_enabled"] is False
    assert packet["can_submit_orders"] is False
    assert packet["candidate"]["quantity"] == 1
    event = record_decision(
        packet["packet_id"],
        "approve",
        journal=journal,
        expected_candidate_digest=packet["candidate_digest"],
        now=NOW + timedelta(seconds=30),
    )
    assert event["execution_authority"] == "none_shadow_observation_only"
    assert load_states(journal)[packet["packet_id"]].decision is not None


def test_late_or_duplicate_decision_fails_closed(tmp_path: Path) -> None:
    journal = tmp_path / "desk.jsonl"
    packet = create_packet(candidate(), journal=journal, now=NOW, decision_window_seconds=30)
    with pytest.raises(AssistedShadowError, match="expired"):
        record_decision(packet["packet_id"], "approve", journal=journal, now=NOW + timedelta(seconds=31))
    record_decision(packet["packet_id"], "skip", journal=journal, now=NOW + timedelta(seconds=10))
    with pytest.raises(AssistedShadowError, match="already recorded"):
        record_decision(packet["packet_id"], "approve", journal=journal, now=NOW + timedelta(seconds=11))


def test_approved_and_skipped_outcomes_are_both_measured_after_costs(tmp_path: Path) -> None:
    journal = tmp_path / "desk.jsonl"
    approved = create_packet(candidate(observed_at="2026-08-17T14:00:00Z"), journal=journal, now=NOW)
    skipped = create_packet(
        candidate(side="sell", observed_at="2026-08-18T14:00:00Z"),
        journal=journal,
        now=NOW + timedelta(days=1),
    )
    record_decision(approved["packet_id"], "approve", journal=journal, now=NOW + timedelta(seconds=5))
    record_decision(skipped["packet_id"], "skip", journal=journal, now=NOW + timedelta(days=1, seconds=5))
    approved_outcome = resolve_outcome(
        approved["packet_id"], exit_price=6505.0, journal=journal, resolved_at=NOW + timedelta(minutes=5)
    )
    resolve_outcome(
        skipped["packet_id"], exit_price=6505.0, journal=journal, resolved_at=NOW + timedelta(days=1, minutes=5)
    )
    assert approved_outcome["net_pnl"] == 22.52
    report = build_report(journal)
    assert report["approved"]["expectancy"] == 22.52
    assert report["skipped"]["expectancy"] == -27.48
    assert report["approve_minus_skip_expectancy"] == 50.0
    assert report["review_eligible"] is False


def test_tampered_journal_is_rejected(tmp_path: Path) -> None:
    journal = tmp_path / "desk.jsonl"
    create_packet(candidate(), journal=journal, now=NOW)
    event = json.loads(journal.read_text(encoding="utf-8"))
    event["packet"]["candidate"]["target"] = 9999.0
    journal.write_text(json.dumps(event) + "\n", encoding="utf-8")
    with pytest.raises(AssistedShadowError, match="hash mismatch"):
        load_states(journal)
