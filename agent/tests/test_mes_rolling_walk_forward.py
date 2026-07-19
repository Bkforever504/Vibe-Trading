from __future__ import annotations

import pytest

from research.mes_rolling_walk_forward import sequential_windows


def test_sequential_windows_are_non_overlapping_and_complete() -> None:
    dates = [f"day-{index:03d}" for index in range(10)]
    windows = sequential_windows(dates, 4)
    assert [len(window) for window in windows] == [4, 4, 2]
    assert [date for window in windows for date in window] == dates


def test_sequential_windows_reject_invalid_size() -> None:
    with pytest.raises(ValueError):
        sequential_windows(["day-001"], 0)
