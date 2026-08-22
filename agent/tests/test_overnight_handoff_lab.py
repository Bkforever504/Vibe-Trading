from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import overnight_handoff_lab as lab


def test_session_returns_splits_overnight_and_intraday_without_future_data() -> None:
    bars = pd.DataFrame(
        [
            {"open": 100.0, "close": 100.0},
            {"open": 102.0, "close": 101.0},
            {"open": 99.0, "close": 100.0},
        ],
        index=pd.to_datetime(["2026-07-24", "2026-07-27", "2026-07-28"]),
    )

    rows = lab.session_returns("SPY", bars)

    assert len(rows) == 2
    assert rows[0].day == "2026-07-27"
    assert rows[0].overnight_return_pct == 2.0
    assert rows[0].intraday_return_pct == -0.9804
    assert rows[1].overnight_return_pct == -1.9802
    assert rows[1].intraday_return_pct == 1.0101


def test_classify_handoff_uses_gap_floor_and_direction() -> None:
    assert lab.classify_handoff(0.1, -0.5, 0.35) == "small_gap_no_handoff"
    assert lab.classify_handoff(0.7, -0.4, 0.35) == "rth_reversal"
    assert lab.classify_handoff(-0.7, -0.4, 0.35) == "rth_continuation"


def test_summarize_flags_large_gap_reversal_guidance() -> None:
    rows = [
        lab.SessionReturn("2026-07-20", "SPY", 0.8, -0.4, 0.4, "ordinary"),
        lab.SessionReturn("2026-07-21", "SPY", -0.9, 0.3, -0.6, "ordinary"),
        lab.SessionReturn("2026-07-22", "SPY", 0.6, -0.2, 0.4, "ordinary"),
        lab.SessionReturn("2026-07-23", "SPY", 0.1, 0.2, 0.3, "ordinary"),
    ]

    summary = lab.summarize(rows, gap_floor_pct=0.35)

    assert summary["large_gap_count"] == 3
    assert summary["large_gap_reversal_rate"] == 1.0
    assert summary["shadow_guidance"] == "shadow_fade_chasing_rth_breakouts_after_large_overnight_gap"


def test_calendar_tag_marks_month_boundary() -> None:
    assert lab.calendar_tag(pd.Timestamp("2026-06-30").date()) == "quarter_end"
    assert lab.calendar_tag(pd.Timestamp("2026-07-31").date()) == "month_end"
    assert lab.calendar_tag(pd.Timestamp("2026-08-03").date()) == "month_start"
    assert lab.calendar_tag(pd.Timestamp("2026-07-28").date()) == "ordinary"
