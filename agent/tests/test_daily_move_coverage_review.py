from __future__ import annotations

from scripts.daily_move_coverage_review import build_review


def test_move_review_separates_risk_gate_denominator_and_counts_blockers() -> None:
    latest = {
        "date": "2026-08-25",
        "market_movers": [
            {"symbol": "LIQUID", "percent_change": 10},
            {"symbol": "THIN", "percent_change": 80},
            {"symbol": "UNKNOWN", "percent_change": 20},
            {"symbol": "WAIT", "percent_change": 15},
        ],
    }
    history = [{
        "date": "2026-08-25",
        "as_of_et": "2026-08-25T10:00:00-04:00",
        "all_discovered_symbols": ["LIQUID", "THIN", "UNKNOWN"],
        "ranked_candidates": [
            {
                "symbol": "LIQUID",
                "change_pct": 3,
                "state": "precision_watch",
                "confirmation_stage": "completed_5m_confirmed",
                "blockers": ["strategy_confirmation_and_revalidation_required"],
            },
            {
                "symbol": "THIN",
                "change_pct": 20,
                "state": "filtered",
                "blockers": ["price_below_minimum", "dollar_liquidity_below_minimum", "underlying_spread_too_wide"],
            },
            {
                "symbol": "WAIT",
                "change_pct": 4,
                "state": "precision_watch",
                "confirmation_stage": "awaiting_completed_5m_confirmation",
                "blockers": ["strategy_confirmation_and_revalidation_required"],
            },
        ],
        "actionable_ranked_candidates": [{"symbol": "LIQUID", "ranking_score": 90}],
    }]

    review = build_review(latest, history)
    summary = review["summary"]
    rows = {row["symbol"]: row for row in review["moves"]}

    assert summary["risk_gate_qualified_count"] == 2
    assert summary["risk_gate_disqualified_count"] == 1
    assert summary["risk_gate_unassessed_count"] == 1
    assert summary["actionable_early_recall_of_risk_qualified_pct"] == 50.0
    blockers = {row["blocker"]: row["count"] for row in summary["top_blockers"]}
    assert blockers["price_below_minimum"] == 1
    assert blockers["dollar_liquidity_below_minimum"] == 1
    assert blockers["underlying_spread_too_wide"] == 1
    assert rows["LIQUID"]["first_actionable_rank"] == 1
    assert rows["THIN"]["risk_gate_status"] == "disqualified"
    assert rows["UNKNOWN"]["risk_gate_status"] == "unassessed"
    assert summary["stage_counts"] == {
        "market_moves": 4,
        "discovered": 4,
        "setup_confirmed": 1,
        "execution_qualified": 1,
    }
    assert rows["LIQUID"]["stages"] == {
        "market_move": True,
        "discovered": True,
        "setup_confirmed": True,
        "execution_qualified": True,
    }
    assert rows["THIN"]["outcome_linkage"]["mfe"] is None
    assert rows["THIN"]["outcome_linkage"]["fill_assumed"] is False
    assert rows["WAIT"]["stages"]["setup_confirmed"] is False
    assert rows["WAIT"]["stages"]["execution_qualified"] is False
    assert review["market_coverage"]["no_move_interpretation_allowed_outside_scope"] is True
    assert review["market_coverage"]["no_move_interpretation_permitted_outside_scope"] is False
    assert review["execution_enabled"] is False
    assert review["can_submit_orders"] is False
