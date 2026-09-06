"""Compare IEX/SIP historical bars on identical saved alerts, never live routing."""
from __future__ import annotations

import json
import argparse
import hashlib
import sys
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import requests
from scripts.premarket_opportunity_radar import _credentials
from scripts.discord_alert_chart_review import evaluate_alert

ET = ZoneInfo('America/New_York')


def fetch_reference(symbols, session_date, feed, *, now):
    if not symbols:
        return {}
    day = datetime.strptime(session_date, '%Y-%m-%d').date()
    start = datetime.combine(day, time(9, 30), ET).astimezone(timezone.utc)
    end = datetime.combine(day, time(16), ET).astimezone(timezone.utc)
    if end > now - timedelta(minutes=15):
        raise ValueError('completed_delayed_session_required')
    params = {'symbols': ','.join(sorted(symbols)), 'timeframe': '1Min', 'start': start.isoformat(),
              'end': end.isoformat(), 'feed': feed, 'sort': 'asc', 'adjustment': 'raw', 'limit': 10000}
    grouped, tokens = {}, set()
    while True:
        response = requests.get('https://data.alpaca.markets/v2/stocks/bars', headers=_credentials(), params=dict(params), timeout=20)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload.get('bars'), dict):
            raise ValueError('missing_bars')
        for symbol, bars in payload['bars'].items():
            grouped.setdefault(symbol, []).extend(b for b in bars if start <= datetime.fromisoformat(b['t'].replace('Z', '+00:00')) < end)
        token = payload.get('next_page_token')
        if not token:
            return grouped
        if token in tokens or len(tokens) >= 100:
            raise ValueError('incomplete_pagination')
        tokens.add(token)
        params['page_token'] = token


def compare(alerts, feeds, *, now):
    # Historical duplicates stay excluded from outcome comparisons.
    unique = [row for row in alerts if not row.get('duplicate_of')]
    results = {feed: [evaluate_alert(row, bars.get(row.get('symbol'), []), now=now) for row in unique] for feed, bars in feeds.items()}
    transitions = Counter()
    if 'iex' in results and 'sip' in results:
        for iex, sip in zip(results['iex'], results['sip']):
            transitions[f"{iex.get('status')} -> {sip.get('status')}"] += 1
    return {'unique_saved_alerts': len(unique), 'status_by_feed': {feed: dict(Counter(r.get('status') for r in rows)) for feed, rows in results.items()},
            'iex_to_sip_status_transitions': dict(transitions),
            'coverage': {feed: {s: {'distinct_minutes': len({b['t'] for b in bars}), 'volume': sum(b.get('v', 0) for b in bars)} for s, bars in grouped.items()} for feed, grouped in feeds.items()},
            'automatic_parameter_changes': False, 'promotion_status': 'human_review_required',
            'execution_enabled': False, 'can_submit_orders': False,
            'interpretation': 'Historical reference comparison, not as-observed replay, calibration-qualified outcomes, option returns or evidence of live SIP entitlement.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--if-needed', action='store_true')
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    source = Path.home() / '.vibe-trading/reports/discord-alert-chart-review.json'
    saved = json.loads(source.read_text(encoding='utf-8-sig'))
    day = saved['session_date']
    alerts = saved['alerts']
    input_hash = hashlib.sha256(json.dumps(alerts, sort_keys=True).encode()).hexdigest()
    output = Path.home() / '.vibe-trading/reports/scanner-feed-reference-study.json'
    if args.if_needed:
        close = datetime.combine(datetime.strptime(day, '%Y-%m-%d').date(), time(16), ET)
        if now < close + timedelta(minutes=15):
            print(json.dumps({'status': 'deferred_until_session_complete_plus_15m'}))
            return 0
        try:
            prior = json.loads(output.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            prior = {}
        if prior.get('input_alerts_sha256') == input_hash and prior.get('session_date') == day and not prior.get('feed_errors'):
            print(json.dumps({'status': 'unchanged_frozen_evidence'}))
            return 0
    symbols = {row['symbol'] for row in alerts if row.get('symbol')}
    feeds, errors = {}, {}
    for feed in ('iex', 'sip'):
        try:
            feeds[feed] = fetch_reference(symbols, day, feed, now=now)
        except (requests.RequestException, ValueError, KeyError) as exc:
            errors[feed] = type(exc).__name__
    result = {'session_date': day, 'input_alerts_sha256': input_hash, 'retrieved_at': now.isoformat(), 'feed_errors': errors, **compare(alerts, feeds, now=now)}
    directory = Path.home() / '.vibe-trading/data/scanner_feed_studies'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (now.strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    with target.open('x', encoding='utf-8') as handle:
        json.dump({'report': result, 'reference_bars': feeds, 'saved_alerts': alerts}, handle, sort_keys=True)
    result['frozen_inputs_path'] = str(target)
    temporary = output.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    temporary.replace(output)
    print(json.dumps({k: v for k, v in result.items() if k != 'coverage'}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
