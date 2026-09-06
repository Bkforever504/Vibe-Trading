from datetime import date, timedelta
from scripts.execution_readiness_scorecard import build_scorecard
from scripts.signal_stack_health_report import is_expected_market_session


def _sessions(count: int, violation_index: int | None = None):
    start = date(2026, 7, 1)
    return [{"date": (start + timedelta(days=i)).isoformat(), "clean_shadow_session": True, "delivery_timestamp_evaluation": True, "order_authority_violations": 1 if i == violation_index else 0, "median_discord_latency_seconds": 5.0} for i in range(count)]


def _report(sessions):
    return build_scorecard(sessions, as_of=date.fromisoformat(sessions[-1]["date"]), chart_report={"provider": "test_post_discord_delivery", "by_grade": [{"grade": "A+", "count": 30, "positive_pct": 60.0, "median_r": 0.7}]}, nominations={"human_review_completed": True, "human_review_accepted": True}, kill_switch_drill={"status": "PASS", "end_to_end": True}, sizing_policy={"status": "PASS", "human_review_accepted": True, "enforcement_verified": True, "evidence_id": "synthetic-test-only", "max_account_risk_fraction": 0.01, "three_loss_day_multiplier": 0.5})


def test_synthetic_thirty_day_pass_is_all_pass() -> None:
    assert all(row["status"] == "PASS" for row in _report(_sessions(50))["criteria"])


def test_twenty_nine_sessions_leaves_sessions_pending() -> None:
    sessions = _sessions(50)
    market_days = [r for r in sessions if is_expected_market_session(date.fromisoformat(r["date"]))]
    sessions = [r for r in sessions if r["date"] >= market_days[-29]["date"]]
    row = next(row for row in _report(sessions)["criteria"] if row["name"] == "SESSIONS")
    assert row["status"] == "PENDING" and row["days_remaining"] == 1


def test_authority_violation_resets_consecutive_counter() -> None:
    row = next(row for row in _report(_sessions(30, violation_index=14))["criteria"] if row["name"] == "ORDER_AUTHORITY")
    assert row["status"] == "PENDING" and row["observed"] == 15


def test_missing_authority_sizing_and_grade_evidence_never_pass():
    report = build_scorecard([{"date": "2026-09-04"}], as_of=date(2026, 9, 4), chart_report={}, nominations={}, kill_switch_drill={})
    criteria = {r["name"]: r for r in report["criteria"]}
    assert criteria["ORDER_AUTHORITY"]["observed"] == 0
    assert criteria["SIZING_POLICY"]["status"] == "PENDING"
    assert criteria["TARGET_GRADE_OUTCOMES"]["status"] == "FAIL"
    assert report["execution_enabled"] is False


def test_duplicate_days_cannot_extend_streak():
    rows = _sessions(1) * 30
    assert next(r for r in _report(rows)["criteria"] if r["name"] == "ORDER_AUTHORITY")["observed"] == 1
