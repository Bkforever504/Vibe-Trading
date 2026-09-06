import pandas as pd

from scripts.ftfc_continuity_shadow import assess_symbol


def test_ftfc_screen_fails_closed_without_completed_history() -> None:
    frame = pd.DataFrame({"open": [100.0] * 5, "high": [101.0] * 5, "low": [99.0] * 5, "close": [100.0] * 5, "volume": [2_000_000] * 5}, index=pd.date_range("2026-08-01", periods=5, freq="B"))
    row = assess_symbol("TSLA", frame)

    assert row["eligible"] is False
    assert row["blockers"] == ["insufficient_completed_daily_history"]
