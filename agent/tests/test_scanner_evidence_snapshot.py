from datetime import datetime, timezone, timedelta
from scripts.scanner_evidence_snapshot import build_snapshot, persist

NOW = datetime(2026, 9, 4, 15, 0, tzinfo=timezone.utc)


def test_capture_retains_rejected_and_accepted_without_fabricating_delivery():
    inputs = {'decisions': {'generated_at': NOW.isoformat(), 'decisions': [
        {'decision': 'shadow_rejected', 'candidate': {'symbol': 'QQQ'}, 'blockers': ['consensus']},
        {'decision': 'shadow_accepted', 'candidate': {'symbol': 'SPY'}}]},
        'delivery': {'generated_at': NOW.isoformat(), 'quality_checks': [{'eligible': False, 'reasons': ['quote_stale_or_future']}]}}
    snapshot = build_snapshot(inputs, {'code': 'abc'}, now=NOW)
    assert snapshot['summary']['rejected_decisions'] == 1
    assert snapshot['summary']['accepted_decisions'] == 1
    assert snapshot['summary']['quote_gate_checks'] == 1
    assert 'delivered_at' not in snapshot['artifacts']['decisions']['decisions'][0]
    assert snapshot['source_provenance']['radar']['status'] == 'missing'


def test_snapshot_is_idempotent_but_configuration_changes_are_separate(tmp_path):
    original = build_snapshot({}, {'code': 'abc'}, now=NOW)
    rerun = build_snapshot({}, {'code': 'abc'}, now=NOW + timedelta(seconds=1))
    changed = build_snapshot({}, {'code': 'def'}, now=NOW)
    assert original['snapshot_id'] == rerun['snapshot_id']
    assert persist(original, tmp_path)
    assert not persist(rerun, tmp_path)
    assert persist(changed, tmp_path)


def test_old_or_unsafe_reports_do_not_become_fresh_training_evidence():
    snapshot = build_snapshot({'decisions': {'generated_at': '2026-09-03T15:00:00Z'},
                               'delivery': {'execution_enabled': True}}, {}, now=NOW)
    assert snapshot['source_provenance']['decisions']['capture_timing'] == 'late_or_unknown'
    assert snapshot['source_provenance']['delivery']['status'] == 'authority_contract_invalid'
    assert 'delivery' not in snapshot['artifacts']
    assert snapshot['execution_enabled'] is False


def test_canonical_event_envelope_preserves_event_and_receipt_time_for_replay():
    inputs = {
        'decisions': {'generated_at': NOW.isoformat(), 'decisions': [{
            'event_id': 'evt-1', 'trace_id': '22d224b6-c685-497c-b47c-d7bf14392e68',
            'scanner_emit_ts': '2026-09-04T15:00:01Z', 'recorded_at': '2026-09-04T15:00:02Z',
            'candidate': {'symbol': 'SPY', 'direction': 'SHORT', 'source': 'radar',
                          'feed_scope': 'sip', 'bar_completed_at': '2026-09-04T15:00:00Z'},
        }]},
        'delivery': {'generated_at': NOW.isoformat(), 'events': [{
            'event_id': 'evt-1', 'attempted_at': '2026-09-04T15:00:03Z',
            'discord_delivered_ts': '2026-09-04T15:00:04Z',
            'ack_receipt_ts': '2026-09-04T15:00:05Z',
        }]},
    }
    snapshot = build_snapshot(inputs, {'code': 'abc'}, now=NOW)
    envelope = snapshot['event_envelopes'][0]
    assert envelope['ts_event'] == '2026-09-04T15:00:00Z'
    assert envelope['ts_discord_delivered'] == '2026-09-04T15:00:04Z'
    assert envelope['ts_ack_receipt'] == '2026-09-04T15:00:05Z'
    assert envelope['replay_eligible'] is True
    assert envelope['timestamp_order_valid'] is True
    assert envelope['execution_enabled'] is False


def test_event_envelope_fails_honest_on_missing_or_reverse_timestamps():
    inputs = {'decisions': {'generated_at': NOW.isoformat(), 'decisions': [{
        'event_id': 'evt-2', 'recorded_at': '2026-09-04T14:59:59Z',
        'candidate': {'symbol': 'QQQ', 'bar_completed_at': '2026-09-04T15:00:00Z'},
    }]}}
    envelope = build_snapshot(inputs, {}, now=NOW)['event_envelopes'][0]
    assert envelope['timestamp_order_valid'] is False
    assert envelope['replay_eligible'] is False
    assert envelope['feed_scope'] == 'missing'
    assert envelope['missing_timestamps'] == ['ts_scanner_emit', 'ts_dispatch_start', 'ts_discord_delivered', 'ts_ack_receipt']
