from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd

from scripts import liquidity_sweep_scanner as scanner


ET = ZoneInfo("America/New_York")


def _bars(direction: str = "bullish") -> pd.DataFrame:
    index = pd.date_range("2026-08-11 09:30", periods=75, freq="1min", tz=ET)
    frame = pd.DataFrame({
        "Open": [105.0] * len(index),
        "High": [105.1] * len(index),
        "Low": [104.9] * len(index),
        "Close": [105.0] * len(index),
        "Volume": [100.0] * len(index),
    }, index=index)
    sweep_index = 6
    frame.iloc[sweep_index, frame.columns.get_loc("Volume")] = 220.0
    if direction == "bullish":
        frame.iloc[sweep_index, frame.columns.get_loc("Low")] = 99.95
        frame.iloc[sweep_index, frame.columns.get_loc("Close")] = 100.05
        frame.iloc[sweep_index + 1, frame.columns.get_loc("Close")] = 100.20
        frame.iloc[sweep_index + 2:, frame.columns.get_loc("Close")] = 100.30
        frame.iloc[sweep_index + 2:, frame.columns.get_loc("High")] = 100.40
        frame.iloc[sweep_index + 2:, frame.columns.get_loc("Low")] = 100.10
    else:
        frame.iloc[sweep_index, frame.columns.get_loc("High")] = 110.055
        frame.iloc[sweep_index, frame.columns.get_loc("Close")] = 109.95
        frame.iloc[sweep_index + 1, frame.columns.get_loc("Close")] = 109.80
        frame.iloc[sweep_index + 2:, frame.columns.get_loc("Close")] = 109.70
        frame.iloc[sweep_index + 2:, frame.columns.get_loc("High")] = 109.90
        frame.iloc[sweep_index + 2:, frame.columns.get_loc("Low")] = 109.60
    return frame


def test_detects_point_in_time_bullish_failed_breakout_proxy() -> None:
    events = scanner.detect_sweeps(
        _bars(), symbol="SPY", session_date=date(2026, 8, 11), levels={"PDL": 100.0}
    )

    assert len(events) == 1
    event = events[0]
    assert event.direction == "bullish"
    assert event.level == "PDL"
    assert event.event_at == "2026-08-11T13:36:00+00:00"
    assert event.available_at == "2026-08-11T13:37:00+00:00"
    assert event.volume_ratio == 2.2
    assert event.forward_returns_bps["5m"] is not None
    assert event.point_in_time is True


def test_detector_requires_confirmation_available_as_of() -> None:
    bars = _bars()
    before_confirmation = scanner.detect_sweeps(
        bars,
        symbol="SPY",
        session_date=date(2026, 8, 11),
        levels={"PDL": 100.0},
        as_of=datetime(2026, 8, 11, 9, 36, tzinfo=ET),
    )
    after_confirmation = scanner.detect_sweeps(
        bars,
        symbol="SPY",
        session_date=date(2026, 8, 11),
        levels={"PDL": 100.0},
        as_of=datetime(2026, 8, 11, 9, 37, tzinfo=ET),
    )

    assert before_confirmation == []
    assert len(after_confirmation) == 1
    assert all(value is None for value in after_confirmation[0].forward_returns_bps.values())


def test_detects_bearish_pdh_proxy() -> None:
    events = scanner.detect_sweeps(
        _bars("bearish"),
        symbol="SPY",
        session_date=date(2026, 8, 11),
        levels={"PDH": 110.0},
    )

    assert len(events) == 1
    assert events[0].direction == "bearish"
    assert events[0].mfe_bps_60m is not None
    assert events[0].mae_bps_60m is not None


def test_ledger_upsert_is_idempotent_and_refreshes_labels(tmp_path) -> None:
    event = scanner.detect_sweeps(
        _bars(), symbol="SPY", session_date=date(2026, 8, 11), levels={"PDL": 100.0}
    )[0]
    path = tmp_path / "events.jsonl"

    assert scanner._upsert_ledger(path, [event]) == 1
    refreshed = replace(event, forward_returns_bps={"5m": 12.0, "15m": None, "30m": None, "60m": None})
    assert scanner._upsert_ledger(path, [refreshed]) == 0

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    assert records[0]["forward_returns_bps"]["5m"] == 12.0


def test_research_context_has_no_execution_or_veto_authority() -> None:
    event = scanner.detect_sweeps(
        _bars(), symbol="SPY", session_date=date(2026, 8, 11), levels={"PDL": 100.0}
    )[0]

    context = scanner.research_context("SPY", events=[event])

    assert context["promotion_status"] == "research_only"
    assert context["execution_authority"] is False
    assert context["can_submit_orders"] is False
    assert context["veto"] is False


def test_latest_context_is_freshness_checked_and_requires_no_network(tmp_path) -> None:
    path = tmp_path / "context.json"
    context = scanner.research_context(
        "SPY", events=[], as_of=datetime.fromisoformat("2026-08-11T13:43:00+00:00")
    )
    path.write_text(json.dumps({
        "session_date": "2026-08-11",
        "generated_at": "2026-08-11T13:43:00+00:00",
        "research_context": context,
    }), encoding="utf-8")

    fresh = scanner.latest_research_context(
        "SPY", path=path, as_of=datetime.fromisoformat("2026-08-11T13:45:00+00:00")
    )
    stale = scanner.latest_research_context(
        "SPY", path=path, as_of=datetime.fromisoformat("2026-08-11T20:00:00+00:00")
    )

    assert fresh["status"] == "available"
    assert fresh["cache_age_minutes"] == 2.0
    assert stale["status"] == "unavailable"
    assert stale["reason"] == "cached_context_stale"


def test_condor_integration_cannot_restore_unvalidated_hard_veto() -> None:
    source = (scanner.ROOT / "strategies" / "spy_iron_condor.py").read_text(encoding="utf-8")

    assert "liquidity_sweep_veto" not in source
    assert "no_bearish_sweep" not in source
    assert "liquidity_sweep_context=sweep_context" in source


def test_credit_spread_bots_record_proxy_without_promoting_it_to_gate() -> None:
    pm_source = (scanner.ROOT / "strategies" / "spy_0dte_pm_spread.py").read_text(encoding="utf-8")

    assert "liquidity_sweep_context=sweep_ctx" in pm_source
    assert 'gates["liquidity_sweep' not in pm_source
