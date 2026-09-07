from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.chart_aligned_shadow_learning import align_signal_to_chart, build_bplus_upgrade_nominations


UTC = timezone.utc


def _signal(**overrides):
    value = {
        "signal_id": "s1", "symbol": "QQQ", "setup": "vwap_reclaim",
        "family_key": "vwap_reclaim", "grade": "B+", "direction": "LONG",
        "entry": 100.0, "stop": 99.0, "target": 102.0,
        "signal_available_at": "2026-09-04T14:02:20Z",
        "delivered_at": "2026-09-04T14:04:20Z",
        "regime_bucket": {"trend": "up", "session": "open"},
    }
    value.update(overrides)
    return value


def _bars(count=12, *, start=datetime(2026, 9, 4, 13, 58, tzinfo=UTC)):
    rows = []
    for index in range(count):
        close = 99.5 + index * 0.2
        rows.append({"t": (start + timedelta(minutes=index)).isoformat(), "o": close - 0.1, "h": close + 0.3, "l": close - 0.3, "c": close, "v": 100 + index})
    return rows


def test_alignment_separates_signal_opportunity_from_delivery_capture():
    result = align_signal_to_chart(_signal(), _bars(), provider="alpaca_sip", horizon_bars=4)
    assert result["status"] == "scored"
    assert result["latency_seconds"] == 120.0
    assert result["signal_entry_boundary"] == "2026-09-04T14:03:00Z"
    assert result["delivery_entry_boundary"] == "2026-09-04T14:05:00Z"
    assert result["signal_path"]["entry_at"] < result["delivery_path"]["entry_at"]
    assert result["latency_edge_decay_r"] > 0
    assert 0 <= result["opportunity_capture"] <= 1
    assert result["pre_signal_features"]["feature_cutoff_at"] <= result["signal_available_at"]
    assert result["execution_enabled"] is False


def test_missing_provider_never_synthesizes_or_scores():
    result = align_signal_to_chart(_signal(), [], provider="", provider_status="missing", horizon_bars=2)
    assert result["status"] == "unavailable"
    assert result["scored"] is False
    assert result["reason"] == "provider_missing"
    assert "signal_path" not in result


def test_missing_bar_inside_horizon_is_not_scored():
    bars = _bars()
    del bars[7]
    result = align_signal_to_chart(_signal(), bars, provider="alpaca_sip", horizon_bars=3)
    assert result["status"] == "not_scored"
    assert result["reason"] == "missing_provider_bar"


def test_same_bar_target_and_stop_is_explicitly_ambiguous():
    bars = _bars()
    # First signal-eligible bar opens at entry, but its range spans both exits.
    bars[5].update({"o": 100.0, "h": 102.1, "l": 98.9, "c": 100.5})
    result = align_signal_to_chart(_signal(delivered_at="2026-09-04T14:02:30Z"), bars, provider="alpaca_sip", horizon_bars=3)
    assert result["status"] == "not_scored"
    assert result["reason"] == "same_bar_target_stop_ambiguity"
    assert result["scored"] is False


def test_terminal_event_stops_excursion_and_prevents_delivery_retrigger():
    bars = _bars()
    # The setup fills and stops before Discord's first eligible minute; a later
    # rally must not turn it into a delivery-time winner or inflate signal MFE.
    bars[5].update({"o": 100.0, "h": 100.2, "l": 98.9, "c": 99.2})
    bars[7].update({"o": 100.5, "h": 103.0, "l": 100.4, "c": 102.5})
    result = align_signal_to_chart(_signal(), bars, provider="alpaca_sip", horizon_bars=4)
    assert result["status"] == "scored"
    assert result["signal_path"]["terminal_event"] == "stop"
    assert result["signal_path"]["mfe_r"] is None
    assert result["signal_path"]["mfe_r_bounds"] == [0.0, 0.2]
    assert result["signal_path"]["mae_r"] == -1.0
    assert result["signal_path"]["excursion_identification"] == "terminal_bar_bounded"
    assert result["delivery_path"]["entry_status"] == "opportunity_expired_before_delivery"
    assert result.get("latency_edge_decay_r") is None


def test_delivery_inside_terminal_bar_is_not_ordered_from_ohlc():
    bars = _bars()
    bars[5].update({"o": 100.0, "h": 100.2, "l": 98.9, "c": 99.2})
    result = align_signal_to_chart(
        _signal(delivered_at="2026-09-04T14:03:30Z"), bars,
        provider="alpaca_sip", horizon_bars=4,
    )
    assert result["status"] == "not_scored"
    assert result["reason"] == "delivery_terminal_order_ambiguous"
    assert result["scored"] is False


def test_delivery_inside_preentry_invalidation_bar_cannot_retrigger():
    bars = _bars()
    bars[5].update({"o": 98.8, "h": 99.2, "l": 98.5, "c": 99.0})
    bars[6].update({"o": 100.1, "h": 101.0, "l": 100.0, "c": 100.8})
    result = align_signal_to_chart(
        _signal(delivered_at="2026-09-04T14:03:30Z"), bars,
        provider="alpaca_sip", horizon_bars=4,
    )
    assert result["status"] == "not_scored"
    assert result["reason"] == "delivery_terminal_order_ambiguous"


def _outcome(index: int, *, win: bool, feature: float, resolved: datetime):
    return {
        "outcome_id": f"o{index}", "signal_id": f"s{index}", "status": "scored", "scored": True,
        "grade": "B+", "family_key": "vwap_reclaim", "regime_bucket": {"trend": "up", "session": "open"},
        "signal_available_at": (resolved - timedelta(minutes=31)).isoformat(),
        "horizon_resolved_at": resolved.isoformat(),
        "pre_signal_features": {"status": "available", "feature_cutoff_at": (resolved - timedelta(minutes=32)).isoformat(), "volume_ratio": feature},
        "delivery_path": {"target_before_stop": win},
    }


def test_bplus_nomination_uses_old_training_then_forward_validation_only():
    start = datetime(2026, 9, 1, 14, tzinfo=UTC)
    rows = []
    # Training: high volume separates winners. Forward: same relationship holds.
    # Seventy observations leave 21 in the chronological validation segment,
    # including at least ten that satisfy the candidate rule.  A six-row
    # winning slice is deliberately not enough to nominate a grade change.
    for index in range(70):
        high = index % 2 == 0
        rows.append(_outcome(index, win=high, feature=2.0 if high else 0.5, resolved=start + timedelta(minutes=index)))
    report = build_bplus_upgrade_nominations(rows, as_of=start + timedelta(minutes=60))
    nomination = report["nominations"][0]
    assert nomination["action"] == "nominate_bplus_to_aplus_shadow_rule_review"
    assert nomination["proposed_shadow_rule"]["feature"] == "volume_ratio"
    # The as-of cutoff excludes rows 61-69, leaving 61 causal observations.
    assert nomination["chronological_evidence"]["training_size"] == 42
    assert nomination["chronological_evidence"]["forward_size"] == 19
    assert nomination["automatic_parameter_changes"] is False
    assert nomination["promotion_status"] == "human_review_required"


def test_future_outcomes_and_post_signal_features_are_rejected_for_leakage():
    start = datetime(2026, 9, 1, 14, tzinfo=UTC)
    rows = [_outcome(index, win=True, feature=2.0, resolved=start + timedelta(minutes=index)) for index in range(30)]
    rows[0]["pre_signal_features"]["feature_cutoff_at"] = rows[0]["horizon_resolved_at"]
    report = build_bplus_upgrade_nominations(rows, as_of=start + timedelta(minutes=15))
    assert report["nominations"] == []
    assert report["excluded_counts"]["feature_leakage_or_missing_cutoff"] == 1
    assert report["excluded_counts"]["not_resolved_as_of_cutoff"] == 14


def test_family_and_regime_cohorts_are_never_pooled():
    start = datetime(2026, 9, 1, 14, tzinfo=UTC)
    rows = [_outcome(index, win=True, feature=2.0, resolved=start + timedelta(minutes=index)) for index in range(15)]
    rows += [{**_outcome(index + 15, win=True, feature=2.0, resolved=start + timedelta(minutes=index + 15)), "family_key": "orb_breakout"} for index in range(15)]
    report = build_bplus_upgrade_nominations(rows, as_of=start + timedelta(minutes=60))
    assert report["nominations"] == []
    assert {row["sample_size"] for row in report["cohorts"]} == {15}
    assert all(row["status"] == "insufficient_data" for row in report["cohorts"])
