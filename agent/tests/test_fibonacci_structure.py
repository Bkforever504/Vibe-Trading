from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.fibonacci_structure import (
    FibonacciConfig,
    FibonacciExecutionConfig,
    analyze_fibonacci_structure,
    build_fibonacci_execution_plan,
    confirmed_pivots,
    confirmed_zigzag_pivots,
)
from strategies import flip_bot


def _frame(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    index = pd.date_range("2026-08-17 09:30", periods=len(rows), freq="5min")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=index)


def test_pivot_is_not_visible_until_right_bars_complete() -> None:
    bars = _frame(
        [
            (10, 10.2, 9.8, 10),
            (10, 10.5, 9.9, 10.4),
            (10.4, 11.0, 10.3, 10.9),
            (10.9, 10.8, 10.4, 10.5),
            (10.5, 10.7, 10.2, 10.3),
        ]
    )
    assert not any(row["kind"] == "high" for row in confirmed_pivots(bars.iloc[:4], left_bars=2, right_bars=2))
    pivots = confirmed_pivots(bars, left_bars=2, right_bars=2)
    high = next(row for row in pivots if row["kind"] == "high")
    assert high["position"] == 2
    assert high["confirmed_position"] == 4


def test_bullish_golden_zone_requires_rejection_confirmation() -> None:
    rows = []
    closes = [10.0, 9.8, 9.5, 9.7, 10.0, 10.4, 10.8, 11.2, 11.5, 11.3, 11.1, 10.75, 10.72]
    for close in closes:
        rows.append((close - 0.05, close + 0.12, close - 0.12, close))
    result = analyze_fibonacci_structure(
        _frame(rows),
        "bullish",
        config=FibonacciConfig(left_bars=2, right_bars=2, atr_length=3, min_impulse_atr=1.0),
    )
    assert result["status"] in {"confirmed", "awaiting_confirmation", "outside_zone", "deep_retracement"}
    assert result["can_submit_orders"] is False
    assert result["anchor_end_was_confirmed_at"] >= result["anchor_end"]["timestamp"]


def test_unknown_direction_fails_deterministically() -> None:
    result = analyze_fibonacci_structure(_frame([(1, 2, 0.5, 1.5)] * 30), "sideways")
    assert result["status"] == "error"
    assert result["reason"] == "unknown_direction"


def test_zigzag_extreme_is_available_only_after_atr_reversal() -> None:
    closes = [10.0] * 14 + [10.2, 10.5, 10.8, 11.1, 11.0, 10.8, 10.5]
    bars = _frame([(close, close + 0.1, close - 0.1, close) for close in closes])
    pivots = confirmed_zigzag_pivots(bars, atr_length=5, reversal_atr=1.0)
    assert pivots
    for pivot in pivots:
        assert pivot["confirmed_position"] >= pivot["position"]


def test_flip_pretrade_hook_attaches_analysis_without_execution_authority(monkeypatch) -> None:
    from strategies import flip_bot

    bars = _frame([(10 + index * 0.05, 10.2 + index * 0.05, 9.8 + index * 0.05, 10.1 + index * 0.05) for index in range(35)])
    monkeypatch.setattr(flip_bot, "_intraday_bars", lambda _symbol: bars)
    monkeypatch.setattr(flip_bot, "_completed_intraday_bars", lambda frame: frame)
    setup = {"symbol": "SPY", "right": "CALL", "strategy": "test"}

    result = flip_bot._attach_fibonacci_pretrade_analysis(setup)

    assert setup["fibonacci_structure"] is result
    assert result["can_submit_orders"] is False
    assert result["execution_authority"].startswith("analysis_only")
    assert result["execution_plan"]["can_submit_orders"] is False


def test_flip_fibonacci_analysis_resamples_completed_one_minute_bars(monkeypatch) -> None:
    index = pd.date_range("2026-08-17 09:30", periods=12, freq="1min")
    frame = pd.DataFrame(
        {
            "Open": range(12),
            "High": [value + 1 for value in range(12)],
            "Low": [value - 1 for value in range(12)],
            "Close": [value + 0.5 for value in range(12)],
            "Volume": [100] * 12,
        },
        index=index,
    )

    monkeypatch.setattr(flip_bot, "_completed_intraday_bars", lambda bars: bars)
    bars = flip_bot._fibonacci_completed_bars(frame)

    assert len(bars) == 2
    assert list(bars["volume"]) == [500, 500]


def test_execution_plan_is_no_chase_shadow_only() -> None:
    analysis = {
        "status": "confirmed",
        "direction": "bullish",
        "levels": {"0.618034": 100.0},
        "planned_limit_entry_0_618": 100.0,
        "invalidation_level": 98.0,
        "atr": 1.0,
        "targets": {"prior_impulse_extreme": 103.0},
        "trend_confirmation": {"aligned": True},
    }
    plan = build_fibonacci_execution_plan(analysis)
    assert plan["status"] == "eligible_shadow"
    assert plan["entry_reference"] == 100.0
    assert plan["no_chase"] is True
    assert plan["replace_or_concede_price"] is False
    assert plan["can_submit_orders"] is False
    assert plan["can_block_production_entry"] is False


def test_execution_plan_requires_confirmation_and_valid_ttl() -> None:
    inactive = build_fibonacci_execution_plan({"status": "awaiting_confirmation"})
    assert inactive["status"] == "inactive"
    invalid = build_fibonacci_execution_plan(
        {"status": "confirmed"},
        config=FibonacciExecutionConfig(order_ttl_completed_bars=0),
    )
    assert invalid["status"] == "error"
