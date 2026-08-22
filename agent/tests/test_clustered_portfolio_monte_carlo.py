from datetime import date, timedelta

from scripts.clustered_portfolio_monte_carlo import build_report


def _rows():
    rows = []
    start = date(2026, 1, 2)
    sequence = [-200.0, -150.0, -100.0, 80.0, 90.0, 100.0, 110.0, 120.0]
    for index in range(40):
        candidate_id = f"candidate-{index}"
        day = start + timedelta(days=index)
        rows.extend([
            {
                "type": "candidate",
                "candidate_id": candidate_id,
                "strategy": "put_spread" if index % 2 else "iron_condor",
            },
            {
                "type": "outcome",
                "candidate_id": candidate_id,
                "resolved_at": f"{day.isoformat()}T20:00:00Z",
                "pnl_before_fees": sequence[index % len(sequence)],
            },
        ])
    return rows


def test_clustered_monte_carlo_is_deterministic_and_read_only():
    first = build_report(_rows(), paths=500, horizon=30, seed=7)
    second = build_report(_rows(), paths=500, horizon=30, seed=7)

    assert first == second
    assert first["resolved_outcome_count"] == 40
    assert first["active_resolution_day_count"] == 40
    assert first["evidence_status"] == "sufficient_for_risk_review"
    assert first["clustered_day_bootstrap"]["block_length_days"] == 6
    assert first["clustered_day_bootstrap"]["p99_max_drawdown_dollars"] >= 0
    assert first["promotion_authority"] == "blocked"
    assert first["can_submit_orders"] is False
