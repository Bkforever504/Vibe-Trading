from datetime import datetime, timedelta, timezone

import pandas as pd

from scripts.contextual_pattern_observation import completed_4h_bars, fvg_zones, inside_bar


def _bars(start: datetime, rows: int) -> pd.DataFrame:
    index = pd.date_range(pd.Timestamp(start).tz_convert("America/New_York"), periods=rows, freq="15min")
    return pd.DataFrame({
        "Open": [100.0 + i for i in range(rows)],
        "High": [101.0 + i for i in range(rows)],
        "Low": [99.0 + i for i in range(rows)],
        "Close": [100.5 + i for i in range(rows)],
        "Volume": [1000] * rows,
    }, index=index)


def test_inside_bar_is_completed_bar_geometry() -> None:
    bars = _bars(datetime(2026, 9, 1, 9, 30, tzinfo=timezone.utc), 2)
    bars.iloc[-1, bars.columns.get_loc("High")] = 100.8
    bars.iloc[-1, bars.columns.get_loc("Low")] = 99.2
    observed = inside_bar(bars)
    assert observed["state"] == "observed"
    assert observed["breakout_above"] == 100.8


def test_four_hour_resample_rejects_partial_window() -> None:
    start = datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc)
    assert completed_4h_bars(_bars(start, 15)).empty


def test_fvg_requires_three_completed_four_hour_bars() -> None:
    index = pd.date_range("2026-08-28 13:30", periods=3, freq="4h", tz="America/New_York")
    bars = pd.DataFrame({
        "Open": [100.0, 105.0, 111.0], "High": [102.0, 110.0, 115.0],
        "Low": [99.0, 104.0, 108.0], "Close": [101.0, 109.0, 114.0], "Volume": [1, 1, 1],
    }, index=index)
    zones = fvg_zones(bars)
    assert zones == [{"direction": "bullish", "low": 102.0, "high": 108.0, "formed_at": index[-1].isoformat()}]
