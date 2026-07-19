from __future__ import annotations

from research.mes_futures_strategy_search import (
    Candidate,
    _candidate_grid,
    _chronological_partitions,
    _configs,
    _metrics,
)
from strategies.topstep_replay_backtester import BacktestResult


def test_orb_candidate_uses_fixed_stop_and_mes_costs() -> None:
    candidate = Candidate("orb", 3.0, 2.0, 40, 4, "full_target_stop", "none", 15)
    orb, bt = _configs(candidate)
    assert orb.range_minutes == 15
    assert orb.min_breakout_points == 3.0
    assert bt.fixed_stop_ticks == 40
    assert bt.commission_per_rt == 4.0


def test_pullback_candidate_uses_fixed_atm_stop() -> None:
    candidate = Candidate("pullback", 3.0, 2.0, 40, 8, "full_target_stop", "gap")
    _, bt = _configs(candidate)
    assert bt.fixed_stop_ticks == 40
    assert bt.pullback_stop_ticks == 40


def test_executable_grid_excludes_partial_exits_and_caps_risk() -> None:
    candidates = _candidate_grid(executable_only=True, max_stop_ticks=40)
    assert candidates
    assert {candidate.exit_model for candidate in candidates} == {"full_target_stop"}
    assert {candidate.range_minutes for candidate in candidates} == {5, 15, 30}
    assert max(candidate.stop_ticks for candidate in candidates) == 40


def test_double_cost_stress_is_stricter() -> None:
    candidate = Candidate("pullback", 3.0, 2.0, 40, 16, "full_target_stop", "none")
    _, base = _configs(candidate)
    _, stress = _configs(candidate, doubled_costs=True)
    assert stress.commission_per_rt == base.commission_per_rt * 2
    assert stress.slippage_ticks == base.slippage_ticks * 2


def test_metrics_reports_daily_average() -> None:
    result = BacktestResult([], 50.0, 0.5, 1.2, 5.0, 20.0, [], 5, 5)
    metrics = _metrics(result, market_days=10)
    assert metrics["daily_average"] == 5.0


def test_chronological_partitions_preserve_untouched_final_window() -> None:
    dates = [f"day-{index:03d}" for index in range(200)]
    development, selection, final_test = _chronological_partitions(dates)
    assert len(development) == 140
    assert len(selection) == 30
    assert len(final_test) == 30
    assert development + selection + final_test == dates
