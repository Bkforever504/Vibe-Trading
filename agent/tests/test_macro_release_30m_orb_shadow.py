from datetime import date

import pandas as pd

from scripts.macro_release_30m_orb_shadow import evaluate_session


SESSION = date(2026, 9, 1)
EVENTS = [
    {"time_et": "10:00", "name": "JOLTS Release (July 2026)"},
    {"time_et": "10:00", "name": "ISM Manufacturing PMI Release (August 2026)"},
]


def _frame() -> pd.DataFrame:
    index = pd.date_range("2026-09-01 09:30", periods=35, freq="1min", tz="America/New_York")
    bars = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 10.0}, index=index)
    bars.iloc[30:35, bars.columns.get_loc("High")] = 102.0
    bars.iloc[30:35, bars.columns.get_loc("Close")] = 101.5
    bars.iloc[30:35, bars.columns.get_loc("Volume")] = 30.0
    return bars


def test_requires_both_primary_releases() -> None:
    result = evaluate_session(_frame(), SESSION, EVENTS[:1], prior_release_volumes=[100.0] * 20)
    assert result["reason"] == "dual_10am_primary_release_not_scheduled"
    assert result["should_observe"] is False


def test_missing_provider_data_is_not_an_exception_or_candidate() -> None:
    result = evaluate_session(pd.DataFrame(), SESSION, EVENTS)
    assert result["reason"] == "incomplete_completed_1m_bars"
    assert result["should_observe"] is False


def test_uses_completed_30m_range_then_release_bar() -> None:
    result = evaluate_session(_frame(), SESSION, EVENTS, prior_release_volumes=[100.0] * 20)
    assert result["reason"] == "qualified_shadow_candidate"
    assert result["direction"] == "long"
    assert result["reaction_bar"]["completed_at_et"] == "10:05"
    assert result["entry_assumption"].startswith("next_completed_1m")
    assert result["execution_enabled"] is False


def test_missing_twenty_release_baselines_fails_closed() -> None:
    result = evaluate_session(_frame(), SESSION, EVENTS, prior_release_volumes=[100.0] * 19)
    assert result["reason"] == "awaiting_volume_baseline"
    assert result["volume_pass"] is False
