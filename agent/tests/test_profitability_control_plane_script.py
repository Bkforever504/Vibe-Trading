from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.profitability_control_plane import candidates_from_reports
from strategies.profitability_control_plane import run_opportunity_exchange


def test_adapter_preserves_failed_review_as_hard_lifecycle_block() -> None:
    opportunity = {
        "evidence": {
            "candidate_lane": {
                "mean_pnl": 100,
                "bootstrap": {"ci90": [50, 150]},
            }
        },
        "strategy_lifecycle": {
            "lanes": {
                "candidate_lane": {
                    "state": "research_only",
                    "paper_review_eligible": False,
                    "observations": 200,
                }
            }
        },
        "regime_allocator": {
            "candidates": [
                {
                    "candidate_id": "candidate-1",
                    "lane": "candidate_lane",
                    "eligible": True,
                    "regime_context": {"vix_regime": "normal"},
                }
            ]
        },
    }

    report = run_opportunity_exchange(candidates_from_reports(opportunity, {}))

    assert report["capital_decision"]["selected"] == []
    assert "lifecycle_research_only" in report["candidates"][0]["blockers"]
    assert report["can_submit_orders"] is False


def test_router_research_priority_does_not_become_capital_authority() -> None:
    router = {
        "lanes": [
            {
                "lane": "momentum_edge_ensemble",
                "status": "forward_shadow_priority",
                "evidence": {"gate_passed": True},
            }
        ]
    }

    report = run_opportunity_exchange(candidates_from_reports({}, router))

    assert report["capital_decision"]["action"] == "hold_cash_collect_counterfactuals"
    assert "lower_confidence_bound_missing" in report["candidates"][0]["blockers"]

