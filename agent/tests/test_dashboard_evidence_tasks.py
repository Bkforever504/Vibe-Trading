from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_evidence_runners_are_read_only_weekday_guarded_and_fail_visible() -> None:
    post_close = (ROOT / "scripts" / "run_dashboard_evidence_chain.ps1").read_text(encoding="utf-8")
    intraday = (ROOT / "scripts" / "run_dashboard_intraday_evidence.ps1").read_text(encoding="utf-8")

    for body in (post_close, intraday):
        assert 'DayOfWeek -in @("Saturday", "Sunday")' in body
        assert "execution_enabled=false can_submit_orders=false" in body
        assert "pattern_grader_scanner.py" not in body
        assert "submit_order(" not in body
    assert "build_move_ground_truth.py" not in post_close
    assert "VibeTradingMoveGroundTruth" in post_close
    assert "detection_scorecard.py" in post_close
    assert "daily_aplus_review.py" in post_close
    assert "broker_fill_observer.py" in intraday
    assert "options_feed_qualification.py" in intraday
    assert "dashboard_readiness.py" in intraday


def test_scheduler_uses_limited_native_tasks_without_credentials() -> None:
    body = (ROOT / "scripts" / "register_dashboard_evidence_tasks.ps1").read_text(encoding="utf-8")

    assert "VibeTradingDashboardEvidenceIntraday" in body
    assert "VibeTradingDashboardEvidencePostClose" in body
    assert '"/RL", "LIMITED"' in body
    assert '"/RI", "15"' in body
    assert '"MON,TUE,WED,THU,FRI"' in body
    assert "API_KEY" not in body
    assert "SECRET" not in body
