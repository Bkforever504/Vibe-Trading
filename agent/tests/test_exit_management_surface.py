from __future__ import annotations

from scripts.live_trading_cockpit import _exit_management_surface


def sources(*names: str) -> dict[str, dict[str, object]]:
    return {
        name: {
            "name": name,
            "filename": f"{name}.json",
            "available": True,
            "freshness": "live",
            "age_seconds": 10.0,
        }
        for name in names
    }


def test_relative_exit_improvement_cannot_mask_negative_expectancy() -> None:
    result = _exit_management_surface(
        {
            "flip_exit_quality": {
                "closed_trade_count": 15,
                "complete_count": 4,
                "insufficient_data_count": 11,
            },
            "flip_exit_policy": {
                "best_challenger": "runner",
                "best_challenger_avg_return_delta": 0.34,
                "promotion_ready": True,
                "policies": {"runner": {"avg_return_pct": -6.41, "profit_factor": 0.691}},
            },
        },
        sources("flip_exit_quality", "flip_exit_policy"),
        {
            "open_trades": {"flip": {"open": 0}},
            "portfolio_concentration": {"position_count": 0},
            "outcome": {"realized_pnl": 0.0},
        },
    )

    assert result["status"] == "flat"
    assert result["trail_state"] == "FLAT"
    assert result["telemetry"]["coverage_pct"] == 26.67
    assert result["basket_risk"]["aggregate_open_risk"] == 0.0
    assert result["outcome_rates"]["economic_basket_win_rate"] is None
    assert result["policy"]["raw_promotion_ready"] is True
    assert result["policy"]["production_eligible"] is False
    assert "challenger_average_return_not_positive" in result["policy"]["blockers"]
    assert "challenger_profit_factor_not_above_one" in result["policy"]["blockers"]


def test_exit_policy_requires_positive_absolute_economics_and_holdout() -> None:
    result = _exit_management_surface(
        {
            "flip_exit_quality": {"closed_trade_count": 100, "complete_count": 90},
            "flip_exit_policy": {
                "best_challenger": "runner",
                "promotion_ready": True,
                "promotion_authorized": True,
                "chronological_holdout": {"qualified": True},
                "policies": {"runner": {"avg_return_pct": 1.2, "profit_factor": 1.08}},
            },
        },
        sources("flip_exit_quality", "flip_exit_policy"),
        {"open_trades": {}, "portfolio_concentration": {"position_count": 0}},
    )

    assert result["policy"]["absolute_economics_positive"] is True
    assert result["policy"]["chronological_holdout_qualified"] is True
    assert result["policy"]["evidence_qualified_for_human_review"] is True
    assert result["policy"]["production_eligible"] is True


def test_open_position_without_normalized_trail_feed_fails_closed() -> None:
    result = _exit_management_surface(
        {"flip_exit_quality": {}, "flip_exit_policy": {}},
        sources("flip_exit_quality", "flip_exit_policy"),
        {
            "open_trades": {"flip": {"open": 1}},
            "portfolio_concentration": {"position_count": 1},
            "outcome": {"realized_pnl": 25.0},
        },
    )

    assert result["status"] == "active_unqualified"
    assert result["trail_state"] == "TELEMETRY_UNAVAILABLE"
    assert result["economics"]["unrealized_pnl"] is None
    assert result["economics"]["economic_pnl"] is None
    assert result["basket_risk"]["aggregate_open_risk"] is None
    assert result["trigger_price"] is None
    assert result["eta_status"] == "blocked_unqualified_trail_telemetry"
    assert result["guardrails"]["add_to_losers_allowed"] is False
    assert result["execution_enabled"] is False
