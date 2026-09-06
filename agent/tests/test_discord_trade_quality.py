from datetime import datetime, timedelta, timezone

import pytest

from scripts import discord_trade_quality as quality
from scripts import governed_shadow_alert as dispatch

NOW = datetime(2026, 9, 4, 14, 2, 5, tzinfo=timezone.utc)


def plan():
    return {'symbol': 'QQQ', 'direction': 'LONG', 'trigger': 100, 'stop': 99, 'target': 102, 'bar_completed_at': '2026-09-04T14:00:00Z'}


def market():
    return {'status': 'ok', 'feed': 'iex', 'quote': {'bp': 100.09, 'ap': 100.10, 't': NOW.isoformat()},
            'bars': [{'t': f'2026-09-04T14:0{i}:00Z', 'h': 100.2, 'l': 99.9} for i in range(2)]}


def test_eligible_shadow_plan_uses_current_ask_and_remaining_rr():
    check = quality.evaluate(plan(), market(), now=NOW)
    assert check['eligible']
    assert check['quote_price'] == 100.1
    assert check['remaining_rr'] == pytest.approx(1.7273)
    assert check['quote_scope'] == 'single_exchange'


@pytest.mark.parametrize('mode,reason', [
    ('chase', 'entry_extended_no_chase'), ('stop', 'invalidated_since_signal'),
    ('stale', 'quote_stale_or_future'), ('gap', 'post_signal_bar_coverage_missing'),
    ('future', 'signal_stale_or_future'), ('not_held', 'trigger_not_currently_held'),
])
def test_known_bad_plans_do_not_reach_discord(mode, reason):
    data, candidate = market(), plan()
    if mode == 'chase': data['quote'].update(bp=100.49, ap=100.50)
    elif mode == 'stop': data['bars'][0]['l'] = 98.9
    elif mode == 'stale': data['quote']['t'] = (NOW - timedelta(seconds=30)).isoformat()
    elif mode == 'gap': data['bars'].pop()
    elif mode == 'future': candidate['bar_completed_at'] = (NOW + timedelta(minutes=1)).isoformat()
    elif mode == 'not_held': data['quote'].update(bp=99.89, ap=99.90)
    check = quality.evaluate(candidate, data, now=NOW)
    assert not check['eligible']
    assert reason in check['reasons']


def test_rejected_core_plans_are_not_trade_notifications():
    row = {'decision': 'shadow_rejected', 'candidate': {**plan(), 'lane': 'CORE_INDEX_SHADOW'}}
    assert dispatch._discord_route(row)[0] is False


def test_entry_boundary_respects_reward_risk_and_expiry():
    check = quality.evaluate(plan(), market(), now=NOW)
    assert check['entry_boundary'] == pytest.approx(100.2)
    assert check['signal_expires_at'] == '2026-09-04T14:03:00+00:00'
    message = dispatch.format_message({'decision': 'shadow_accepted', 'candidate': plan(), 'delivery_quality': check})
    assert '100 to 100.2000' in message
    assert 'single_exchange' in message
    assert 'not an option-contract fill quote' in message


def test_short_entry_boundary_uses_bid_side_floor():
    candidate = {**plan(), 'direction': 'SHORT', 'stop': 101, 'target': 98}
    snapshot = market()
    snapshot['quote'].update(bp=99.9, ap=99.91)
    check = quality.evaluate(candidate, snapshot, now=NOW)
    assert check['eligible']
    assert check['entry_boundary'] == pytest.approx(99.8)
    assert check['entry_boundary_label'] == 'minimum_short_entry'


def test_same_levels_with_new_bar_or_grade_are_one_plan():
    assert quality.setup_key(plan()) == quality.setup_key({**plan(), 'grade': 'A', 'bar_completed_at': NOW.isoformat()})


def test_delivery_is_quote_checked_logged_and_deduplicated_across_refreshes(tmp_path):
    now = datetime.now(timezone.utc)
    candidate = {**plan(), 'bar_completed_at': now.replace(second=0, microsecond=0).isoformat()}
    snapshot = {'status': 'ok', 'feed': 'iex', 'quote': {'bp': 100.09, 'ap': 100.1, 't': now.isoformat()}, 'bars': []}
    sent = []
    kwargs = dict(send=True, state_path=tmp_path/'state.json', report_path=tmp_path/'report.json', event_path=tmp_path/'events.jsonl',
                  market_fetcher=lambda *args, **kwargs: {'QQQ': snapshot},
                  sender=lambda text: sent.append(text) or {'delivered': True, 'attempts': 1, 'error_class': None,
                      'discord_message_id': '123456789', 'discord_delivered_ts': (now + timedelta(milliseconds=500)).isoformat().replace('+00:00', 'Z'),
                      'ack_receipt_ts': (now + timedelta(seconds=1)).isoformat().replace('+00:00', 'Z')})
    row = {'event_id': 'one', 'trace_id': '22d224b6-c685-497c-b47c-d7bf14392e68',
           'decision': 'shadow_accepted', 'candidate': candidate}
    first = dispatch.run({'decisions': [row]}, **kwargs)
    second = dispatch.run({'decisions': [{**row, 'event_id': 'two'}]}, **kwargs)
    assert len(sent) == 1
    assert first['events'][0]['delivered_at'] >= first['events'][0]['attempted_at']
    assert first['events'][0]['delivery_timestamp_semantics'] == 'discord_message_timestamp'
    assert first['events'][0]['discord_message_id'] == '123456789'
    assert first['events'][0]['transport_seconds'] >= 0
    assert second['dashboard_only_reasons']['duplicate_setup_cooldown'] == 1
