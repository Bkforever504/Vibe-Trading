from datetime import datetime, timezone
import pytest
from research.scanner_feed_reference_study import fetch_reference, compare


def test_historical_reference_cannot_request_live_session():
    with pytest.raises(ValueError, match='completed_delayed_session_required'):
        fetch_reference({'SPY'}, '2026-09-04', 'sip', now=datetime(2026, 9, 4, 19, tzinfo=timezone.utc))


def test_missing_reference_feed_does_not_fabricate_comparison():
    report = compare([], {'iex': {}}, now=datetime.now(timezone.utc))
    assert report['iex_to_sip_status_transitions'] == {}
    assert 'sip' not in report['status_by_feed']
    assert report['automatic_parameter_changes'] is False


def test_duplicate_saved_alert_is_not_an_independent_trial(monkeypatch):
    import research.scanner_feed_reference_study as study
    monkeypatch.setattr(study, 'evaluate_alert', lambda row, bars, now: {'status': 'evaluated' if bars else 'incomplete_bar_history'})
    result = compare([{'symbol': 'SPY'}, {'symbol': 'SPY', 'duplicate_of': 'first'}],
                     {'iex': {'SPY': []}, 'sip': {'SPY': [{'t': '2026-09-04T14:00:00Z', 'v': 10}]}}, now=datetime.now(timezone.utc))
    assert result['unique_saved_alerts'] == 1
    assert result['iex_to_sip_status_transitions'] == {'incomplete_bar_history -> evaluated': 1}
