from __future__ import annotations

import pandas as pd
import pytest

from research.swing_exit_overlay_lab import POLICIES, simulate_asset, true_range


def frame(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def test_true_range_includes_prior_close_gap() -> None:
    data = frame([(100, 101, 99, 100), (110, 112, 109, 111)])
    values = true_range(data)
    assert values.iloc[1] == pytest.approx(12.0)


def test_gap_below_stop_exits_at_open_not_optimistic_stop() -> None:
    rows = [(100, 101, 99, 100)] * 20
    rows.extend([(100, 101, 99, 100), (80, 82, 79, 81)])
    policy = next(item for item in POLICIES if item.name == "initial_stop_2_5atr")
    result = simulate_asset(frame(rows), 20, policy)
    assert result["reason"] == "gap_stop"
    assert result["exit"] == 80


def test_chandelier_uses_completed_close_for_next_session() -> None:
    rows = [(100, 101, 99, 100)] * 20
    rows.extend([
        (100, 111, 99, 110),
        (110, 111, 105, 106),
    ])
    policy = next(item for item in POLICIES if item.name == "chandelier_3atr")
    result = simulate_asset(frame(rows), 20, policy)
    assert result["exit_pos"] >= 21
