from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from research.mes_opening_gap_fade_lab import (
    GapFadeConfig,
    GapSession,
    _candidate_rank,
    _historical_stability_pass,
    parameter_grid,
    simulate_session,
)


def _bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    start = datetime(2026, 8, 10, 9, 30)
    return pd.DataFrame([
        {
            "dt": start + timedelta(minutes=index),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
        }
        for index, (open_, high, low, close) in enumerate(rows)
    ])


def test_parameter_grid_is_frozen_to_twelve_attempts() -> None:
    assert len(parameter_grid()) == 12


def test_gap_up_rejection_enters_next_bar_and_targets_prior_close() -> None:
    rows = [
        (101.0, 101.2, 100.7, 100.8),
        (100.8, 100.9, 100.5, 100.6),
        (100.6, 100.7, 100.3, 100.4),
        (100.4, 100.5, 100.1, 100.2),
        (100.2, 100.3, 99.9, 100.0),
        (100.0, 100.1, 98.8, 99.0),
    ]
    session = GapSession("2026-08-10", _bars(rows), prior_close=99.0, gap_pct=2.0)
    config = GapFadeConfig(0.35, 5, 0.25, min_reward_risk=0.1)
    trade = simulate_session(session, config)
    assert trade is not None
    assert trade.side == "sell"
    assert trade.entry_time.endswith("09:35:00")
    assert trade.exit_reason == "target"
    assert trade.raw_points == 1.0


def test_stop_has_priority_when_stop_and_target_touch_same_bar() -> None:
    rows = [
        (101.0, 101.2, 100.7, 100.8),
        (100.8, 100.9, 100.5, 100.6),
        (100.6, 100.7, 100.3, 100.4),
        (100.4, 100.5, 100.1, 100.2),
        (100.2, 100.3, 99.9, 100.0),
        (100.0, 102.0, 98.0, 99.0),
    ]
    session = GapSession("2026-08-10", _bars(rows), prior_close=99.0, gap_pct=2.0)
    config = GapFadeConfig(0.35, 5, 0.25, min_reward_risk=0.1)
    trade = simulate_session(session, config)
    assert trade is not None
    assert trade.exit_reason == "stop"
    assert trade.raw_points < 0


def test_gap_without_required_rejection_is_blocked() -> None:
    rows = [(101.0, 101.2, 100.9, 101.1)] * 6
    session = GapSession("2026-08-10", _bars(rows), prior_close=99.0, gap_pct=2.0)
    assert simulate_session(session, GapFadeConfig(0.35, 5, 0.25)) is None


def test_historical_pass_requires_every_year_and_all_stresses() -> None:
    good = {"trades": 20, "expectancy": 1.0, "profit_factor": 1.2, "p_value": 0.001}
    row = {
        "annual": {year: dict(good) for year in ("2024", "2025", "2026")},
        "annual_2x_cost": {year: dict(good) for year in ("2024", "2025", "2026")},
        "aggregate_2x_cost": dict(good),
        "aggregate_2x_cost_one_bar_delay": dict(good),
        "aggregate_2x_cost_without_top_1pct": dict(good),
    }
    assert _historical_stability_pass(row) is True
    row["annual_2x_cost"]["2025"]["expectancy"] = -0.01
    assert _historical_stability_pass(row) is False


def test_candidate_rank_prefers_cross_year_coverage_over_one_trade_win() -> None:
    sparse = {
        "historical_stability_pass": False,
        "annual_2x_cost": {"2025": {"trades": 1, "expectancy": 100.0}},
        "aggregate_2x_cost": {"expectancy": 100.0},
    }
    covered = {
        "historical_stability_pass": False,
        "annual_2x_cost": {
            year: {"trades": 2, "expectancy": -1.0}
            for year in ("2024", "2025", "2026")
        },
        "aggregate_2x_cost": {"expectancy": -1.0},
    }
    assert _candidate_rank(covered) > _candidate_rank(sparse)
