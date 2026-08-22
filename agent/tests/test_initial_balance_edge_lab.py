from __future__ import annotations

import pandas as pd

from research.initial_balance_edge_lab import (
    MES,
    _exit_r,
    _session_context,
    complete_sessions,
    descriptive,
    metrics,
    replay,
)


def frame(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    index = [pd.Timestamp(timestamp) for timestamp, *_ in rows]
    values = [(open_, high, low, close, 1000) for _, open_, high, low, close in rows]
    return pd.DataFrame(values, columns=["open", "high", "low", "close", "volume"], index=index)


def test_extreme_order_uses_final_range_extremes_without_lookahead() -> None:
    bars = frame([
        ("2026-07-20 09:30", 100, 103, 99, 102),
        ("2026-07-20 09:35", 102, 104, 101, 103),
        ("2026-07-20 09:40", 103, 103, 98, 99),
        ("2026-07-20 09:45", 99, 99.5, 97, 98),
    ])
    context = _session_context(bars, 15)
    assert context is not None
    assert context["order"] == "high_first"
    assert context["high"] == 104
    assert context["low"] == 98


def test_sweep_entry_cannot_use_opening_range_bar() -> None:
    bars = frame([
        ("2026-07-20 09:30", 100, 104, 99, 103),
        ("2026-07-20 09:35", 103, 103, 100, 101),
        ("2026-07-20 09:40", 101, 102, 98, 99),
        ("2026-07-20 09:45", 99, 99.5, 97, 98),
        ("2026-07-20 09:50", 98, 99, 96, 97),
    ])
    trade = replay(bars, 15, MES)["extreme_order_sweep"][0]
    assert trade["direction"] == "short"
    assert trade["outcome"] == "target"


def test_same_bar_stop_target_collision_fails_conservatively() -> None:
    future = frame([("2026-07-20 10:30", 100, 102, 98, 100)])
    gross, result, outcome = _exit_r(future, side=1, entry=100, stop=99, target=101, cost_r=0)
    assert outcome == "stop"
    assert gross == -1
    assert result == -1


def test_sweep_is_skipped_when_market_gaps_through_target() -> None:
    bars = frame([
        ("2026-07-20 09:30", 100, 104, 99, 103),
        ("2026-07-20 09:35", 103, 103, 100, 101),
        ("2026-07-20 09:40", 101, 102, 98, 99),
        ("2026-07-20 09:45", 97, 98, 96, 97),
    ])
    assert replay(bars, 15, MES)["extreme_order_sweep"] == []


def test_descriptive_single_break_is_not_a_trade_win_rate() -> None:
    bars = frame([
        ("2026-07-20 09:30", 100, 103, 99, 102),
        ("2026-07-20 09:35", 102, 104, 101, 103),
        ("2026-07-20 09:40", 103, 103, 98, 99),
        ("2026-07-20 09:45", 99, 105, 99, 104),
        ("2026-07-20 09:50", 104, 106, 100, 105),
    ])
    result = descriptive(bars, 15)
    assert result["wick"]["single_break"] == 1
    assert "win_rate" not in result["wick"]


def test_metrics_include_costs_drawdown_and_uncertainty() -> None:
    trades = [
        {"gross_r": value + 0.1, "cost_r": 0.1, "net_r": value, "outcome": "target" if value > 0 else "stop"}
        for value in [1, -1, 1, -1, 1, -1, 1, -1, 1, -1]
    ]
    result = metrics(trades)
    assert result["trades"] == 10
    assert result["expectancy_r"] == 0
    assert result["gross_expectancy_r"] == 0.1
    assert result["average_cost_r"] == 0.1
    assert result["profit_factor"] == 1
    assert result["max_drawdown_r"] == 1
    assert result["target_hit_rate"] == 0.5
    assert result["expectancy_95pct_moving_5_trade_block_ci"][0] is not None


def test_incomplete_sessions_and_1600_bar_are_excluded() -> None:
    complete_index = pd.date_range("2026-07-20 09:30", periods=390, freq="1min")
    incomplete_index = pd.date_range("2026-07-21 09:30", periods=389, freq="1min")
    extra_close_bar = pd.DatetimeIndex([pd.Timestamp("2026-07-20 16:00")])
    index = complete_index.append(incomplete_index).append(extra_close_bar)
    bars = pd.DataFrame(
        {"open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        index=index,
    ).between_time("09:30", "15:59")
    filtered, coverage = complete_sessions(bars)
    assert coverage["raw_sessions"] == 2
    assert coverage["complete_sessions"] == 1
    assert len(filtered) == 390
