from scripts.post_delivery_grade_calibrator import build_report


def _outcomes(count=30, trend="down", wins=10):
    return [{"outcome_id": f"{trend}-{i}", "calibration_eligible": True, "delivery_timestamp_quality": "exact", "session_date": "2026-09-04", "status": "evaluated", "setup": "vwap_reject", "grade": "B+", "symbol": "QQQ", "outcome_r": 1.0 if i < wins else -1.0, "regime_bucket": {"vix_bucket": "15-20", "trend_bucket": trend, "session_slot": "1000-1100", "day_of_week": "FRI"}} for i in range(count)]


def test_thirty_weak_bplus_post_delivery_outcomes_nominate_tightening_only() -> None:
    outcomes = _outcomes()
    report = build_report(outcomes)
    nomination = report["nominations"][0]
    assert nomination["action"] == "nominate_grade_tightening_review"
    assert nomination["current"]["post_delivery_hit_rate"] == 0.3333
    assert nomination["automatic_parameter_changes"] is False
    assert report["human_review_required"] is True


def test_duplicate_deliveries_cannot_reach_minimum_sample():
    report = build_report(_outcomes(10) * 3)
    assert report["nominations"] == []
    assert report["excluded_counts"]["duplicate"] == 20


def test_unknown_regime_never_becomes_a_pooled_nomination():
    rows = _outcomes()
    for row in rows:
        row["regime_bucket"]["vix_bucket"] = "missing"
    report = build_report(rows)
    assert report["nominations"] == []
    assert report["excluded_counts"]["missing_regime_evidence"] == 30


def test_opposite_regime_results_remain_separate_human_nominations():
    report = build_report(_outcomes(trend="up", wins=25) + _outcomes(trend="down"))
    routing = {row["regime_bucket"]["trend_bucket"]: row["proposed_routing"] for row in report["nominations"]}
    assert routing == {"up": "discord", "down": "dashboard_only"}
    assert all(row["promotion_status"] == "human_review_required" for row in report["nominations"])


def test_legacy_unverified_delivery_cannot_train():
    rows = _outcomes()
    for row in rows:
        row["delivery_timestamp_quality"] = "attempt_only"
    assert build_report(rows)["nominations"] == []
