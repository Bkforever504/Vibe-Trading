from datetime import datetime, timezone
from scripts import aplus_spotlight, continuous_improvement_scorecard, outcome_science_report, simple_price_action_alerts


def test_all_alert_review_modules_start_after_delivery_not_signal_bar() -> None:
    alert = {"bar_completed_at": "2026-09-04T14:00:00Z", "delivered_at": "2026-09-04T14:03:20Z"}
    expected = datetime(2026, 9, 4, 14, 4, tzinfo=timezone.utc)
    for module in (aplus_spotlight, simple_price_action_alerts, continuous_improvement_scorecard, outcome_science_report):
        assert module.first_complete_bar_after_delivery(alert) == expected
