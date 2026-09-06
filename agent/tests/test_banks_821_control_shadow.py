from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.banks_821_control_shadow import assess_symbol


ET = ZoneInfo("America/New_York")


def test_821_shadow_emits_completed_bar_observation_without_execution_authority() -> None:
    rows = []
    start = datetime(2026, 8, 28, 9, 30, tzinfo=ET)
    for index in range(75):
        stamp = start + timedelta(minutes=5 * index)
        rows.append({"t": stamp.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"), "o": 100, "h": 101, "l": 99, "c": 100, "v": 100})
    start = datetime(2026, 8, 31, 9, 30, tzinfo=ET)
    for index in range(5):
        stamp = start + timedelta(minutes=5 * index)
        rows.append({"t": stamp.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"), "o": 100, "h": 101, "l": 99, "c": 100, "v": 100})

    result = assess_symbol("TSLA", rows, datetime(2026, 8, 31, 10, 0, tzinfo=ET))

    assert result["status"] == "observed"
    assert "8_21_range" in result["no_trade_reasons"]
    assert result["can_submit_orders"] is False
