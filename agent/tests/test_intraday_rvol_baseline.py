from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.intraday_rvol_baseline import build_profiles


ET = ZoneInfo("America/New_York")


def test_profiles_use_prior_session_cumulative_volume_at_the_same_clock_time() -> None:
    rows = {
        "TSLA": [
            {"t": "2026-08-18T13:30:00Z", "v": 100}, {"t": "2026-08-18T13:35:00Z", "v": 50},
            {"t": "2026-08-19T13:30:00Z", "v": 200}, {"t": "2026-08-19T13:35:00Z", "v": 100},
        ]
    }
    # Add enough complete bars to make the two sessions eligible without
    # changing the 09:35 cumulative baseline being asserted.
    for day in (18, 19):
        start = datetime(2026, 8, day, 9, 40, tzinfo=ET)
        for index in range(48):
            rows["TSLA"].append({"t": (start + timedelta(minutes=5 * index)).astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"), "v": 1})
    profiles = build_profiles(rows, datetime(2026, 8, 20, 10, 0, tzinfo=ET), lookback_sessions=20)

    assert profiles["TSLA"]["status"] == "insufficient_prior_sessions"
    assert profiles["TSLA"]["cumulative_volume_baseline_by_clock_et"]["09:35"] == 225.0
