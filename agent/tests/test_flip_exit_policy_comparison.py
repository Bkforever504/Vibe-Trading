from __future__ import annotations

import json

from scripts import flip_exit_policy_comparison as policy


def test_partial_runner_banks_target_and_keeps_upside() -> None:
    current = policy.simulate_path([0.0, 80.0, 140.0, 110.0], "current_all_out_75")
    partial = policy.simulate_path([0.0, 80.0, 140.0, 110.0], "partial_60_runner_40")

    assert current["return_pct"] == 80.0
    assert partial["return_pct"] == 92.0
    assert partial["reason"] == "runner_ratchet"


def test_partial_runner_can_underperform_captured_target() -> None:
    current = policy.simulate_path([0.0, 80.0, -30.0], "current_all_out_75")
    partial = policy.simulate_path([0.0, 80.0, -30.0], "partial_60_runner_40")

    assert current["return_pct"] == 80.0
    assert partial["return_pct"] == 36.0


def test_report_uses_only_closed_complete_executable_paths(tmp_path) -> None:
    path = tmp_path / "shadow.jsonl"
    base = {
        "schema_version": 3,
        "data_quality": "current_session_lifecycle",
        "execution_mode": "shadow_only",
        "date": "2026-07-15",
        "symbol": "SPY",
        "right": "CALL",
        "option_symbol": "SPY1",
        "lifecycle_id": "life1",
    }
    rows = [
        {**base, "event_type": "shadow_entry", "scanned_at": "2026-07-15T14:30:00Z", "selection_ask": 1.0, "selection_bid": 0.98},
        {**base, "event_type": "shadow_exit", "scanned_at": "2026-07-15T15:00:00Z", "selection_ask": 1.82, "selection_bid": 1.80},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    report = policy.build_report(path)

    assert report["executable_completed_path_count"] == 1
    assert report["policies"]["current_all_out_75"]["avg_return_pct"] == 80.0
    assert report["execution_enabled"] is False
    assert report["promotion_ready"] is False
    assert report["structural_tournament"]["complete_forward_path_count"] == 0


def test_structural_tournament_counts_only_forward_underlying_marks(tmp_path) -> None:
    path = tmp_path / "shadow.jsonl"
    base = {
        "schema_version": 3,
        "data_quality": "current_session_lifecycle",
        "execution_mode": "shadow_only",
        "date": "2026-07-17",
        "symbol": "SPY",
        "right": "CALL",
        "option_symbol": "SPY1",
        "lifecycle_id": "life-forward",
        "underlying_mark_status": "observed_forward",
    }
    rows = [
        {**base, "event_type": "shadow_entry", "scanned_at": "2026-07-17T14:30:00Z",
         "selection_ask": 1.0, "selection_bid": 0.98, "underlying_close": 100,
         "underlying_vwap": 99.5, "underlying_prior_5m_close": 99.8},
        {**base, "event_type": "shadow_mark", "scanned_at": "2026-07-17T14:35:00Z",
         "selection_ask": 1.27, "selection_bid": 1.25, "underlying_close": 101,
         "underlying_vwap": 100, "underlying_prior_5m_close": 100.5},
        {**base, "event_type": "shadow_exit", "scanned_at": "2026-07-17T14:40:00Z",
         "selection_ask": 1.20, "selection_bid": 1.18, "underlying_close": 99.8,
         "underlying_vwap": 100, "underlying_prior_5m_close": 100.7},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    report = policy.build_report(path)

    tournament = report["structural_tournament"]
    assert tournament["complete_forward_path_count"] == 1
    assert tournament["execution_behavior_changed"] is False
    assert set(tournament["policies"]) == {
        "current_ratchet", "structural_5m_close_trail", "structural_vwap_trail"
    }
