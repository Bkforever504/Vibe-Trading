from scripts.filter_counterfactual_attribution import build_report


def test_filter_attribution_separates_blocked_losses_from_allowed_winners():
    rows = []
    for index in range(40):
        candidate_id = f"candidate-{index}"
        blockers = ["risk_veto"] if index < 20 else []
        rows.extend([
            {
                "type": "candidate",
                "candidate_id": candidate_id,
                "strategy": "put_spread",
                "underlying": "SPY",
                "shadow_consensus": {"blockers": blockers},
            },
            {
                "type": "outcome",
                "candidate_id": candidate_id,
                "pnl_before_fees": -25.0 if index < 20 else 15.0,
            },
        ])

    report = build_report(rows)

    result = next(row for row in report["filters"] if row["filter"] == "shadow:risk_veto")
    assert result["verdict"] == "promising_veto"
    assert result["blocked"]["average_pnl_dollars"] == -25.0
    assert result["allowed"]["average_pnl_dollars"] == 15.0
    assert result["counterfactual_loss_avoided_dollars"] == 500.0
    assert result["loss_dollars_captured_rate"] == 1.0
    assert report["promotion_authority"] == "blocked"
    assert report["can_submit_orders"] is False


def test_setup_gate_false_is_treated_as_active_veto():
    twin = [
        {"type": "candidate", "candidate_id": "a", "shadow_consensus": {}},
        {"type": "outcome", "candidate_id": "a", "pnl_before_fees": -5.0},
        {"type": "candidate", "candidate_id": "b", "shadow_consensus": {}},
        {"type": "outcome", "candidate_id": "b", "pnl_before_fees": 4.0},
    ]
    setups = [
        {
            "type": "matched_setup",
            "gate_states": {"contango": False},
            "expressions": [{"candidate_id": "a"}],
        },
        {
            "type": "matched_setup",
            "gate_states": {"contango": True},
            "expressions": [{"candidate_id": "b"}],
        },
    ]

    report = build_report(twin, setups)
    result = next(row for row in report["filters"] if row["filter"] == "setup_gate:contango")
    assert result["blocked"]["count"] == 1
    assert result["allowed"]["count"] == 1
    assert result["verdict"] == "insufficient_cohort"
