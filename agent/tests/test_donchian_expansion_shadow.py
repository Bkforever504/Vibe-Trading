from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.donchian_expansion_shadow import assess_symbol


ET = ZoneInfo("America/New_York")


def _rows(*, expansion: bool = True) -> list[dict]:
    start = datetime(2026, 8, 31, 9, 30, tzinfo=ET)
    rows = []
    for index in range(36):
        stamp = start + timedelta(minutes=5 * index)
        rows.append({"t": stamp.isoformat(), "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.0, "v": 100.0})
    if expansion:
        rows[-1] = {"t": (start + timedelta(minutes=5 * 35)).isoformat(), "o": 100.5, "h": 104.0, "l": 100.0, "c": 103.5, "v": 300.0}
    return rows


def test_strict_bullish_expansion_requires_completed_prior_bar_history() -> None:
    result = assess_symbol("TSLA", _rows(), datetime(2026, 8, 31, 12, 30, tzinfo=ET))
    assert result["status"] == "observed"
    assert result["direction"] == "bullish"
    assert result["strict_expansion_hit"] is True
    assert result["evidence"]["volume_multiple_vs_prior_20_completed_bars"] == 3.0
    assert result["can_submit_orders"] is False


def test_standard_break_without_range_expansion_is_not_a_shadow_hit() -> None:
    rows = _rows()
    rows[-1].update({"h": 101.2, "l": 100.8, "c": 101.1, "v": 300.0})
    result = assess_symbol("TSLA", rows, datetime(2026, 8, 31, 12, 30, tzinfo=ET))
    assert result["standard_direction"] == "bullish"
    assert result["direction"] == "none"
    assert "true_range_not_above_1_20x_prior_atr" in result["blockers"]


def test_incomplete_open_has_no_signal() -> None:
    result = assess_symbol("TSLA", _rows()[:10], datetime(2026, 8, 31, 10, 20, tzinfo=ET))
    assert result["status"] == "unavailable"
    assert result["reason"] == "insufficient_completed_current_rth_bars"
