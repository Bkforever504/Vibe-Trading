from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.refresh_intraday_radar_context import refresh_report


def test_refresh_attaches_fresh_context_without_reordering_or_enabling_execution() -> None:
    observed = datetime(2026, 8, 31, 10, 0, tzinfo=ZoneInfo("America/New_York"))
    candidate = {
        "symbol": "TSLA",
        "rank": 1,
        "structure": {
            "last_completed_bar_at": "2026-08-31T09:55:00-04:00",
            "session_volume_5m": 300.0,
        },
        "confirmation": {},
        "levels": {},
    }
    radar = {"ranked_candidates": [candidate], "actionable_ranked_candidates": [dict(candidate)], "coverage": {}}
    rvol = {
        "as_of_et": "2026-08-31T10:00:00-04:00",
        "provider": "test_rvol",
        "profiles": {"TSLA": {"status": "ok", "sessions_used": 5, "cumulative_volume_baseline_by_clock_et": {"09:55": 100.0}}},
        "errors": [],
    }
    sec = {"status": "ok", "generated_at": "2026-08-31T13:59:00Z", "catalysts": []}

    refreshed = refresh_report(radar, rvol, sec, observed)

    row = refreshed["ranked_candidates"][0]
    assert row["rank"] == 1
    assert row["time_matched_rvol"]["value"] == 3.0
    assert row["primary_catalyst"]["status"] == "no_matching_primary_filing"
    assert refreshed["actionable_ranked_candidates"][0]["symbol"] == "TSLA"
    assert refreshed["execution_enabled"] is False
    assert refreshed["can_submit_orders"] is False
