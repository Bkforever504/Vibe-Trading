from datetime import datetime, timezone

from scripts import institutional_confluence_shadow as confluence


def _event(timestamp: str, direction: str = "LONG") -> dict:
    return {
        "symbol": "SPY", "direction": direction, "state": "CONFIRMED",
        "bar_completed_at": timestamp, "trigger": 100, "stop": 99, "target": 102,
    }


def test_repeat_confirmation_requires_same_direction_unique_bars_and_span():
    candidate = _event("2026-09-03T14:40:00Z")
    events = [
        _event("2026-09-03T14:30:00Z"),
        _event("2026-09-03T14:35:00Z"),
        _event("2026-09-03T14:40:00Z"),
        _event("2026-09-03T14:40:00Z"),
        _event("2026-09-03T14:35:00Z", "SHORT"),
    ]
    result = confluence.repeat_confirmation(events, candidate)
    assert result["count"] == 3
    assert result["span_minutes"] == 10.0
    assert result["qualifies"] is True
    assert result["independent_source"] is False


def test_missing_institutional_feeds_are_visible_and_never_inferred():
    candidate = _event("2026-09-03T14:40:00Z")
    report = confluence.build_report(
        as_of=datetime(2026, 9, 3, 14, 41, tzinfo=timezone.utc),
        alerts={"recent_events": [candidate]},
        gex_rows=[{
            "timestamp": "2026-09-03T13:35:00Z",
            "scans": [{"symbol": "SPY", "status": "unavailable", "error": "insufficient open interest coverage", "open_interest_coverage": 0.0}],
        }],
        czt={"snapshots": [{"symbol": "SPY", "as_of": "2026-09-03T14:39:00Z", "czt_aligned": True, "shadow_direction": "call"}]},
    )
    card = report["cards"][0]
    assert card["recommendation"] == "insufficient_independent_evidence"
    assert card["independent_sources_available"] == 0
    assert card["alert_visibility_preserved"] is True
    assert report["execution_enabled"] is False
    by_name = {source["name"]: source for source in card["sources"]}
    assert by_name["gamma_open_interest_proxy"]["available"] is False
    assert by_name["nbbo_options_flow"]["reason"] == "missing"
    assert by_name["dark_pool_prints"]["available"] is False
    assert by_name["ohlcv_condition_zone_trigger_proxy"]["independent_source"] is False


def test_stale_gex_is_excluded_from_independent_source_count():
    candidate = _event("2026-09-03T20:00:00Z")
    report = confluence.build_report(
        as_of=datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc),
        alerts={"recent_events": [candidate]},
        gex_rows=[{
            "timestamp": "2026-09-03T10:00:00Z",
            "scans": [{"symbol": "SPY", "status": "ok", "gex_wall": {"strike": 100}}],
        }],
        czt={},
    )
    assert report["cards"][0]["independent_sources_available"] == 0
    assert report["cards"][0]["sources"][0]["fresh"] is False
