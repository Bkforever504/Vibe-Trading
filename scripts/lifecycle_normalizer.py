#!/usr/bin/env python3
"""Versioned, read-only canonical lifecycle adapter for the three bot families.

This module never rewrites historical logs. It reads existing trade records and
emits normalized views with explicit family semantics so learning reports stop
grading one family's trades with another family's rules.

Families:
- flip_directional_debit: long single-leg calls/puts; direction from right.
- options_defined_risk_credit: credit structures; direction from structure,
  never from a leg's right.
- topstep_mes_futures: MES futures; point-value/fee accounting; direction
  from position side.

Cross-family fields become "not_applicable" (not false, not a mistake).
Ambiguous records are quarantined as direction/outcome "unknown" with an
explicit unknown_reason. Applying one family's grading rules to another
family's view fails closed with FamilyRuleViolation.
"""
from __future__ import annotations

from typing import Any

LIFECYCLE_SCHEMA_VERSION = "1.1.0"

FLIP_FAMILY = "flip_directional_debit"
OPTIONS_FAMILY = "options_defined_risk_credit"
TOPSTEP_FAMILY = "topstep_mes_futures"
BOT_FAMILIES = (FLIP_FAMILY, OPTIONS_FAMILY, TOPSTEP_FAMILY)

NOT_APPLICABLE = "not_applicable"
UNKNOWN = "unknown"

MES_POINT_VALUE = 5.0

# Structure-implied direction for defined-risk credit strategies. A bull put
# credit spread is bullish even though its legs are puts.
CREDIT_STRUCTURE_DIRECTION = {
    "put_spread": "bullish",
    "bull_put_spread": "bullish",
    "call_spread": "bearish",
    "bear_call_spread": "bearish",
    "iron_condor": "neutral",
}

FLIP_STRATEGY_DIRECTION_HINTS = {
    "bull_trend": "bullish",
    "bear_trend": "bearish",
}

BULLISH_TREND_KEYS = ("above_vwap", "above_ema50", "ema50_sloping_up")
BEARISH_TREND_KEYS = ("below_vwap", "below_ema50", "ema50_sloping_down")


class FamilyRuleViolation(Exception):
    """Raised when a rule for one bot family is applied to another family."""


def assert_rule_compatible(rule_family: str, view: dict[str, Any]) -> None:
    view_family = view.get("bot_family")
    if rule_family not in BOT_FAMILIES:
        raise FamilyRuleViolation(f"unknown rule family: {rule_family!r}")
    if view_family != rule_family:
        raise FamilyRuleViolation(
            f"rule family {rule_family!r} cannot grade a {view_family!r} record"
        )


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_quantity(value: Any, field: str, quarantine: list[str]) -> float | None:
    quantity = _safe_float(value)
    if quantity is None or quantity <= 0:
        quarantine.append(f"missing_or_invalid_{field}")
        return None
    return quantity


def underlying_move_is_favorable(direction: str, underlying_change: float) -> bool | str:
    """Whether a signed underlying move favors the position's direction.

    Bearish positions (long puts, bear call spreads) profit when the
    underlying falls. Neutral structures have no single favorable direction
    and return not_applicable.
    """
    if direction == "bullish":
        return underlying_change > 0
    if direction == "bearish":
        return underlying_change < 0
    return NOT_APPLICABLE


def trend_alignment(direction: str, features: dict[str, Any] | None) -> tuple[str, str | None]:
    """Direction-aware trend alignment with explicit unknown reasons.

    Returns (alignment, unknown_reason). Older feature snapshots that lack the
    direction-matching keys yield ("unknown", reason) instead of silently
    grading a put against bullish-only keys.
    """
    features = features or {}
    if direction == "bullish":
        keys = BULLISH_TREND_KEYS
    elif direction == "bearish":
        keys = BEARISH_TREND_KEYS
    else:
        return NOT_APPLICABLE, None
    present = [key for key in keys if key in features]
    if len(present) < len(keys):
        missing = [key for key in keys if key not in features]
        return UNKNOWN, f"missing_{direction}_feature_keys:{','.join(missing)}"
    return ("confirmed" if all(features.get(key) is True for key in keys) else "unconfirmed"), None


def _outcome_from_pnl(status: str, pnl: float | None) -> tuple[str, str | None]:
    if status == "open":
        return "open", None
    if status != "closed":
        return UNKNOWN, f"unrecognized_status:{status or 'empty'}"
    if pnl is None:
        return UNKNOWN, "closed_without_resolvable_pnl"
    if pnl > 0:
        return "win", None
    if pnl < 0:
        return "loss", None
    return "flat", None


def normalize_flip_trade(trade: dict[str, Any]) -> dict[str, Any]:
    """Normalize a flip-trades.json record (long single-leg debit options)."""
    quarantine: list[str] = []
    right = str(trade.get("right") or "").upper()
    strategy = str(trade.get("strategy") or "")

    if right == "CALL":
        direction = "bullish"
    elif right == "PUT":
        direction = "bearish"
    else:
        direction = UNKNOWN
        quarantine.append("missing_or_invalid_right")

    hint = FLIP_STRATEGY_DIRECTION_HINTS.get(strategy)
    if hint and direction not in (UNKNOWN,) and hint != direction:
        direction = UNKNOWN
        quarantine.append(f"conflicting_direction_fields:strategy={strategy},right={right}")

    entry = _safe_float(trade.get("entry_price"))
    exit_price = _safe_float(trade.get("exit_price"))
    contracts = _positive_quantity(trade.get("contracts"), "contracts", quarantine)
    pnl = _safe_float(trade.get("pnl"))
    if pnl is None and entry is not None and exit_price is not None and contracts is not None:
        pnl = round((exit_price - entry) * 100 * contracts, 2)
    debit_paid = (
        round(entry * 100 * contracts, 2)
        if entry is not None and contracts is not None
        else None
    )
    return_on_debit_pct = (
        round(pnl / debit_paid * 100, 3) if pnl is not None and debit_paid else None
    )
    if debit_paid is None:
        quarantine.append("missing_entry_price")

    status = str(trade.get("status") or "")
    outcome, outcome_reason = _outcome_from_pnl(status, pnl)
    if outcome_reason:
        quarantine.append(outcome_reason)

    return {
        "lifecycle_schema_version": LIFECYCLE_SCHEMA_VERSION,
        "bot_family": FLIP_FAMILY,
        "strategy_family": strategy or UNKNOWN,
        "instrument_type": "equity_option",
        "position_effect": "long_debit",
        "direction": direction,
        "direction_basis": "option_right",
        "right": right or UNKNOWN,
        "outcome_status": outcome,
        "pnl_dollars": pnl,
        "risk_basis": "debit_paid",
        "risk_dollars": debit_paid,
        "return_on_risk_pct": return_on_debit_pct,
        "credit_fields": NOT_APPLICABLE,
        "point_value": NOT_APPLICABLE,
        "trade_id": trade.get("id"),
        "parent_order_id": trade.get("alpaca_order_id"),
        "symbol": trade.get("symbol"),
        "entry_date": trade.get("entry_date"),
        "exit_date": trade.get("exit_date"),
        "source": "flip-trades.json",
        "quarantined": bool(quarantine),
        "unknown_reasons": quarantine,
    }


def normalize_options_trade(trade: dict[str, Any]) -> dict[str, Any]:
    """Normalize an options-trades.json record (defined-risk credit)."""
    quarantine: list[str] = []
    strategy = str(trade.get("strategy") or "")

    if strategy in CREDIT_STRUCTURE_DIRECTION:
        direction = CREDIT_STRUCTURE_DIRECTION[strategy]
        direction_basis = "credit_structure"
    else:
        direction = UNKNOWN
        direction_basis = UNKNOWN
        quarantine.append(f"unclassified_credit_structure:{strategy or 'empty'}")

    qty = _positive_quantity(trade.get("qty"), "qty", quarantine)
    credit = _safe_float(trade.get("net_credit"))
    closing_debit = _safe_float(trade.get("closing_filled_avg_price"))
    realized_pnl = _safe_float(trade.get("realized_pnl_dollars"))
    declared_pnl_source = str(trade.get("pnl_source") or "")
    pnl = (
        realized_pnl
        if declared_pnl_source == "fill_derived" and realized_pnl is not None
        else None
    )
    normalized_pnl_source = "fill_derived" if pnl is not None else UNKNOWN
    if pnl is None and credit is not None and closing_debit is not None and qty is not None:
        pnl = round((credit - closing_debit) * 100 * qty, 2)
        normalized_pnl_source = "fill_derived"
    legacy_no_fill_pnl = (
        str(trade.get("status") or "") == "closed"
        and pnl is None
        and closing_debit is None
    )

    # The options bot stores max_risk_per_contract in dollars, not option
    # price points. See iwm_options_bot._sized_qty() and the trade metadata
    # written by run_put_spread()/run_iron_condor().
    max_risk_per_contract = _safe_float(trade.get("max_risk_per_contract"))
    max_risk = (
        round(max_risk_per_contract * qty, 2)
        if max_risk_per_contract is not None and qty is not None
        else None
    )
    if credit is None or credit <= 0:
        quarantine.append("missing_or_nonpositive_net_credit")
    if max_risk is None:
        quarantine.append("missing_max_risk")
    return_on_max_risk_pct = (
        round(pnl / max_risk * 100, 3) if pnl is not None and max_risk else None
    )

    status = str(trade.get("status") or "")
    outcome, outcome_reason = _outcome_from_pnl(status, pnl)
    if outcome_reason:
        quarantine.append(outcome_reason)

    return {
        "lifecycle_schema_version": LIFECYCLE_SCHEMA_VERSION,
        "bot_family": OPTIONS_FAMILY,
        "strategy_family": strategy or UNKNOWN,
        "instrument_type": "equity_option_multi_leg",
        "position_effect": "short_credit_defined_risk",
        "direction": direction,
        "direction_basis": direction_basis,
        # A leg's right must never set the structure's direction.
        "right": NOT_APPLICABLE,
        "outcome_status": outcome,
        "pnl_dollars": pnl,
        "pnl_source": normalized_pnl_source,
        "legacy_no_fill_pnl": legacy_no_fill_pnl,
        "risk_basis": "credit_max_risk",
        "risk_dollars": max_risk,
        "opening_credit_dollars": (
            round(credit * 100 * qty, 2)
            if credit is not None and qty is not None
            else None
        ),
        "closing_debit_dollars": (
            round(closing_debit * 100 * qty, 2)
            if closing_debit is not None and qty is not None
            else None
        ),
        "return_on_risk_pct": return_on_max_risk_pct,
        "point_value": NOT_APPLICABLE,
        "trade_id": trade.get("id"),
        "parent_order_id": trade.get("order_id"),
        "symbol": trade.get("underlying"),
        "entry_date": str(trade.get("opened_at") or "")[:10] or None,
        "exit_date": str(trade.get("closed_at") or "")[:10] or None,
        "source": "options-trades.json",
        "quarantined": bool(quarantine),
        "unknown_reasons": quarantine,
    }


def normalize_topstep_trade(trade: dict[str, Any]) -> dict[str, Any]:
    """Normalize an MES futures trade with point-value and fee accounting."""
    quarantine: list[str] = []
    side = str(trade.get("side") or "").lower()
    if side in {"long", "buy"}:
        direction = "bullish"
        sign = 1.0
    elif side in {"short", "sell"}:
        direction = "bearish"
        sign = -1.0
    else:
        direction = UNKNOWN
        sign = 0.0
        quarantine.append(f"missing_or_invalid_side:{side or 'empty'}")

    contracts = _positive_quantity(trade.get("contracts"), "contracts", quarantine)
    entry = _safe_float(trade.get("entry_price"))
    exit_price = _safe_float(trade.get("exit_price"))
    fees = _safe_float(trade.get("fees")) or 0.0
    pnl = _safe_float(trade.get("pnl"))
    if (
        pnl is None
        and entry is not None
        and exit_price is not None
        and sign
        and contracts is not None
    ):
        points = (exit_price - entry) * sign
        pnl = round(points * MES_POINT_VALUE * contracts - fees, 2)
    if pnl is None and not quarantine:
        quarantine.append("missing_price_path")

    status = str(trade.get("status") or "closed")
    outcome, outcome_reason = _outcome_from_pnl(status, pnl)
    if outcome_reason:
        quarantine.append(outcome_reason)

    return {
        "lifecycle_schema_version": LIFECYCLE_SCHEMA_VERSION,
        "bot_family": TOPSTEP_FAMILY,
        "strategy_family": str(trade.get("strategy") or UNKNOWN),
        "instrument_type": "future",
        "position_effect": "futures_directional",
        "direction": direction,
        "direction_basis": "position_side",
        "right": NOT_APPLICABLE,
        "outcome_status": outcome,
        "pnl_dollars": pnl,
        "risk_basis": "prop_rule_drawdown",
        "point_value": MES_POINT_VALUE,
        "fees_dollars": fees,
        "credit_fields": NOT_APPLICABLE,
        "trade_id": trade.get("id"),
        "parent_order_id": trade.get("order_id"),
        "symbol": str(trade.get("symbol") or "MES"),
        "entry_date": trade.get("entry_date"),
        "exit_date": trade.get("exit_date"),
        "source": str(trade.get("source") or "topstep_sim"),
        "quarantined": bool(quarantine),
        "unknown_reasons": quarantine,
    }
