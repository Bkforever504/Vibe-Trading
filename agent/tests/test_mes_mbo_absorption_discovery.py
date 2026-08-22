from __future__ import annotations

from research.mes_mbo_absorption_discovery import direction, evaluate_windows


def row(bucket: int, *, fill: float = 0.0, pressure: float = 0.0, depth: float = 0.0) -> dict:
    return {
        "bucket": bucket,
        "passive_fill_imbalance": fill,
        "cancel_add_pressure": pressure,
        "depth_imbalance": depth,
        "valid_book": True,
        "best_bid": 100_000_000_000 + bucket * 250_000_000,
        "best_ask": 100_250_000_000 + bucket * 250_000_000,
    }


def test_direction_requires_frozen_three_way_conjunction() -> None:
    assert direction(row(0, fill=0.5, pressure=0.08, depth=0.6)) == 1
    assert direction(row(0, fill=-0.5, pressure=-0.08, depth=-0.6)) == -1
    assert direction(row(0, fill=0.5, pressure=-0.08, depth=0.6)) == 0


def test_evaluation_enters_next_window_and_uses_executable_quotes() -> None:
    rows = [row(index) for index in range(9)]
    rows[0] = row(0, fill=0.5, pressure=0.08, depth=0.6)
    trades = evaluate_windows(rows, "2026-07-16")
    assert len(trades) == 1
    assert trades[0]["direction"] == "bullish"
    assert trades[0]["net_pnl_usd"] == 3.77
    assert trades[0]["stressed_pnl_usd"] == -1.21
