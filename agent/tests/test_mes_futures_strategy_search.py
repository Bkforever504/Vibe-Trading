from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from research.mes_futures_strategy_search import (
    Candidate,
    _candidate_grid,
    _chronological_partitions,
    _configs,
    _metrics,
    _take_unique_finalists,
    _trim_candles_from_start,
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
    assert {candidate.range_minutes for candidate in candidates} == {5, 15, 30, 45, 60}
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


def test_trim_candles_from_start_is_inclusive_and_normalized() -> None:
    candles = [
        SimpleNamespace(timestamp=datetime(2023, 12, 29, 9, 30)),
        SimpleNamespace(timestamp=datetime(2024, 1, 1, 9, 30)),
        SimpleNamespace(timestamp=datetime(2024, 1, 2, 9, 30)),
    ]
    trimmed, normalized = _trim_candles_from_start(candles, "2024-01-01")
    assert normalized == "2024-01-01"
    assert [candle.timestamp.date().isoformat() for candle in trimmed] == ["2024-01-01", "2024-01-02"]


def test_trim_candles_from_start_rejects_non_iso_dates() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _trim_candles_from_start([], "01/01/2024")


def test_finalists_deduplicate_exact_development_trade_paths() -> None:
    first = Candidate("orb", 1.0, 2.0, 40, 4, "full_target_stop", "live_vwap", 5)
    duplicate = Candidate("orb", 1.0, 2.0, 40, 4, "full_target_stop", "ema20", 5)
    distinct = Candidate("pullback", 1.0, 2.0, 40, 4, "full_target_stop", "none", 5)
    same_path = ((("2026-01-02", "entry", "exit", "buy", 1.0, 2.0, 1.0, "target"),),)
    other_path = ((("2026-01-03", "entry", "exit", "sell", 2.0, 1.0, 1.0, "target"),),)
    ranked = [
        (3.0, first, [], same_path),
        (2.0, duplicate, [], same_path),
        (1.0, distinct, [], other_path),
    ]
    selected, skipped = _take_unique_finalists(ranked, 2)
    assert [row[1] for row in selected] == [first, distinct]
    assert skipped == 1
