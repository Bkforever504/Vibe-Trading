from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.profitability_control_plane import (
    ControlConfig,
    OpportunityCandidate,
    regime_weighted_loss_buffer,
    run_opportunity_exchange,
)


def _candidate(**updates) -> OpportunityCandidate:
    values = {
        "candidate_id": "alpha-1",
        "lane": "tested_lane",
        "risk_cluster": "equity_beta",
        "expected_pnl": 42.0,
        "lower_confidence_pnl": 18.0,
        "estimated_round_trip_cost": 3.0,
        "max_loss": 50.0,
        "current_signal": True,
        "lifecycle_state": "paper_approved",
        "paper_review_eligible": True,
        "data_status": "current",
        "regime": "normal",
        "regime_compatible": True,
        "forward_observations": 40,
    }
    values.update(updates)
    return OpportunityCandidate(**values)


def test_positive_after_cost_lower_bound_can_beat_cash_without_execution_authority() -> None:
    report = run_opportunity_exchange([_candidate()])

    assert report["capital_decision"]["action"] == "paper_candidates_available"
    assert report["capital_decision"]["selected"][0]["lane"] == "tested_lane"
    assert report["can_submit_orders"] is False
    assert report["orders_submitted"] == 0


def test_cash_wins_when_lower_bound_is_not_positive_after_costs() -> None:
    report = run_opportunity_exchange([_candidate(lower_confidence_pnl=2.0, estimated_round_trip_cost=3.0)])

    assert report["capital_decision"]["action"] == "hold_cash_collect_counterfactuals"
    assert "after_cost_lower_bound_not_positive" in report["candidates"][0]["blockers"]


def test_lifecycle_data_and_forward_evidence_are_hard_requirements() -> None:
    report = run_opportunity_exchange([
        _candidate(lifecycle_state="research_only", paper_review_eligible=False, data_status="stale", forward_observations=4)
    ])
    blockers = report["candidates"][0]["blockers"]

    assert "lifecycle_research_only" in blockers
    assert "paper_review_not_eligible" in blockers
    assert "data_stale" in blockers
    assert "insufficient_forward_observations" in blockers


def test_regime_weighted_loss_buffer_penalizes_recent_same_regime_misses() -> None:
    residuals = [
        {"adverse_error": 1.0, "regime": "normal"},
        {"adverse_error": 2.0, "regime": "high_vol"},
        {"adverse_error": 9.0, "regime": "normal"},
    ]

    assert regime_weighted_loss_buffer(residuals, current_regime="normal", quantile=0.8) == 9.0


def test_only_one_candidate_per_correlated_risk_cluster_is_selected() -> None:
    report = run_opportunity_exchange([
        _candidate(candidate_id="a", lane="lane_a", lower_confidence_pnl=20.0),
        _candidate(candidate_id="b", lane="lane_b", lower_confidence_pnl=15.0),
    ])

    assert [row["candidate_id"] for row in report["capital_decision"]["selected"]] == ["a"]


def test_risk_budget_can_force_cash_even_when_statistical_edge_is_positive() -> None:
    report = run_opportunity_exchange(
        [_candidate(max_loss=500.0)],
        config=ControlConfig(account_equity=10_000.0, max_candidate_risk_fraction=0.0025),
    )

    assert report["capital_decision"]["selected"] == []
    assert "risk_budget_cannot_fund_one_unit" in report["candidates"][0]["blockers"]

