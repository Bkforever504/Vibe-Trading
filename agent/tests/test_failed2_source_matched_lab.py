from __future__ import annotations

import pandas as pd

from research.failed2_source_matched_lab import _allows, strict_level_failed2


def candle(open_: float, high: float, low: float, close: float) -> pd.Series:
    return pd.Series({"open": open_, "high": high, "low": low, "close": close, "volume": 100})


def test_source_matched_failed2_short_is_same_candle_rejection() -> None:
    event = strict_level_failed2(
        candle(101.1, 101.3, 100.5, 100.8),
        {"pdh": 101.0},
        tolerance=0.5,
    )
    assert event == ("short", "pdh")


def test_source_matched_failed2_requires_reversal_candle_color() -> None:
    assert strict_level_failed2(
        candle(100.7, 101.3, 100.5, 100.8),
        {"pdh": 101.0},
        tolerance=0.5,
    ) is None


def test_source_matched_failed2_long_is_mirror() -> None:
    event = strict_level_failed2(
        candle(98.8, 99.5, 98.6, 99.2),
        {"pdl": 99.0},
        tolerance=0.5,
    )
    assert event == ("long", "pdl")


def test_ambiguous_two_direction_event_fails_closed() -> None:
    event = strict_level_failed2(
        candle(100.0, 101.2, 98.8, 100.0),
        {"high": 101.0, "low": 99.0},
        tolerance=0.5,
    )
    assert event is None


def test_source_full_variant_requires_all_contexts() -> None:
    assert _allows("level_failed2_full", killzone=True, ha=True, vwap=True, htf=True)
    assert not _allows("level_failed2_full", killzone=True, ha=True, vwap=False, htf=True)
