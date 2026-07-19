from research.mes_candidate_stress import monte_carlo


def test_monte_carlo_is_deterministic_and_reports_drawdown() -> None:
    first = monte_carlo([100.0, -50.0, 25.0], samples=100, seed=7)
    second = monte_carlo([100.0, -50.0, 25.0], samples=100, seed=7)
    assert first == second
    assert first["trades_per_path"] == 3
    assert "probability_30pct_drawdown" in first
