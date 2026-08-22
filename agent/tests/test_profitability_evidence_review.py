from scripts.profitability_evidence_review import build_review


def test_review_fails_closed_with_no_evidence():
    report = build_review([], [])

    assert report["summary"]["blockers"] == [
        "fewer_than_30_resolved_filter_counterfactuals",
        "fewer_than_30_resolved_execution_observations",
        "clustered_portfolio_history_insufficient",
    ]
    assert report["promotion_authority"] == "blocked"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
