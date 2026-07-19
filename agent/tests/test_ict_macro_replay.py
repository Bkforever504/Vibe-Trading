from __future__ import annotations

import pandas as pd

from scripts.ict_macro_replay import ReplayCosts, readiness, resolve_outcome, summarize


def _signal(direction: str = "buy") -> dict:
    return {
        "entry_at": "2026-07-20T10:00:00-04:00",
        "entry": 100.0,
        "stop": 99.0 if direction == "buy" else 101.0,
        "target": 102.0 if direction == "buy" else 98.0,
        "direction": direction,
    }


def _bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    index = pd.date_range("2026-07-20 10:00", periods=len(rows), freq="5min", tz="America/New_York")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)


def test_target_hit_resolves_win_and_deducts_costs() -> None:
    bars = _bars([(100, 100.2, 99.8, 100), (100, 102.1, 99.9, 102)])
    result = resolve_outcome(bars, _signal(), symbol="MNQ", costs=ReplayCosts())

    assert result["outcome"] == "win"
    assert result["net_pnl"] == 1.76


def test_same_bar_stop_and_target_is_conservative_loss() -> None:
    bars = _bars([(100, 100.2, 99.8, 100), (100, 102.1, 98.9, 100)])
    result = resolve_outcome(bars, _signal(), symbol="MNQ", costs=ReplayCosts())

    assert result["outcome"] == "loss"
    assert result["net_pnl"] == -4.24


def test_short_target_hit_uses_mes_point_value() -> None:
    bars = _bars([(100, 100.2, 99.8, 100), (100, 100.1, 97.9, 98)])
    result = resolve_outcome(bars, _signal("sell"), symbol="MES", costs=ReplayCosts())

    assert result["outcome"] == "win"
    assert result["net_pnl"] == 6.26


def test_summary_tracks_holdout_metrics_and_drawdown() -> None:
    summary = summarize([{"net_pnl": 10}, {"net_pnl": -4}, {"net_pnl": -7}, {"net_pnl": 5}])

    assert summary["trades"] == 4
    assert summary["win_rate"] == 0.5
    assert summary["profit_factor"] == 1.364
    assert summary["max_drawdown"] == 11.0


def test_readiness_blocks_negative_small_sample() -> None:
    all_metrics = summarize([{"net_pnl": 10}, {"net_pnl": -20}])
    holdout_metrics = summarize([{"net_pnl": -20}])
    result = readiness(all_metrics, holdout_metrics)

    assert result["verdict"] == "BLOCKED"
    assert result["evidence_confidence_score"] < 5
