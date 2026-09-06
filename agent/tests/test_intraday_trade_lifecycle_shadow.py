from scripts.intraday_trade_lifecycle_shadow import lifecycle_plan


def test_confirmed_plan_has_fixed_exit_arms_but_no_execution_authority() -> None:
    plan = lifecycle_plan({
        "symbol": "AAPL", "direction": "bullish", "entry": 100, "invalidation": 99, "target": 102,
        "lane_rank": 2, "grade": "B+", "setup": "sweep_and_reclaim",
        "price_action_confirmation": {"state": "bullish_confirmed", "bar_completed_at": "2026-09-01T14:00:00Z"},
    })
    assert plan is not None
    assert plan["one_r_reference"] == 101.0
    assert plan["lane_rank"] == 2
    assert plan["decision_contract"]["outcome"] == "do_not_take"
    assert "primary_catalyst_not_verified" in plan["decision_contract"]["reasons"]
    assert plan["time_stop_at"] == "2026-09-01T14:30:00Z"
    assert plan["exit_policy_arms"][1]["id"] == "experiment_break_even_30m_after_1r"
    assert plan["can_submit_orders"] is False
