from datetime import datetime
from zoneinfo import ZoneInfo
from scripts.premarket_thesis_shadow import build_report

ET = ZoneInfo("America/New_York")


def test_verified_put_print_without_nbbo_quotes_is_not_a_directional_thesis() -> None:
    report = build_report(
        radar={"high_priority": [{"symbol": "SPY", "gap_pct": 0.4}]},
        nbbo_rows=[{"symbol": "SPY260904P00769000", "record_type": "trade", "premium": 75000.0, "observed_at": "2026-09-04T12:30:00Z", "verified": True, "provider": "test", "trade_id": "test-1"}],
        now_et=datetime(2026, 9, 4, 8, 30, tzinfo=ET),
    )
    assert report["status"] == "missing"
    assert len(report["theses"]) == 3
    assert {row["direction"] for row in report["theses"]} == {"NO_BIAS"}
    assert report["theses"][0]["conviction"] == "low"
    assert report["theses"][0]["state"] == "OBSERVE"


def test_missing_trade_print_feed_is_explicit_and_never_fabricated_from_quotes() -> None:
    report = build_report(radar={"observations": [{"symbol": "SPY", "gap_pct": -1.0}]}, nbbo_rows=[{"symbol": "SPY260904P00769000", "bid": 1.0, "ask": 1.1}], now_et=datetime(2026, 9, 4, 8, 30, tzinfo=ET))
    assert report["status"] == "missing"
    assert len(report["theses"]) == 3
    assert report["reason"] == "fresh_verified_opra_nbbo_unavailable"
    assert report["execution_enabled"] is False


def test_stale_unverified_and_future_prints_cannot_form_thesis():
    base = {"symbol": "SPY260904P00769000", "record_type": "trade", "premium": 75000, "verified": True, "provider": "test", "trade_id": "test-1"}
    for changes in ({"observed_at": "2026-09-03T12:30:00Z"}, {"observed_at": "2026-09-04T12:31:00Z"}, {"observed_at": "2026-09-04T12:30:00Z", "verified": False}):
        report = build_report(radar={}, nbbo_rows=[{**base, **changes}], now_et=datetime(2026, 9, 4, 8, 30, tzinfo=ET))
        assert report["status"] == "missing"
        assert {row["direction"] for row in report["theses"]} == {"NO_BIAS"}
