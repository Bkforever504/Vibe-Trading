from __future__ import annotations

from research.mes_intraday_momentum_lab import MomentumConfig, simulate


def test_momentum_and_reversal_have_opposite_gross_direction() -> None:
    rows = [{
        "opening_return": 0.01, "entry": 100.0, "exit": 102.0,
        "opening_volume": 1000, "volume_average": 900,
        "prior_close": 100.0, "daily_sma20": 99.0,
    }]
    momentum = simulate(rows, MomentumConfig("momentum", 0, 0, False))
    reversal = simulate(rows, MomentumConfig("reversal", 0, 0, False))
    assert momentum["total_pnl"] > reversal["total_pnl"]


def test_doubled_costs_reduce_result() -> None:
    rows = [{
        "opening_return": 0.01, "entry": 100.0, "exit": 102.0,
        "opening_volume": 1000, "volume_average": 900,
        "prior_close": 100.0, "daily_sma20": 99.0,
    }]
    config = MomentumConfig("momentum", 0, 0, False)
    assert simulate(rows, config, doubled_costs=True)["total_pnl"] < simulate(rows, config)["total_pnl"]
