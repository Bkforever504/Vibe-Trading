from __future__ import annotations

import pandas as pd

from scripts.fetch_databento_futures import (
    DownloadSpec,
    audit_sessions,
    normalize_rth,
    request_kwargs,
)


def test_request_uses_volume_front_month_continuous_symbol() -> None:
    spec = DownloadSpec("MES", "2024-01-01", "2025-01-01")
    request = request_kwargs(spec)
    assert request["symbols"] == "MES.v.0"
    assert request["stype_in"] == "continuous"
    assert request["schema"] == "ohlcv-1m"


def test_normalize_rth_excludes_roll_session_and_overnight() -> None:
    index = pd.to_datetime([
        "2026-06-17T12:00:00Z",  # 08:00 ET
        "2026-06-17T13:30:00Z",  # 09:30 ET
        "2026-06-18T13:30:00Z",  # instrument changes; exclude date
        "2026-06-19T13:30:00Z",
    ])
    frame = pd.DataFrame(
        {
            "open": [1, 2, 3, 4], "high": [2, 3, 4, 5], "low": [0, 1, 2, 3],
            "close": [1.5, 2.5, 3.5, 4.5], "volume": [10, 20, 30, 40],
            "instrument_id": [100, 100, 200, 200], "symbol": ["MES.v.0"] * 4,
        },
        index=index,
    )
    clean, rolls, transitions = normalize_rth(frame)
    assert rolls == ["2026-06-18"]
    assert clean["timestamp"].tolist() == ["2026-06-17T09:30:00", "2026-06-19T09:30:00"]
    assert len(transitions) == 1
    assert transitions[0]["old_instrument_id"] == 100
    assert transitions[0]["new_instrument_id"] == 200
    assert transitions[0]["excluded_session"] == "2026-06-18"


def test_normalize_rth_excludes_degraded_condition_date() -> None:
    index = pd.to_datetime(["2026-06-16T13:30:00Z", "2026-06-17T13:30:00Z"])
    frame = pd.DataFrame(
        {
            "open": [1, 2], "high": [2, 3], "low": [0, 1],
            "close": [1.5, 2.5], "volume": [10, 20],
            "instrument_id": [100, 100], "symbol": ["MES.v.0"] * 2,
        },
        index=index,
    )
    clean, _, _ = normalize_rth(frame, excluded_condition_dates={"2026-06-16"})
    assert clean["timestamp"].tolist() == ["2026-06-17T09:30:00"]


def test_sunday_roll_excludes_following_monday_rth_session() -> None:
    index = pd.to_datetime([
        "2026-06-12T13:30:00Z",  # Friday 09:30 ET, old contract
        "2026-06-14T22:00:00Z",  # Sunday 18:00 ET, instrument changes overnight
        "2026-06-15T13:30:00Z",  # Monday 09:30 ET, first RTH session on new contract
        "2026-06-16T13:30:00Z",  # Tuesday 09:30 ET
    ])
    frame = pd.DataFrame(
        {
            "open": [1, 2, 3, 4], "high": [2, 3, 4, 5], "low": [0, 1, 2, 3],
            "close": [1.5, 2.5, 3.5, 4.5], "volume": [10, 20, 30, 40],
            "instrument_id": [100, 200, 200, 200], "symbol": ["MES.v.0"] * 4,
        },
        index=index,
    )
    clean, rolls, transitions = normalize_rth(frame)
    assert rolls == ["2026-06-15"]
    assert clean["timestamp"].tolist() == ["2026-06-12T09:30:00", "2026-06-16T09:30:00"]
    assert len(transitions) == 1
    assert transitions[0]["timestamp"].startswith("2026-06-14T18:00:00")
    assert transitions[0]["old_instrument_id"] == 100
    assert transitions[0]["new_instrument_id"] == 200
    assert transitions[0]["excluded_session"] == "2026-06-15"


def test_roll_after_last_session_records_no_exclusion() -> None:
    index = pd.to_datetime([
        "2026-06-12T13:30:00Z",  # Friday 09:30 ET
        "2026-06-14T22:00:00Z",  # Sunday roll with no later RTH session in data
    ])
    frame = pd.DataFrame(
        {
            "open": [1, 2], "high": [2, 3], "low": [0, 1],
            "close": [1.5, 2.5], "volume": [10, 20],
            "instrument_id": [100, 200], "symbol": ["MES.v.0"] * 2,
        },
        index=index,
    )
    clean, rolls, transitions = normalize_rth(frame)
    assert rolls == []
    assert clean["timestamp"].tolist() == ["2026-06-12T09:30:00"]
    assert transitions[0]["excluded_session"] is None


def _session_frame(rows: list[tuple[str, int]]) -> pd.DataFrame:
    timestamps = []
    for date, bars in rows:
        for minute in range(bars):
            timestamps.append(f"{date}T09:{30 + minute:02d}:00")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10,
        }
    )


def test_audit_sessions_excludes_unexplained_incomplete_sessions() -> None:
    clean = _session_frame([("2026-06-15", 4), ("2026-06-16", 3), ("2026-06-17", 3)])
    expected = {"2026-06-15": 4, "2026-06-16": 10, "2026-06-17": 4}
    filtered, report = audit_sessions(clean, expected_bars=expected, max_missing_bars=5)
    dates = sorted(pd.to_datetime(filtered["timestamp"]).dt.date.astype(str).unique())
    assert dates == ["2026-06-15", "2026-06-17"]
    assert report["sessions_audited"] == 3
    assert report["sessions_excluded"] == [
        {"date": "2026-06-16", "bars": 3, "expected": 10, "missing": 7, "reason": "incomplete_session"}
    ]
    assert report["incomplete_sessions_kept"] == [
        {"date": "2026-06-17", "bars": 3, "expected": 4, "missing": 1}
    ]


def test_audit_sessions_excludes_dates_missing_from_calendar() -> None:
    clean = _session_frame([("2026-06-15", 2), ("2026-06-16", 2)])
    expected = {"2026-06-15": 2}
    filtered, report = audit_sessions(clean, expected_bars=expected, max_missing_bars=5)
    dates = sorted(pd.to_datetime(filtered["timestamp"]).dt.date.astype(str).unique())
    assert dates == ["2026-06-15"]
    assert report["sessions_excluded"][0]["reason"] == "not_in_exchange_calendar"
