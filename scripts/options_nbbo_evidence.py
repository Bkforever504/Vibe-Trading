"""Normalize fresh OPRA observations into critic evidence without inferring tape."""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

OCC = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")
MAX_AGE_SECONDS = 60


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _stamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or '').replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def analyze(rows: Iterable[Mapping[str, Any]], underlying: str, *, as_of: datetime) -> dict[str, Any]:
    as_of = as_of.astimezone(timezone.utc)
    rejected: Counter[str] = Counter()
    latest: dict[str, Mapping[str, Any]] = {}
    trades: dict[tuple[str, str], Mapping[str, Any]] = {}
    for raw in rows:
        row = raw if isinstance(raw, Mapping) else {}
        symbol = str(row.get('symbol') or '').replace(' ', '').upper()
        match = OCC.fullmatch(symbol)
        if not match or match.group(1) != underlying.upper():
            continue
        observed = _stamp(row.get('quote_timestamp') or row.get('observed_at') or row.get('event_at'))
        age = (as_of - observed).total_seconds() if observed else None
        if age is None or not 0 <= age <= MAX_AGE_SECONDS:
            rejected['stale_or_future'] += 1
            continue
        provenance = row.get('provenance') or {}
        if row.get('quote_scope') != 'databento_opra_cbbo_1s' or provenance.get('licensed_consolidated_nbbo') is not True:
            rejected['unverified_nbbo_scope'] += 1
            continue
        record_type = str(row.get('record_type') or row.get('event_type') or 'quote').lower()
        if record_type in {'trade', 'option_print'}:
            identity = (str(provenance.get('provider') or row.get('provider') or ''), str(row.get('trade_id') or ''))
            if row.get('verified') is not True or not all(identity):
                rejected['unverified_trade'] += 1
                continue
            trades[identity] = row
        else:
            previous = latest.get(symbol)
            if previous is None or (_stamp(previous.get('quote_timestamp') or previous.get('observed_at')) or datetime.min.replace(tzinfo=timezone.utc)) < observed:
                latest[symbol] = row
    put_dollars = call_dollars = 0.0
    iv_by_right: dict[str, list[float]] = {'P': [], 'C': []}
    gamma_total = 0.0
    gamma_inputs = 0
    ages = []
    for symbol, row in latest.items():
        match = OCC.fullmatch(symbol)
        bid, ask, ask_size = _number(row.get('bid')), _number(row.get('ask')), _number(row.get('ask_size'))
        if bid is None or ask is None or ask_size is None or bid <= 0 or ask < bid or ask_size < 0:
            rejected['invalid_quote'] += 1
            continue
        value = ((bid + ask) / 2) * ask_size * 100
        if match.group(3) == 'P': put_dollars += value
        else: call_dollars += value
        iv = _number(row.get('iv'))
        if iv is not None:
            iv_by_right[match.group(3)].append(iv)
        gamma, oi, spot = (_number(row.get(k)) for k in ('gamma', 'open_interest', 'spot'))
        if None not in (gamma, oi, spot):
            gamma_total += gamma * oi * 100 * spot
            gamma_inputs += 1
        at = _stamp(row.get('quote_timestamp') or row.get('observed_at'))
        ages.append((as_of - at).total_seconds())
    ratio = put_dollars / call_dollars if call_dollars > 0 else None
    skew = (sum(iv_by_right['P']) / len(iv_by_right['P']) - sum(iv_by_right['C']) / len(iv_by_right['C'])) if all(iv_by_right.values()) else None
    unusual, directional = [], {'LONG': 0.0, 'SHORT': 0.0}
    for row in trades.values():
        symbol = str(row.get('symbol') or '').replace(' ', '').upper()
        match = OCC.fullmatch(symbol)
        premium = _number(row.get('premium'))
        if premium is None:
            price, size = _number(row.get('price')), _number(row.get('size'))
            premium = price * size * 100 if price is not None and size is not None else None
        # Direction is only known for a verified ask-aggressing buy. Contract
        # right alone never proves buyer intent.
        aggression = str(row.get('aggressor_side') or '').lower()
        side = 'SHORT' if match.group(3) == 'P' and aggression in {'ask', 'buy'} else 'LONG' if match.group(3) == 'C' and aggression in {'ask', 'buy'} else None
        if premium is not None and premium >= 50_000:
            item = {'symbol': symbol, 'right': 'PUT' if match.group(3) == 'P' else 'CALL', 'premium': round(premium, 2),
                    'size': _number(row.get('size')), 'strike': int(match.group(4)) / 1000, 'observed_at': row.get('observed_at') or row.get('event_at'), 'direction': side}
            unusual.append(item)
            if side:
                directional[side] += premium
    signals = []
    if ratio is not None and ratio > 1.5: signals.append(('put_call_ratio', 'SHORT'))
    elif ratio is not None and ratio < (1 / 1.5): signals.append(('put_call_ratio', 'LONG'))
    if skew is not None and skew > 0: signals.append(('skew', 'SHORT'))
    elif skew is not None and skew < 0: signals.append(('skew', 'LONG'))
    if directional['SHORT'] > directional['LONG'] and directional['SHORT'] > 0: signals.append(('unusual_prints', 'SHORT'))
    elif directional['LONG'] > directional['SHORT'] and directional['LONG'] > 0: signals.append(('unusual_prints', 'LONG'))
    counts = Counter(direction for _, direction in signals)
    bias, aligned = (counts.most_common(1)[0] if counts else ('NEUTRAL', 0))
    if aligned < 2:
        bias = 'NEUTRAL'
    available = bool(latest)
    return {'status': 'ok' if available else 'missing', 'symbol': underlying.upper(), 'available': available,
            'fresh': available and bool(ages) and max(ages) <= MAX_AGE_SECONDS, 'observed_at': max((_stamp(r.get('quote_timestamp') or r.get('observed_at')) for r in latest.values()), default=None),
            'age_seconds': round(max(ages), 3) if ages else None, 'direction': bias, 'aligned_signal_count': aligned,
            'aligned_signals': [name for name, direction in signals if direction == bias],
            'evidence_numeric': {'put_call_dollar_premium_ratio': round(ratio, 4) if ratio is not None else None,
                                 'skew_5pct': round(skew, 4) if skew is not None else None,
                                 'unusual_prints_count': len(unusual),
                                 'unusual_prints_dollar_total': round(sum(x['premium'] for x in unusual), 2),
                                 'atm_iv_change_since_prior_close_pct': None,
                                 'net_gamma_estimate': round(gamma_total, 2) if gamma_inputs else None},
            'unusual_prints': sorted(unusual, key=lambda x: str(x.get('observed_at')), reverse=True),
            'quote_contract_count': len(latest), 'rejected_counts': dict(rejected),
            'limitations': 'OPRA NBBO top-of-book. Quote depth is not trade direction; IV/gamma/OI require separately observed fields.',
            'execution_enabled': False, 'can_submit_orders': False}
