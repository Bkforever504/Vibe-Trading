from __future__ import annotations

import json
from datetime import time

import pandas as pd

from research.mes_failed_breakdown_lab import (
    FBDConfig,
    _simulate_exit,
    find_level_trade,
    metrics,
)


def _bars(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"open": open_, "high": high, "low": low, "close": close, "volume": 1000}
            for _, open_, high, low, close in rows
        ],
        index=pd.DatetimeIndex([pd.Timestamp(timestamp) for timestamp, *_ in rows]),
    )


def test_failed_breakdown_enters_after_reclaim_and_acceptance() -> None:
    bars = _bars(
        [
            ("2026-07-20 10:00", 100.5, 100.5, 99.25, 99.75),
            ("2026-07-20 10:01", 99.75, 100.5, 99.5, 100.25),
            ("2026-07-20 10:02", 100.25, 100.75, 100.0, 100.5),
            ("2026-07-20 10:03", 100.5, 101.0, 100.25, 100.75),
            ("2026-07-20 10:04", 100.75, 104.0, 100.5, 103.5),
        ]
    )
    config = FBDConfig(
        min_excursion_ticks=2,
        reclaim_window_bars=2,
        acceptance_bars=1,
        reward_risk=1.5,
        entry_start=time(10, 0),
    )
    trade = find_level_trade(
        bars,
        {"name": "test", "side": "long", "price": 100.0, "available_at": time(10, 0)},
        config,
    )

    assert trade is not None
    assert trade["entry_at"].endswith("10:03:00")
    assert trade["exit_reason"] == "target"


def test_failed_reclaim_does_not_get_retried_with_future_knowledge() -> None:
    bars = _bars(
        [
            ("2026-07-20 10:00", 100.0, 100.0, 99.0, 99.25),
            ("2026-07-20 10:01", 99.25, 99.75, 99.0, 99.5),
            ("2026-07-20 10:02", 99.5, 99.75, 99.25, 99.5),
            ("2026-07-20 10:03", 99.5, 100.5, 99.25, 100.25),
            ("2026-07-20 10:04", 100.25, 101.0, 100.0, 100.75),
        ]
    )
    config = FBDConfig(reclaim_window_bars=1, entry_start=time(10, 0))

    trade = find_level_trade(
        bars,
        {"name": "test", "side": "long", "price": 100.0, "available_at": time(10, 0)},
        config,
    )

    assert trade is None


def test_same_bar_ambiguity_resolves_to_stop() -> None:
    bars = _bars(
        [("2026-07-20 10:00", 100.0, 102.0, 98.0, 100.0)]
    )
    exit_price, _, reason = _simulate_exit(
        bars,
        entry_position=0,
        side="long",
        stop=99.0,
        target=101.0,
        exit_time=time(15, 55),
    )

    assert exit_price == 99.0
    assert reason == "stop"


def test_metrics_apply_round_trip_costs_and_outlier_removal() -> None:
    config = FBDConfig(slippage_ticks_per_side=1, commission_round_trip=2.5)
    trades = [{"gross_pnl": 20.0}, {"gross_pnl": -10.0}, {"gross_pnl": 100.0}]

    base = metrics(trades, config)
    stressed = metrics(trades, config, cost_multiple=2.0)
    trimmed = metrics(trades, config, remove_top_pct=0.01)

    assert base["total_pnl"] == 95.0
    assert stressed["total_pnl"] == 80.0
    assert trimmed["trades"] == 2
    assert trimmed["total_pnl"] == 0.0


def test_config_is_report_serializable_with_explicit_default() -> None:
    payload = json.dumps({"config": FBDConfig().__dict__}, default=str)
    assert "09:35:00" in payload
