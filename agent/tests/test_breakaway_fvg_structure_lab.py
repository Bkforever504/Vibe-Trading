from __future__ import annotations

from datetime import date

import pandas as pd

from research.breakaway_fvg_structure_lab import Signal, manage_trade, summarize


def _bars(rows):
    frame = pd.DataFrame(rows, columns=["dt", "open", "high", "low", "close"])
    frame["dt"] = pd.to_datetime(frame["dt"])
    frame["date"] = date(2026, 8, 4)
    frame["time"] = frame["dt"].dt.strftime("%H:%M")
    return frame


def _signal() -> Signal:
    return Signal(
        direction=1,
        formed_at=pd.Timestamp("2026-08-04 09:45"),
        expires_at=pd.Timestamp("2026-08-04 10:15"),
        midpoint=100.0,
        stop=98.0,
        risk_points=2.0,
        structure_level=100.5,
        gap_bottom=99.5,
        gap_top=100.5,
    )


def test_same_bar_stop_beats_target() -> None:
    bars = _bars([("2026-08-04 09:46", 100, 104.5, 97.5, 103)])
    points, reason = manage_trade(bars, _signal(), 0)
    assert points == -2.0
    assert reason == "stop"


def test_breakeven_only_applies_after_arm_bar() -> None:
    bars = _bars([
        ("2026-08-04 09:46", 100, 102.1, 99.5, 101.5),
        ("2026-08-04 09:47", 101.5, 101.6, 99.8, 100.1),
    ])
    points, reason = manage_trade(bars, _signal(), 0)
    assert points == 0.0
    assert reason == "breakeven"


def test_summary_includes_two_sided_costs() -> None:
    rows = [
        {"points_before_cost": 4.0, "exit_reason": "target"},
        {"points_before_cost": -2.0, "exit_reason": "stop"},
    ]
    result = summarize(rows)
    assert result["trades"] == 2
    assert result["total_pnl"] == 0.04
    assert result["max_drawdown"] == 14.98
    assert result["exit_reasons"] == {"stop": 1, "target": 1}
