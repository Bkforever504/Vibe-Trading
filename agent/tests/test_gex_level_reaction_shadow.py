from __future__ import annotations

from datetime import datetime, timezone

from research.gex_level_reaction_lab import build_report
from scripts.gex_level_reaction_shadow import ReactionConfig, detect_reactions, validate_snapshot


NOW = datetime(2026, 8, 19, 16, 0, tzinfo=timezone.utc)


def _snapshot(**updates) -> dict:
    value = {
        "status": "ok", "symbol": "SPY", "timestamp": "2026-08-19T15:00:00Z",
        "data_source": "test", "point_in_time": True, "expiry_filter": "0dte",
        "size_source": "open_interest", "open_interest_coverage": 0.9,
        "dealer_positioning_observed": False,
        "levels": [{"strike": 100.0, "gex": 1000.0, "rank": 1}],
        "max_snapshot_age_hours": 8.0,
    }
    value.update(updates)
    return value


def _bar(minute: int, o: float, h: float, low: float, c: float, volume: float = 100) -> dict:
    return {
        "timestamp": f"2026-08-19T15:{minute:02d}:00Z", "open": o, "high": h,
        "low": low, "close": c, "volume": volume,
    }


def test_snapshot_requires_exact_0dte_open_interest() -> None:
    assert validate_snapshot(_snapshot(), now=NOW) == (True, "ok")
    assert validate_snapshot(_snapshot(expiry_filter="shortest_available"), now=NOW)[1] == "requires_exact_0dte"
    assert validate_snapshot(_snapshot(size_source="quote_size"), now=NOW)[1] == "requires_open_interest"


def test_snapshot_requires_point_in_time_and_freshness() -> None:
    assert validate_snapshot(_snapshot(point_in_time=False), now=NOW)[1] == "point_in_time_not_attested"
    stale = _snapshot(timestamp="2026-08-18T15:00:00Z")
    assert validate_snapshot(stale, now=NOW)[1] == "snapshot_stale"


def test_detects_causal_rejection_from_below() -> None:
    bars = [
        _bar(5, 99.0, 99.4, 98.9, 99.2),
        _bar(10, 99.2, 100.1, 99.1, 99.7),
        _bar(15, 99.7, 99.8, 99.1, 99.3, 150),
        _bar(20, 99.2, 99.3, 98.5, 98.7),
        _bar(25, 98.7, 98.8, 98.0, 98.1),
    ]
    events = detect_reactions(bars, _snapshot(), config=ReactionConfig(min_volume_ratio=1.0))
    assert len(events) == 1
    assert events[0]["sequence"] == "rejection_from_below"
    assert events[0]["direction"] == -1
    assert events[0]["outcome"]["entry_timestamp"].endswith("15:20:00Z")


def test_detects_accepted_break_and_retest() -> None:
    bars = [
        _bar(5, 99.0, 99.4, 98.9, 99.2),
        _bar(10, 99.2, 100.8, 99.2, 100.6),
        _bar(15, 100.6, 100.9, 100.1, 100.5, 150),
        _bar(20, 100.6, 101.3, 100.5, 101.1),
        _bar(25, 101.1, 102.0, 101.0, 101.8),
    ]
    events = detect_reactions(bars, _snapshot())
    assert len(events) == 1
    assert events[0]["sequence"] == "accepted_break_up"
    assert events[0]["direction"] == 1


def test_pre_snapshot_bars_cannot_create_event() -> None:
    bars = [
        {**_bar(5, 99.0, 100.1, 98.9, 99.7), "timestamp": "2026-08-19T14:55:00Z"},
        _bar(5, 99.7, 99.8, 99.1, 99.3),
        _bar(10, 99.3, 99.4, 98.8, 99.0),
    ]
    assert detect_reactions(bars, _snapshot()) == []


def test_report_never_promotes_execution() -> None:
    rows = []
    for i in range(30):
        for rank in (1, 2):
            rows.append({
                "symbol": "SPY", "level_rank": rank, "sequence": "rejection_from_below",
                "confirmation_timestamp": f"2026-07-{(i % 25) + 1:02d}T15:00:00Z",
                "outcome": {"status": "resolved", "gross_r": 0.5 if rank == 1 else 0.1},
            })
    report = build_report(rows)
    assert report["review_gate"]["eligible"] is True
    assert report["review_gate"]["promotion_allowed"] is False
    assert report["execution_enabled"] is False
