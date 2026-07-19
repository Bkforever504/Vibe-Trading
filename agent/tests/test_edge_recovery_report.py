from scripts import edge_recovery_report as report


def _trade(day: str, pnl: float, confidence: float | None = 9.0, *, structured: bool = False, consensus: str | None = None) -> dict:
    row = {
        "id": f"{day}-{pnl}",
        "status": "closed",
        "entry_date": day,
        "pnl": pnl,
        "catalyst": f"VWAP trend {confidence}/10" if confidence is not None else "gap",
    }
    if structured and confidence is not None:
        row["entry_quality"] = {"feature_snapshot": {"confidence": confidence}}
    if consensus:
        row["shadow_consensus"] = {"recommendation": consensus, "blockers": ["market_force_unclear", "adaptive_stand_aside"]}
    return row


def test_extract_confidence_prefers_structured_snapshot() -> None:
    value, source = report.extract_confidence({
        "catalyst": "trend 8/10",
        "entry_quality": {"feature_snapshot": {"confidence": 9.5}},
    })
    assert value == 9.5
    assert source == "structured_entry_snapshot"


def test_saturated_confidence_fails_discrimination_and_calibration() -> None:
    result = report.calibration_summary([0.9] * 4, [1, 1, 0, 0])
    assert result["unique_prediction_count"] == 1
    assert result["discrimination_status"] == "unmeasurable_saturated_score"
    assert result["status"] == "not_calibrated"
    assert result["brier_skill_vs_constant_base_rate"] < 0


def test_split_at_profit_peak_separates_green_stretch_from_decay() -> None:
    trades = [_trade("2026-06-29", 100), _trade("2026-06-30", 100), _trade("2026-07-01", -25), _trade("2026-07-02", -25)]
    early, recent, metadata = report.split_at_profit_peak(trades)
    assert len(early) == 2
    assert len(recent) == 2
    assert metadata["peak_cumulative_pnl"] == 200


def test_build_report_keeps_pre_hardening_separate_and_marks_counterfactual_small() -> None:
    trades = [
        _trade("2026-06-23", -1000, None),
        _trade("2026-06-29", 100),
        _trade("2026-07-01", -30, structured=True, consensus="stand_aside"),
    ]
    missed = {"evaluations": [{
        "outcome_status": "observed",
        "direction": "bull",
        "reason": "score_below_minimum",
        "directional_end_move_pct": -0.2,
        "max_favorable_underlying_pct": 0.1,
        "max_adverse_underlying_pct": 0.3,
    }]}
    result = report.build_report(trades, missed)
    assert result["all_closed_trade_stats"]["trade_count"] == 3
    assert result["post_hardening_trade_stats"]["trade_count"] == 2
    veto = result["consensus_veto_counterfactual"]
    assert veto["strict_veto_counterfactual_pnl_delta"] == 30
    assert veto["evidence_status"] == "insufficient_for_authority"
    proxy = result["blocked_trade_proxy"]["reason_summaries"][0]
    assert proxy["blocked_direction_finished_adverse"] == 1
    assert result["can_submit_orders"] is False
