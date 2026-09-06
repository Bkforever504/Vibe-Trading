"""Shadow-only latency evidence from exact delivery receipts; never impute stages."""
from __future__ import annotations

import json
import math
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HOME = Path.home() / '.vibe-trading'
REPORT_PATH = HOME / 'reports/latency-budget-scorecard.json'
INPUTS = {
    'governed_shadow': HOME / 'data/governed_shadow_alert_events.jsonl',
    'core_index_tape_watcher': HOME / 'data/core_index_tape_delivery_events.jsonl',
}
BACKFILL_PATH = HOME / 'data/discord_delivery_backfill.jsonl'
LATENCY_PAIRS_PATH = Path(__file__).resolve().parents[1] / 'data/latency_pairs.jsonl'
STAGES = {
    'signal_bar_to_decision': ('signal_available_at', 'decision_at', 30),
    'decision_to_alert': ('decision_at', 'attempted_at', 5),
    'alert_to_discord_delivered': ('attempted_at', 'delivered_at', 10),
    'total_signal_to_delivered': ('signal_available_at', 'delivered_at', 60),
}
RECOMMENDATIONS = {
    'signal_bar_to_decision': 'Measure scheduler start versus bar availability, feed delay, scan duration and Python cold-start separately.',
    'decision_to_alert': 'Inspect work queued before send and final quote-fetch duration; preserve safety gates.',
    'alert_to_discord_delivered': 'Inspect Discord request duration, rate limits and transport retries.',
    'total_signal_to_delivered': 'Inspect measured component breaches; missing stage timestamps prevent bottleneck attribution.',
}


def stamp(value):
    try:
        at = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return at.astimezone(timezone.utc) if at.tzinfo else None
    except (ValueError, TypeError):
        return None


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    low, high = math.floor(index), math.ceil(index)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (index - low), 3)


def paired_latency_proof(sources, *, samples=2000, mean_block=5, seed=20260905):
    """Stationary-block bootstrap of paired challenger-minus-baseline latency."""
    pairs = {}
    for rows in sources.values():
        for row in rows:
            pair_id, variant = row.get('pair_id'), row.get('pipeline_variant')
            start, end = stamp(row.get('signal_available_at')), stamp(row.get('delivered_at'))
            if pair_id and variant in {'baseline', 'challenger'} and start and end and end >= start:
                pairs.setdefault(str(pair_id), {})[variant] = (end - start).total_seconds()
    deltas = [values['challenger'] - values['baseline'] for _, values in sorted(pairs.items())
              if {'baseline', 'challenger'} <= values.keys()]
    base = {'paired_samples': len(deltas), 'minimum_paired_samples': 30,
            'method': 'stationary_block_bootstrap_challenger_minus_baseline',
            'claim_rule': '95pct_ci_must_exclude_zero', 'execution_enabled': False}
    if len(deltas) < 30:
        return {**base, 'status': 'insufficient_evidence', 'mean_delta_seconds': None, 'ci95_seconds': [None, None]}
    rng = random.Random(seed)
    probability = 1.0 / max(1, mean_block)
    estimates = []
    for _ in range(samples):
        picked, index = [], rng.randrange(len(deltas))
        while len(picked) < len(deltas):
            picked.append(deltas[index])
            index = rng.randrange(len(deltas)) if rng.random() < probability else (index + 1) % len(deltas)
        estimates.append(sum(picked) / len(picked))
    low, high = percentile(estimates, .025), percentile(estimates, .975)
    mean = round(sum(deltas) / len(deltas), 3)
    return {**base, 'status': 'improvement_supported' if high is not None and high < 0 else 'cannot_claim_improvement',
            'mean_delta_seconds': mean, 'ci95_seconds': [low, high]}


def apply_backfills(sources, backfills):
    exact = {(str(row.get('source')), str(row.get('event_id'))): row.get('discord_delivered_ts')
             for row in backfills if row.get('status') == 'recovered' and row.get('discord_delivered_ts')}
    return {source: [{**row, 'discord_delivered_ts': exact.get((source, str(row.get('event_id')))),
                      'delivered_at': exact.get((source, str(row.get('event_id')))),
                      'delivery_timestamp_semantics': 'discord_message_timestamp'}
                     if (source, str(row.get('event_id'))) in exact else row for row in rows]
            for source, rows in sources.items()}


def build_report(sources, *, now=None):
    now = now or datetime.now(timezone.utc)
    excluded = Counter()
    eligible = []
    seen = set()
    for source, rows in sources.items():
        for row in rows:
            if not isinstance(row, dict):
                excluded['malformed_record'] += 1
                continue
            identity = row.get('event_id') or row.get('transition_id')
            exact = row.get('delivery_timestamp_semantics') == 'discord_message_timestamp'
            delivered = row.get('delivered') is True or row.get('delivery_status') == 'delivered'
            times = {key: stamp(row.get(key)) for key in ('signal_available_at', 'decision_at', 'attempted_at', 'delivered_at')}
            if not identity or not delivered or not exact or not times['delivered_at']:
                excluded['missing_exact_delivery_receipt'] += 1
                continue
            if times['delivered_at'] > now:
                excluded['future_delivery'] += 1
                continue
            present = [value for value in times.values() if value is not None]
            if present != sorted(present):
                excluded['non_monotonic_clock'] += 1
                continue
            key = (source, identity)
            if key in seen:
                excluded['duplicate'] += 1
                continue
            seen.add(key)
            day = times['delivered_at'].astimezone(ZoneInfo('America/New_York')).date().isoformat()
            eligible.append((source, day, times))
    days = sorted({day for _, day, _ in eligible})[-30:]
    by_source, breaches = {}, []
    for source in sources:
        rows = [times for src, day, times in eligible if src == source and day in days]
        stages = {}
        for name, (start, end, default_target) in STAGES.items():
            target = 15 if source == 'core_index_tape_watcher' and name == 'total_signal_to_delivered' else default_target
            values = [(r[end] - r[start]).total_seconds() for r in rows if r[start] and r[end]]
            p90 = percentile(values, .9)
            status = 'missing' if p90 is None else ('over_budget' if p90 > target else 'within_budget')
            stages[name] = {'count': len(values), 'missing_count': len(rows) - len(values), 'p50': percentile(values, .5), 'p90': p90, 'p99': percentile(values, .99), 'target': target, 'status': status}
            if status == 'over_budget':
                breaches.append({'source': source, 'stage': name, 'p90': p90, 'target': target, 'recommendation': RECOMMENDATIONS[name]})
        by_source[source] = stages
    return {'provider': 'latency_budget_scorecard', 'generated_at': now.isoformat(),
            'status': 'ok' if eligible else 'insufficient_evidence', 'sessions_reviewed': len(days),
            'session_dates': days, 'window_policy': 'last_30_observed_receipt_dates',
            'by_source': by_source, 'breach_summary': breaches, 'excluded_counts': dict(excluded),
            'historical_gap': {'pre_instrumentation_rows': excluded.get('missing_exact_delivery_receipt', 0),
                               'timestamps_synthesized': 0,
                               'recoverable_only_with_stored_discord_message_id': True},
            'paired_pipeline_proof': paired_latency_proof(sources),
            'measurement_boundary': 'transport_acknowledgment_not_user_read_time',
            'automatic_parameter_changes': False, 'promotion_status': 'human_review_required',
            'execution_enabled': False, 'can_submit_orders': False}


def read_rows(path):
    rows, errors = [], 0
    if not path.exists():
        return rows, 'missing', errors
    try:
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                errors += 1
        return rows, 'partial' if errors else 'ok', errors
    except OSError:
        return [], 'unreadable', errors


def main():
    inputs = {source: read_rows(path) for source, path in INPUTS.items()}
    backfills = read_rows(BACKFILL_PATH)[0]
    sources = apply_backfills({source: result[0] for source, result in inputs.items()}, backfills)
    report = build_report(sources)
    pair_rows, pair_status, pair_errors = read_rows(LATENCY_PAIRS_PATH)
    valid_pairs = [row for row in pair_rows if isinstance(row.get('baseline_latency_ms'), (int, float))
                   and isinstance(row.get('new_latency_ms'), (int, float))]
    if not any(isinstance(row.get('baseline_latency_ms'), (int, float)) for row in pair_rows):
        report['paired_pipeline_proof'] = {
            'status': 'no_baseline', 'paired_samples': 0, 'minimum_paired_samples': 30,
            'reason': 'no_defensible_parallel_baseline_recorded', 'ci95_seconds': [None, None],
            'timestamps_synthesized': 0, 'execution_enabled': False,
        }
    report['latency_pair_ledger'] = {'status': pair_status, 'records': len(pair_rows),
                                     'valid_pairs': len(valid_pairs), 'malformed_lines': pair_errors}
    report['input_status'] = {source: {'status': result[1], 'malformed_lines': result[2]} for source, result in inputs.items()}
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = REPORT_PATH.with_suffix('.json.tmp')
    temp.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    temp.replace(REPORT_PATH)
    print(json.dumps({'status': report['status'], 'sessions_reviewed': report['sessions_reviewed'], 'breaches': len(report['breach_summary']), 'excluded_counts': report['excluded_counts']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
