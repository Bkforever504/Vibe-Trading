from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.fibonacci_execution_lab import _first_retest_fill


def test_retest_limit_expires_without_chasing() -> None:
    future = pd.DataFrame(
        [
            {"low": 101.0, "high": 102.0, "close": 101.5},
            {"low": 100.8, "high": 101.8, "close": 101.0},
        ]
    )
    assert _first_retest_fill(future, direction=1, entry=100.0, stop=98.0, ttl_bars=2) is None


def test_retest_limit_records_first_touch() -> None:
    future = pd.DataFrame(
        [
            {"low": 100.5, "high": 102.0, "close": 101.0},
            {"low": 99.8, "high": 101.2, "close": 100.4},
        ]
    )
    assert _first_retest_fill(future, direction=1, entry=100.0, stop=98.0, ttl_bars=2) == 1


def test_retest_limit_cancels_after_structural_invalidation() -> None:
    future = pd.DataFrame(
        [
            {"low": 97.5, "high": 98.8, "close": 97.9},
            {"low": 99.5, "high": 101.0, "close": 100.0},
        ]
    )
    assert _first_retest_fill(future, direction=1, entry=99.0, stop=98.0, ttl_bars=2) is None
