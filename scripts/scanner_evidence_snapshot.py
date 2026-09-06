"""Preserve scanner opportunities, gates and research context without tuning rules."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.order_authority_invariant import runtime_violations

HOME = Path.home() / '.vibe-trading'
SOURCES = {
    'radar': 'intraday-opportunity-radar',
    'decisions': 'governed-shadow-decisions',
    'delivery': 'governed-shadow-alert-delivery',
    'chart_review': 'discord-alert-chart-review',
    'calibration': 'grade-recalibration-nominations',
    'latency': 'latency-budget-scorecard',
    'research_utilization': 'research-asset-utilization',
    'options_shadow_twin': 'options-shadow-twin',
    'ranking_regret': 'economic-ranking-regret',
    'feed_reference': 'scanner-feed-reference-study',
}
CODE = ('intraday_opportunity_radar', 'priority_focus_universe', 'simple_price_action_alerts',
        'governed_shadow_decision', 'governed_shadow_alert', 'discord_trade_quality',
        'core_index_tape_watcher', 'post_delivery_grade_calibrator')
REFERENCES = ('research/signal_registry.json',
              'research/MOON_DEV_AND_TRADER_BARBIE_EVIDENCE_REVIEW_2026-08-30.md',
              'research/EVIDENCE_CONFIDENCE_UPGRADE_RESULTS_2026-07-25.md',
              'research/SCANNER_EVIDENCE_RESEARCH_2026-09-04.md',
              'CODEx_CLAUDE_COLLAB/CODEX_HANDOFF_LEARNING_LOOP_2026-09-04.md')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def timestamp(value):
    try:
        at = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return at.astimezone(timezone.utc) if at.tzinfo else None
    except (TypeError, ValueError):
        return None


def _iso(value):
    parsed = timestamp(value)
    return parsed.isoformat().replace('+00:00', 'Z') if parsed else None


def event_envelopes(decisions, delivery, configuration_id):
    """Build replay-safe timing records without inventing unavailable timestamps."""
    delivered = {str(row.get('event_id')): row for row in (delivery.get('events') or [])
                 if isinstance(row, dict) and row.get('event_id')}
    envelopes = []
    for row in decisions:
        if not isinstance(row, dict):
            continue
        candidate = row.get('candidate') if isinstance(row.get('candidate'), dict) else {}
        event_id = str(row.get('event_id') or '') or None
        receipt = delivered.get(str(event_id), {})
        timing = {
            'ts_event': _iso(row.get('bar_close_ts') or candidate.get('bar_completed_at')),
            'ts_scanner_emit': _iso(row.get('scanner_emit_ts')),
            'ts_decision': _iso(row.get('decision_ts') or row.get('recorded_at')),
            'ts_dispatch_start': _iso(receipt.get('dispatch_send_ts') or receipt.get('attempted_at')),
            'ts_discord_delivered': _iso(receipt.get('discord_delivered_ts') or receipt.get('delivered_at')),
            'ts_ack_receipt': _iso(receipt.get('ack_receipt_ts')),
        }
        observed = [timestamp(timing[key]) for key in ('ts_event', 'ts_scanner_emit', 'ts_decision', 'ts_dispatch_start', 'ts_discord_delivered', 'ts_ack_receipt')]
        present = [value for value in observed if value is not None]
        order_valid = all(left <= right for left, right in zip(present, present[1:]))
        missing = [key for key, value in timing.items() if value is None]
        envelopes.append({
            'event_id': event_id,
            'trace_id': row.get('trace_id') or receipt.get('trace_id'),
            'symbol': candidate.get('symbol'),
            'direction': candidate.get('direction'),
            'source': candidate.get('source') or candidate.get('setup'),
            'feed_scope': candidate.get('feed_scope') or candidate.get('market_data_feed') or 'missing',
            'configuration_id': configuration_id,
            **timing,
            'timestamp_order_valid': order_valid,
            'missing_timestamps': missing,
            'replay_eligible': order_valid and not missing,
            'execution_enabled': False,
            'can_submit_orders': False,
        })
    return envelopes


def build_snapshot(artifacts, versions, *, now):
    provenance, usable = {}, {}
    for name in SOURCES:
        value = artifacts.get(name)
        if not isinstance(value, dict) or not value:
            provenance[name] = {'status': 'missing'}
            continue
        if runtime_violations(value):
            provenance[name] = {'status': 'authority_contract_invalid'}
            continue
        try:
            content_hash = digest(value)
        except (TypeError, ValueError):
            provenance[name] = {'status': 'invalid_json_values'}
            continue
        at = timestamp(value.get('generated_at') or value.get('timestamp') or value.get('as_of_et'))
        age = (now - at).total_seconds() if at else None
        provenance[name] = {'status': 'available', 'sha256': content_hash,
                            'source_generated_at': at.isoformat() if at else None,
                            'age_seconds_at_capture': age,
                            'capture_timing': 'near_generation' if age is not None and 0 <= age <= 120 else 'late_or_unknown'}
        usable[name] = value
    configuration_id = digest(versions)
    identity = digest({'source_hashes': {n: p.get('sha256') for n, p in provenance.items()}, 'configuration_id': configuration_id})
    decisions = usable.get('decisions', {}).get('decisions') or []
    delivery = usable.get('delivery', {})
    radar = usable.get('radar', {})
    envelopes = event_envelopes(decisions, delivery, configuration_id)
    return {'schema_version': 'scanner-evidence-snapshot-v2', 'snapshot_id': identity,
            'captured_at': now.isoformat(), 'configuration_id': configuration_id,
            'versions': versions, 'source_provenance': provenance, 'artifacts': usable,
            'event_envelopes': envelopes,
            'summary': {'ranked_candidates': len(radar.get('ranked_candidates') or []),
                        'discovered_symbols': len(radar.get('all_discovered_symbols') or []),
                        'accepted_decisions': sum(r.get('decision') == 'shadow_accepted' for r in decisions),
                        'rejected_decisions': sum(r.get('decision') == 'shadow_rejected' for r in decisions),
                        'quote_gate_checks': len(delivery.get('quality_checks') or []),
                        'replay_eligible_events': sum(row['replay_eligible'] for row in envelopes),
                        'invalid_timestamp_order_events': sum(not row['timestamp_order_valid'] for row in envelopes),
                        'available_sources': len(usable)},
            'interpretation': 'Observational archive. Rejected candidates have no Discord delivery; snapshots are not fills or causal counterfactual outcomes.',
            'automatic_parameter_changes': False, 'promotion_status': 'human_review_required',
            'execution_enabled': False, 'can_submit_orders': False}


def persist(snapshot, directory):
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (snapshot['snapshot_id'] + '.json')
    # Exclusive creation preserves the first capture time across reruns.
    try:
        with target.open('x', encoding='utf-8') as handle:
            json.dump(snapshot, handle, sort_keys=True, allow_nan=False)
            handle.write('\n')
        return True
    except FileExistsError:
        return False


def main():
    artifacts = {}
    for name, stem in SOURCES.items():
        try:
            artifacts[name] = json.loads((HOME / 'reports' / (stem + '.json')).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            pass
    paths = [*(f'scripts/{name}.py' for name in CODE), *REFERENCES]
    versions = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() if (ROOT / name).is_file() else None for name in paths}
    snapshot = build_snapshot(artifacts, versions, now=datetime.now(timezone.utc))
    saved = persist(snapshot, HOME / 'data/scanner_evidence_snapshots')
    report = {key: value for key, value in snapshot.items() if key != 'artifacts'}
    report['snapshot_created'] = saved
    report['snapshot_path'] = str(HOME / 'data/scanner_evidence_snapshots' / (snapshot['snapshot_id'] + '.json'))
    path = HOME / 'reports/scanner-evidence-collection.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)
    print(json.dumps({'snapshot_created': saved, **snapshot['summary']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
