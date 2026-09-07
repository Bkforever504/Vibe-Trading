from datetime import datetime, timedelta, timezone

from scripts.shadow_alert_intelligence import (
    adaptive_conformal_abstention,
    anytime_bounded_mean_interval,
    build_action_deadline,
    diversify_discord_queue,
    estimate_alert_half_life,
    event_intensity_challenger,
    schedule_by_action_deadline,
    market_data_quorum,
)


NOW = datetime(2026, 9, 6, 15, 0, tzinfo=timezone.utc)


def test_half_life_is_chronological_and_falls_back_when_underpowered():
    rows = [
        {"setup_family": "orb", "regime": "open", "resolved_at": (NOW - timedelta(days=1)).isoformat(), "valid_for_seconds": value}
        for value in range(40, 80)
    ]
    rows.append({"setup_family": "orb", "regime": "open", "resolved_at": (NOW + timedelta(days=1)).isoformat(), "valid_for_seconds": 9999})
    result = estimate_alert_half_life(rows, setup_family="orb", regime="open", as_of=NOW)
    assert result["status"] == "estimated"
    assert result["future_rows_rejected"] == 1
    assert result["half_life_seconds"] < 100
    assert result["execution_enabled"] is False
    fallback = estimate_alert_half_life(rows[:2], setup_family="orb", regime="open", as_of=NOW)
    assert fallback["status"] == "insufficient_data"
    assert fallback["conservative_validity_seconds"] == 180


def test_deadline_never_bypasses_upstream_blockers():
    half_life = {"conservative_validity_seconds": 60}
    candidate = {"bar_completed_at": (NOW - timedelta(seconds=10)).isoformat(), "blockers": ["spread_too_wide"]}
    result = build_action_deadline(candidate, half_life, now=NOW)
    assert result["status"] == "blocked_upstream"
    assert result["do_not_page_reason"] == "upstream_blocker"


def test_conformal_layer_can_only_retain_or_abstain_and_rejects_future_rows():
    rows = [
        {"resolved_at": (NOW - timedelta(minutes=i + 1)).isoformat(), "prediction": 0.7, "actual": 0.68}
        for i in range(35)
    ]
    rows.append({"resolved_at": (NOW + timedelta(minutes=1)).isoformat(), "prediction": 0.0, "actual": 1.0})
    retained = adaptive_conformal_abstention(0.75, rows, as_of=NOW, economic_threshold=0.6)
    assert retained["decision"] == "RETAIN"
    assert retained["future_rows_rejected"] == 1
    assert "UPGRADE" not in str(retained)
    abstained = adaptive_conformal_abstention(0.59, rows, as_of=NOW, economic_threshold=0.6)
    assert abstained["decision"] == "ABSTAIN"
    assert abstained["execution_enabled"] is False


def test_diversification_reserves_core_and_avoids_redundant_second_slot():
    rows = [
        {"candidate_id": "spy", "symbol": "SPY", "utility_score": 95, "exposure_vector": {"market": 1, "tech": 0}},
        {"candidate_id": "qqq", "symbol": "QQQ", "utility_score": 94, "exposure_vector": {"market": 1, "tech": 0.9}},
        {"candidate_id": "xom", "symbol": "XOM", "utility_score": 82, "exposure_vector": {"market": 0.2, "energy": 1}},
    ]
    result = diversify_discord_queue(rows, capacity=2, reserved_symbols=("SPY",))
    assert [row["symbol"] for row in result["selected"]] == ["SPY", "XOM"]
    assert result["all_candidates_retained"] == rows
    assert result["can_submit_orders"] is False


def test_event_intensity_requires_multiple_persistent_channels():
    result = event_intensity_challenger(
        {"aggressive_trades": 30, "quote_changes": 25, "cancels": 4},
        {"aggressive_trades": 10, "quote_changes": 10, "cancels": 5},
        persistence_windows=2,
    )
    assert result["state"] == "ACCELERATING"
    assert result["authority"].startswith("challenger_context_only")


def test_anytime_interval_is_bounded_and_never_promotes():
    result = anytime_bounded_mean_interval([1.0] * 100)
    assert 0 <= result["lower"] <= result["upper"] <= 1
    assert result["automatic_promotion"] is False
    assert anytime_bounded_mean_interval([1.2])["status"] == "unavailable"


def test_deadline_scheduler_prioritizes_expiring_usable_opportunity():
    rows = [
        {"candidate_id": "later", "utility_score": 99, "blockers": [], "alert_deadline_shadow": {"status": "actionable", "action_deadline_ts": (NOW + timedelta(seconds=90)).isoformat()}},
        {"candidate_id": "sooner", "utility_score": 80, "blockers": [], "alert_deadline_shadow": {"status": "actionable", "action_deadline_ts": (NOW + timedelta(seconds=30)).isoformat()}},
        {"candidate_id": "blocked", "utility_score": 100, "blockers": ["spread"], "alert_deadline_shadow": {"status": "actionable", "action_deadline_ts": (NOW + timedelta(seconds=1)).isoformat()}},
    ]
    result = schedule_by_action_deadline(rows, capacity=2)
    assert [row["candidate_id"] for row in result["selected"]] == ["sooner", "later"]
    assert result["automatic_dispatch"] is False


def test_market_data_quorum_requires_independent_fresh_agreement():
    observations = [
        {"source": "alpaca_sip", "bid": 99.99, "ask": 100.01, "event_at": NOW.isoformat()},
        {"source": "databento", "bid": 100.00, "ask": 100.02, "event_at": NOW.isoformat()},
    ]
    agreed = market_data_quorum(observations, as_of=NOW)
    assert agreed["status"] == "agreed"
    disagreed = market_data_quorum([{**observations[0]}, {**observations[1], "bid": 101, "ask": 101.02}], as_of=NOW)
    assert disagreed["status"] == "data_disagreement"
    assert market_data_quorum(observations[:1], as_of=NOW)["status"] == "unavailable"
