from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.nq_late_orb_retest_shadow import build_snapshot
from strategies.topstep_prop_bot import Candle


def _bar(minute: int, open_: float, high: float, low: float, close: float, volume: int = 100) -> Candle:
    return Candle(datetime(2026, 8, 19, 9, 30) + timedelta(minutes=minute), open_, high, low, close, volume)


def test_snapshot_is_shadow_only_and_records_gap_aligned_candidate() -> None:
    bars = [
        _bar(0, 100, 101, 99, 100),
        _bar(5, 100, 102, 99, 101),
        _bar(10, 101, 102, 100, 101),
        _bar(15, 101, 115, 101, 114),
        _bar(20, 114, 114.5, 101.5, 105),
    ]
    report = build_snapshot(
        bars,
        99.0,
        observed_at=datetime(2026, 8, 19, 14, 0, tzinfo=timezone.utc),
    )
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["state"] == "candidate_observed"
    assert report["signal"]["gap_aligned"] is True


def test_snapshot_blocks_counter_gap_signal() -> None:
    bars = [
        _bar(0, 100, 101, 99, 100),
        _bar(5, 100, 102, 99, 101),
        _bar(10, 101, 102, 100, 101),
        _bar(15, 101, 115, 101, 114),
        _bar(20, 114, 114.5, 101.5, 105),
    ]
    report = build_snapshot(bars, 101.0)
    assert report["state"] == "gap_direction_not_aligned"
    assert report["signal"] is None


def test_snapshot_labels_runaway_breakout_without_inventing_retest() -> None:
    bars = [
        _bar(0, 100, 101, 99, 100),
        _bar(5, 100, 102, 99, 101),
        _bar(10, 101, 102, 100, 101),
        _bar(15, 101, 115, 103, 114),
        _bar(20, 114, 120, 110, 119),
        _bar(25, 119, 125, 116, 124),
    ]
    report = build_snapshot(bars, 99.0)
    assert report["state"] == "breakout_without_qualified_retest"
    assert report["signal"] is None
    assert report["missed_move_diagnostic"]["gap_aligned"] is True
    assert report["missed_move_diagnostic"]["max_favorable_excursion_points"] == 11.0
