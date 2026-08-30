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


def _write_policy_paths(path, *, positive_winners: int, negative_losers: int) -> None:
    rows = []
    path_number = 0
    total = positive_winners + negative_losers
    for index in range(total):
        day = (index % 10) + 1
        path_number += 1
        base = {
            "schema_version": 3,
            "data_quality": "current_session_lifecycle",
            "execution_mode": "shadow_only",
            "date": f"2026-07-{day:02d}",
            "symbol": "SPY",
            "right": "CALL",
            "option_symbol": f"SPY{path_number}",
            "lifecycle_id": f"life-{path_number}",
        }
        if index < positive_winners:
            bids = (1.0, 1.8, 2.4, 2.1)
        else:
            bids = (1.0, 0.8)
        for mark_index, bid in enumerate(bids):
            rows.append({
                **base,
                "event_type": "shadow_exit" if mark_index == len(bids) - 1 else "shadow_mark",
                "scanned_at": f"2026-07-{day:02d}T14:{30 + mark_index:02d}:00Z",
                "selection_ask": 1.0,
                "selection_bid": bid,
            })
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_promotion_blocks_relative_improvement_with_negative_absolute_expectancy(
    tmp_path, monkeypatch
) -> None:
    paths = []
    for index in range(100):
        paths.append({
            "lifecycle_id": f"life-{index}",
            "date": f"2026-07-{(index % 10) + 1:02d}",
            "symbol": "SPY",
            "returns": [0.0, -20.0],
            "observations": [],
        })
    monkeypatch.setattr(policy, "load_executable_paths", lambda _path: paths)

    def losing_but_better(_returns, policy_name):
        value = -10.0 if policy_name == "current_all_out_75" else -5.0
        return {"return_pct": value, "reason": "test", "best_return_pct": 0.0}

    monkeypatch.setattr(policy, "simulate_path", losing_but_better)
    report = policy.build_report(tmp_path / "unused.jsonl")

    assert report["best_challenger_avg_return_delta"] == 5.0
    assert report["promotion_ready"] is False
    assert "challenger_avg_return_not_positive" in report["promotion_blockers"]
    assert "challenger_profit_factor_not_above_one" in report["promotion_blockers"]
    assert report["chronological_holdout"]["qualified"] is False


def test_promotion_accepts_positive_challenger_after_chronological_holdout(tmp_path) -> None:
    path = tmp_path / "shadow.jsonl"
    _write_policy_paths(path, positive_winners=80, negative_losers=20)

    report = policy.build_report(path)

    assert report["best_challenger"] == "ratchet_runner_no_target"
    assert report["policies"]["ratchet_runner_no_target"]["avg_return_pct"] > 0
    assert report["policies"]["ratchet_runner_no_target"]["profit_factor"] > 1
    assert report["chronological_holdout"]["qualified"] is True
    assert report["chronological_holdout"]["candidate_selected_on"] == "training_dates_only"
    assert report["promotion_blockers"] == []
    assert report["promotion_ready"] is True
    assert report["promotion_authorized"] is False


def test_structural_review_blocks_losing_relative_winner(tmp_path, monkeypatch) -> None:
    paths = [{
        "lifecycle_id": f"life-{index}",
        "date": f"2026-07-{(index % 10) + 1:02d}",
        "symbol": "SPY",
        "returns": [0.0, 10.0],
        "observations": [{"underlying_mark_status": "observed_forward"}],
    } for index in range(20)]
    monkeypatch.setattr(policy, "load_executable_paths", lambda _path: paths)
    monkeypatch.setattr(policy, "simulate_structural_exit_tournament", lambda _observations: {
        "current_ratchet": {"hypothetical_exit_pct": -10.0, "exit_trigger": "test"},
        "structural_vwap_trail": {"hypothetical_exit_pct": -5.0, "exit_trigger": "test"},
        "structural_5m_close_trail": {"hypothetical_exit_pct": -8.0, "exit_trigger": "test"},
    })

    tournament = policy.build_report(tmp_path / "unused.jsonl")["structural_tournament"]

    assert tournament["best_path_avg_return_delta_vs_current_ratchet"] == 5.0
    assert tournament["review_ready"] is False
    assert "structural_avg_return_not_positive" in tournament["review_blockers"]
    assert "structural_profit_factor_not_above_one" in tournament["review_blockers"]
