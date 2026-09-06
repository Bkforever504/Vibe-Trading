"""Final quote and completed-bar checks for shadow trade notifications.

Fixed delivery controls, not a fitted profitability model. The candidate stays
in the research ledger regardless of notification eligibility.
"""
from __future__ import annotations

import hashlib
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

import requests

MAX_SIGNAL_AGE_SECONDS = 180
MAX_QUOTE_AGE_SECONDS = 15
MAX_CHASE_R = 0.25
MIN_REMAINING_RR = 1.5
MAX_SPREAD_BPS = 10


def stamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or '').replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def number(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def setup_key(candidate: Mapping[str, Any]) -> str:
    # Independent of scanner bar and grade; repeated refreshes of the same
    # direction and levels are one plan within the notification cooldown.
    fields = [str(candidate.get('symbol') or '').upper(), str(candidate.get('direction') or '').upper()]
    fields += [str(number(candidate.get(key))) for key in ('trigger', 'stop', 'target')]
    return hashlib.sha256('|'.join(fields).encode()).hexdigest()


def evaluate(candidate: Mapping[str, Any], market: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    reasons: list[str] = []
    now = now.astimezone(timezone.utc)
    available = stamp(candidate.get('bar_completed_at'))
    age = (now - available).total_seconds() if available else None
    if age is None or not 0 <= age <= MAX_SIGNAL_AGE_SECONDS:
        reasons.append('signal_stale_or_future')
    entry, stop, target = [number(candidate.get(key)) for key in ('trigger', 'stop', 'target')]
    side = str(candidate.get('direction') or '').upper()
    geometry = entry is not None and stop is not None and target is not None and (
        (side == 'LONG' and 0 < stop < entry < target) or (side == 'SHORT' and 0 < target < entry < stop))
    if not geometry:
        reasons.append('invalid_plan_geometry')
    quote = market.get('quote') or {}
    bid, ask = number(quote.get('bp')), number(quote.get('ap'))
    quoted_at = stamp(quote.get('t'))
    quote_age = (now - quoted_at).total_seconds() if quoted_at else None
    if market.get('status') != 'ok':
        reasons.append('market_data_unavailable')
    if quote_age is None or not 0 <= quote_age <= MAX_QUOTE_AGE_SECONDS:
        reasons.append('quote_stale_or_future')
    valid_quote = bid is not None and ask is not None and 0 < bid <= ask
    if not valid_quote:
        reasons.append('invalid_bid_ask')
    spread = ((ask - bid) / ((ask + bid) / 2) * 10000) if valid_quote else None
    if spread is not None and spread > MAX_SPREAD_BPS:
        reasons.append('spread_too_wide')
    price = (ask if side == 'LONG' else bid) if valid_quote else None
    chase = rr = None
    if geometry and price is not None:
        sign = 1 if side == 'LONG' else -1
        risk = sign * (price - stop)
        reward = sign * (target - price)
        chase = sign * (price - entry) / abs(entry - stop)
        rr = reward / risk if risk > 0 else None
        if risk <= 0:
            reasons.append('stop_already_breached')
        if reward <= 0:
            reasons.append('target_already_reached')
        if chase > MAX_CHASE_R:
            reasons.append('entry_extended_no_chase')
        if chase < 0:
            reasons.append('trigger_not_currently_held')
        if rr is None or rr < MIN_REMAINING_RR:
            reasons.append('remaining_reward_risk_too_low')
        # Check the observable completed minutes after the signal. Gaps are
        # data debt: they cannot establish that a stop remained intact.
        if available:
            start = available.replace(second=0, microsecond=0)
            if start < available:
                start += timedelta(minutes=1)
            end = now.replace(second=0, microsecond=0)
            observed = {}
            for bar in market.get('bars') or []:
                at = stamp(bar.get('t'))
                high, low = number(bar.get('h')), number(bar.get('l'))
                if at and at.second == 0 and at.microsecond == 0 and start <= at < end and high is not None and low is not None and 0 < low <= high:
                    observed[at] = bar
                    if (side == 'LONG' and low <= stop) or (side == 'SHORT' and high >= stop):
                        reasons.append('invalidated_since_signal')
            required = int(max(0, (end - start).total_seconds()) // 60)
            if len(observed) < required:
                reasons.append('post_signal_bar_coverage_missing')
    entry_boundary = None
    if geometry:
        # Both the no-chase limit and minimum remaining reward/risk must hold.
        rr_boundary = (target + MIN_REMAINING_RR * stop) / (1 + MIN_REMAINING_RR)
        chase_boundary = entry + (1 if side == 'LONG' else -1) * MAX_CHASE_R * abs(entry - stop)
        entry_boundary = min(rr_boundary, chase_boundary) if side == 'LONG' else max(rr_boundary, chase_boundary)
    return {
        'eligible': not reasons, 'reasons': sorted(set(reasons)), 'quote_price': price,
        'quote_at': quote.get('t'), 'quote_age_seconds': quote_age, 'signal_age_seconds': age,
        'spread_bps': round(spread, 3) if spread is not None else None,
        'chase_r': round(chase, 4) if chase is not None else None,
        'remaining_rr': round(rr, 4) if rr is not None else None,
        'entry_boundary': entry_boundary,
        'entry_boundary_label': 'maximum_long_entry' if side == 'LONG' else 'minimum_short_entry',
        'signal_expires_at': (available + timedelta(seconds=MAX_SIGNAL_AGE_SECONDS)).isoformat() if available else None,
        'feed': market.get('feed'), 'quote_scope': 'single_exchange' if market.get('feed') == 'iex' else 'consolidated',
        'execution_enabled': False, 'can_submit_orders': False,
    }


def fetch_market(candidates: Iterable[Mapping[str, Any]], *, now: datetime) -> dict[str, dict[str, Any]]:
    from scripts.premarket_opportunity_radar import _credentials
    rows = list(candidates)
    symbols = sorted({str(row.get('symbol') or '').upper() for row in rows if row.get('symbol')})
    if not symbols:
        return {}
    feed = os.environ.get('VIBE_TRADING_STOCK_FEED', 'iex').lower()
    if feed not in {'sip', 'iex'}:
        return {symbol: {'status': 'not_configured', 'feed': feed} for symbol in symbols}
    start = (now - timedelta(seconds=MAX_SIGNAL_AGE_SECONDS)).replace(second=0, microsecond=0)
    try:
        headers = _credentials()
        response = requests.get('https://data.alpaca.markets/v2/stocks/quotes/latest', headers=headers,
                                params={'symbols': ','.join(symbols), 'feed': feed}, timeout=5)
        response.raise_for_status()
        quotes = response.json().get('quotes') or {}
        response = requests.get('https://data.alpaca.markets/v2/stocks/bars', headers=headers, params={
            'symbols': ','.join(symbols), 'timeframe': '1Min', 'start': start.isoformat(),
            'end': now.isoformat(), 'feed': feed, 'adjustment': 'raw', 'limit': 10000, 'sort': 'asc',
        }, timeout=5)
        response.raise_for_status()
        payload = response.json()
        if payload.get('next_page_token'):
            raise ValueError('unexpected_short_window_pagination')
        bars = payload.get('bars') or {}
        return {symbol: {'status': 'ok', 'feed': feed, 'quote': quotes.get(symbol, {}), 'bars': bars.get(symbol, [])} for symbol in symbols}
    except Exception as exc:
        return {symbol: {'status': 'missing', 'feed': feed, 'error_class': type(exc).__name__} for symbol in symbols}
