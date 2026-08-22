"""Pure execution-quality policy for long-option entries."""
from __future__ import annotations

from typing import Any


POLICY_VERSION = "long_option_execution_v1"


def evaluate_long_option_quote(
    *,
    bid: Any,
    ask: Any,
    quote_age_seconds: Any = None,
    min_ask: float = 0.10,
    max_spread_pct_of_mid: float = 0.10,
    max_spread_cents: int = 10,
    max_quote_age_seconds: float = 15.0,
) -> dict[str, Any]:
    """Return a fail-closed execution-quality decision for a long option."""
    try:
        parsed_bid = float(bid)
        parsed_ask = float(ask)
    except (TypeError, ValueError):
        parsed_bid = 0.0
        parsed_ask = 0.0
    try:
        parsed_age = float(quote_age_seconds)
    except (TypeError, ValueError):
        parsed_age = None

    spread = parsed_ask - parsed_bid
    mid = (parsed_ask + parsed_bid) / 2.0 if parsed_bid > 0 and parsed_ask >= parsed_bid else 0.0
    spread_pct = spread / mid if mid > 0 else None
    cross_loss_pct = spread / parsed_ask if parsed_ask > 0 and spread >= 0 else None
    spread_cents = int(round(spread * 100)) if spread >= 0 else None

    blockers: list[str] = []
    if parsed_bid <= 0 or parsed_ask <= 0 or parsed_ask < parsed_bid:
        blockers.append("entry_two_sided_quote_unavailable")
    if parsed_age is None or parsed_age > max_quote_age_seconds:
        blockers.append("entry_quote_stale_or_unverifiable")
    if parsed_ask > 0 and parsed_ask < min_ask:
        blockers.append("entry_premium_below_minimum")
    if spread_cents is not None and spread_cents > max_spread_cents:
        blockers.append("entry_absolute_spread_too_wide")
    if spread_pct is not None and spread_pct > max_spread_pct_of_mid:
        blockers.append("entry_relative_spread_too_wide")

    return {
        "policy_version": POLICY_VERSION,
        "eligible": not blockers,
        "reason": blockers[0] if blockers else "eligible",
        "blockers": blockers,
        "bid": round(parsed_bid, 4) if parsed_bid > 0 else None,
        "ask": round(parsed_ask, 4) if parsed_ask > 0 else None,
        "mid": round(mid, 4) if mid > 0 else None,
        "spread_cents": spread_cents,
        "spread_pct_of_mid": round(spread_pct, 4) if spread_pct is not None else None,
        "immediate_cross_loss_pct_of_ask": round(cross_loss_pct, 4) if cross_loss_pct is not None else None,
        "quote_age_seconds": round(parsed_age, 3) if parsed_age is not None else None,
        "limits": {
            "min_ask": min_ask,
            "max_spread_pct_of_mid": max_spread_pct_of_mid,
            "max_spread_cents": max_spread_cents,
            "max_quote_age_seconds": max_quote_age_seconds,
        },
        "authority": "execution_guard_and_shadow_attribution",
    }
