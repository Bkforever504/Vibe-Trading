from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.fibonacci_structure_lab import LabConfig, _metrics, _simulate_trade


def test_same_bar_ambiguity_is_stop_first() -> None:
    future = pd.DataFrame(
        [{"open": 100.0, "high": 102.0, "low": 98.0, "close": 101.0}],
        index=[pd.Timestamp("2026-08-17 10:00")],
    )
    outcome = _simulate_trade(
        future,
        direction=1,
        entry=100.0,
        stop=99.0,
        target=101.0,
        cost_bps=0.0,
    )
    assert outcome["exit_reason"] == "stop_first"
    assert outcome["net_r"] == -1.0


def test_metrics_are_cost_inclusive() -> None:
    metrics = _metrics(
        [
            {"date": "2026-08-17", "net_r": 1.0},
            {"date": "2026-08-18", "net_r": -0.5},
        ]
    )
    assert metrics["expectancy_r"] == 0.25
    assert metrics["profit_factor"] == 2.0
    assert LabConfig().round_trip_cost_bps > 0
