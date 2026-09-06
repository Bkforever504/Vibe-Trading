from scripts.continuous_improvement_scorecard import build_scorecard


def _event(symbol: str, delivered: bool, detected: str = "2026-09-02T14:36:00Z") -> dict:
    return {
        "event_id": f"{symbol}-{detected}",
        "symbol": symbol,
        "state": "CONFIRMED",
        "detected_at": detected,
        "bar_completed_at": "2026-09-02T14:35:00Z",
        "discord_delivered": delivered,
    }


def test_scorecard_flags_delivery_latency_and_missing_core() -> None:
    report = build_scorecard(
        day="2026-09-02",
        alert_events=[_event("SPY", False, "2026-09-02T14:44:01Z")],
        alert_report={"generated_at": "2026-09-02T14:44:02Z", "notification_attempts": 1, "notification_failures": 1},
        coverage_history=[{"date": "2026-09-02", "summary": {"source_discovery_recall_pct": 75.0, "actionable_early_recall_pct": 25.0}}],
        scorecard_history=[],
        spy_report={"operational_health": "ok"},
        strat_report={},
    )
    assert report["daily"]["grade"] == "F"
    assert report["daily"]["late_alert_count"] == 1
    assert report["daily"]["missing_core_symbols"] == ["QQQ", "IWM"]
    assert {row["stage"] for row in report["failures"]} == {
        "delivery", "timeliness", "core_index_coverage", "discovery"
    }


def test_scorecard_can_grade_clean_session_and_compare_previous() -> None:
    events = [_event(symbol, True) for symbol in ("SPY", "QQQ", "IWM")]
    previous = {
        "date": "2026-09-01",
        "daily": {"grade": "B", "delivery_success_pct": 90.0, "p95_alert_latency_seconds": 90.0, "source_discovery_recall_pct": 95.0},
    }
    report = build_scorecard(
        day="2026-09-02",
        alert_events=events,
        alert_report={"generated_at": "2026-09-02T14:36:01Z", "notification_attempts": 3, "notification_failures": 0},
        coverage_history=[{"date": "2026-09-02", "summary": {"source_discovery_recall_pct": 100.0, "actionable_early_recall_pct": 80.0}}],
        scorecard_history=[previous],
        spy_report={"operational_health": "ok"},
        strat_report={"provider": "strat_30m_continuation_shadow"},
    )
    assert report["daily"]["grade"] == "A"
    assert report["daily"]["delivery_success_pct"] == 100.0
    assert report["change_vs_previous_session"]["delivery_success_pct_delta"] == 10.0
    assert report["change_vs_previous_session"]["discovery_recall_pct_delta"] == 5.0
    assert not report["failures"]
