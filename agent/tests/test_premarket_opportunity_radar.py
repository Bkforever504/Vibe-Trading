from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from scripts.premarket_opportunity_radar import build_report, evaluate_candidate, lane_for_gap, premarket_features, send_watch_alerts


def _metrics(gap: float, spread: float = 0.001) -> dict:
    return {"gap_return": gap, "price": 100.0, "spread_pct": spread}


def _deep() -> dict:
    return {"avg_dollar_volume_20d": 500_000_000}


def test_gap_lanes_are_separate() -> None:
    assert lane_for_gap(0.08) == "event_gap"
    assert lane_for_gap(-0.03) == "momentum_gap"
    assert lane_for_gap(0.01) == "tactical_gap"
    assert lane_for_gap(0.004) is None


def test_event_gap_can_be_high_priority_without_social_authority() -> None:
    row = evaluate_candidate("MRNA", _metrics(0.84), {"premarket_rvol": 5.0}, _deep(), [], 0.01)
    assert row["priority"] == "high"
    assert row["routed_shadow_playbook"] == "event_gap_continuation_shadow"
    assert row["execution_enabled"] is False and row["can_submit_orders"] is False


def test_exceptional_catalyst_gap_alerts_even_when_rvol_is_unavailable() -> None:
    news = [{"headline": "Company reports pivotal Phase 3 success"}]
    row = evaluate_candidate("MRNA", _metrics(0.90, 0.013), {"premarket_rvol": None}, _deep(), news, 0.02)
    assert row["state"] == "exceptional_event_watch"
    assert row["priority"] == "high"
    assert row["alertable"] is True
    assert row["hard_gates"]["same_time_premarket_rvol"] is False
    assert row["paper_signal_eligible"] is False


def test_momentum_gap_requires_catalyst_or_sector_confirmation() -> None:
    blocked = evaluate_candidate("AAPL", _metrics(0.03), {"premarket_rvol": 2.0}, _deep(), [], -0.01)
    assert blocked["priority"] == "observe"
    news = [{"headline": "Apple announces a product"}]
    ready = evaluate_candidate("AAPL", _metrics(0.03), {"premarket_rvol": 2.0}, _deep(), news, 0.003)
    assert ready["priority"] == "high"


def test_missing_liquidity_or_spread_fails_closed() -> None:
    row = evaluate_candidate("XYZ", _metrics(0.10, 0.02), {"premarket_rvol": 10.0}, {}, [], None)
    assert row["priority"] == "observe"
    assert row["hard_gates"]["historical_dollar_liquidity"] is False
    assert row["hard_gates"]["executable_underlying_spread"] is False


def test_premarket_rvol_uses_same_time_prior_sessions() -> None:
    zone = ZoneInfo("America/New_York")
    index = pd.to_datetime(["2026-08-17 04:00", "2026-08-17 04:05", "2026-08-18 04:00", "2026-08-18 04:05", "2026-08-19 04:00", "2026-08-19 04:05"]).tz_localize(zone)
    frame = pd.DataFrame({"open": [10] * 6, "high": [11] * 6, "low": [9] * 6, "close": [10] * 6, "volume": [100, 100, 200, 200, 900, 900]}, index=index)
    result = premarket_features(frame, datetime(2026, 8, 19, 4, 6, tzinfo=zone))
    assert result["same_time_median_volume"] == 300
    assert result["premarket_rvol"] == 6.0


def test_alerts_are_deduplicated(tmp_path: Path) -> None:
    messages: list[str] = []
    report = {"date": "2026-08-19", "generated_at": "2026-08-19T12:00:00Z", "observations": [{"symbol": "MRNA", "lane": "event_gap", "direction": "bull", "priority": "high", "alertable": True, "score": 9, "gap_pct": 84.0, "premarket_rvol": 8.0, "sector_etf": "XBI", "sector_confirmed": True, "routed_shadow_playbook": "event_gap_continuation_shadow", "catalyst_headlines": []}]}
    sender = lambda message: messages.append(message) is None
    state = tmp_path / "state.json"
    assert send_watch_alerts(report, state_path=state, sender=sender) == 1
    assert send_watch_alerts(report, state_path=state, sender=sender) == 0
    assert len(messages) == 1


def test_outside_premarket_window_does_not_scan() -> None:
    zone = ZoneInfo("America/New_York")
    report = build_report(now_et=datetime(2026, 8, 19, 15, 0, tzinfo=zone), symbols=["MRNA"])
    assert report["session_status"] == "outside_premarket_scan_window"
    assert report["snapshot_count"] == 0
    assert report["observations"] == []
