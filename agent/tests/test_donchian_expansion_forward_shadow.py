from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.donchian_expansion_forward_shadow import resolve_signal


ET = ZoneInfo("America/New_York")


def _signal(direction: str = "bullish") -> dict:
    return {"symbol": "TSLA", "direction": direction, "signal_bar_completed_at": datetime(2026, 8, 31, 11, 0, tzinfo=ET).isoformat(), "initial_stop_reference": 99.0 if direction == "bullish" else 101.0}


def test_forward_shadow_uses_next_bar_open_and_costs() -> None:
    start = datetime(2026, 8, 31, 11, 5, tzinfo=ET)
    rows = [
        {"t": start.isoformat(), "o": 100.0, "h": 100.4, "l": 99.7, "c": 100.2},
        {"t": (start + timedelta(minutes=5)).isoformat(), "o": 100.3, "h": 102.3, "l": 100.0, "c": 102.1},
    ]
    result = resolve_signal(_signal(), rows)
    assert result["status"] == "resolved"
    assert result["exit_reason"] == "target_2r"
    assert result["entry_raw"] == 100.0
    assert result["net_r_after_costs"] < 2.0
    assert result["can_submit_orders"] is False


def test_stop_wins_when_a_bar_hits_both_stop_and_target() -> None:
    start = datetime(2026, 8, 31, 11, 5, tzinfo=ET)
    rows = [{"t": start.isoformat(), "o": 100.0, "h": 103.0, "l": 98.0, "c": 101.0}]
    result = resolve_signal(_signal(), rows)
    assert result["status"] == "resolved"
    assert result["exit_reason"] == "stop"
