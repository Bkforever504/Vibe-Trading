from __future__ import annotations

from strategies.topstep_combine_simulator import CombineRules, bootstrap_combine, simulate_combine


def test_two_even_winning_days_pass_consistency_target() -> None:
    result = simulate_combine([1500.0, 1500.0])

    assert result.status == "passed"
    assert result.sessions == 2
    assert result.ending_profit == 3000.0
    assert result.required_profit == 3000.0


def test_large_best_day_increases_required_profit() -> None:
    result = simulate_combine([2000.0, 1000.0])

    assert result.status == "incomplete"
    assert result.ending_profit == 3000.0
    assert result.required_profit == 4000.0


def test_maximum_loss_limit_trails_at_eod_and_never_moves_down() -> None:
    rules = CombineRules(max_sessions=3)
    result = simulate_combine([1000.0, -1500.0, 0.0], rules)

    assert result.status == "incomplete"
    assert result.maximum_loss_limit == 49000.0
    assert result.ending_balance == 49500.0


def test_hitting_maximum_loss_limit_fails() -> None:
    result = simulate_combine([-1000.0, -1000.0])

    assert result.status == "failed"
    assert result.failure_reason == "maximum_loss_limit"
    assert result.sessions == 2


def test_bootstrap_is_deterministic_and_reports_all_outcomes() -> None:
    rules = CombineRules(profit_target=100.0, maximum_loss=100.0, max_sessions=10)
    first = bootstrap_combine([50.0, -25.0, 0.0], contracts=1, rules=rules, simulations=100, block_size=2)
    second = bootstrap_combine([50.0, -25.0, 0.0], contracts=1, rules=rules, simulations=100, block_size=2)

    assert first == second
    assert round(first["pass_rate"] + first["mll_failure_rate"] + first["incomplete_rate"], 4) == 1.0
