from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from strategies.flip_retest_quality import score_retest_quality


def _frame(highs, lows, closes, volumes) -> pd.DataFrame:
    start = datetime(2026, 7, 17, 9, 30)
    return pd.DataFrame(
        {"High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=pd.DatetimeIndex([start + timedelta(minutes=i) for i in range(len(closes))]),
    )


def test_controlled_fast_low_volume_retest_grades_a() -> None:
    bars = _frame(
        [100.5, 100.7, 100.8, 100.9, 101.0, 101.4, 101.2, 101.3],
        [99.8, 100.0, 100.1, 100.0, 100.2, 100.9, 100.98, 101.05],
        [100.2, 100.4, 100.5, 100.6, 100.8, 101.3, 101.1, 101.25],
        [100, 100, 100, 100, 100, 1000, 400, 500],
    )
    result = score_retest_quality(
        bars, breakout_pos=5, retest_pos=6, direction="bull", orb_high=101.0, orb_low=100.0
    )

    assert result.grade == "A"
    assert result.minutes_since_breakout == 1
    assert result.volume_on_test_vs_breakout == 0.4


def test_extended_retest_is_rejected_even_when_other_components_pass() -> None:
    bars = _frame(
        [100.5, 100.7, 100.8, 100.9, 101.0, 102.8, 101.2],
        [99.8, 100.0, 100.1, 100.0, 100.2, 100.9, 100.98],
        [100.2, 100.4, 100.5, 100.6, 100.8, 102.5, 101.1],
        [100, 100, 100, 100, 100, 1000, 400],
    )
    result = score_retest_quality(
        bars, breakout_pos=5, retest_pos=6, direction="bull", orb_high=101.0, orb_low=100.0
    )

    assert result.grade == "rejected"
    assert result.pre_retest_extension_pct > 1.5

