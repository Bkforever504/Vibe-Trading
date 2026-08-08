"""Pure execution and exit policy helpers for SPY-family option trades.

The functions in this module do not access a broker and cannot submit orders.
They keep evidence scoring, limit-price construction, and underlying exit logic
testable outside the large Flip bot process.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def execution_ladder_prices(
    bid: float,
    ask: float,
    maximum_price: float,
    *,
    tick: float = 0.01,
) -> list[float]:
    """Return passive-to-marketable buy limits without exceeding the edge cap."""
    bid = float(bid or 0.0)
    ask = float(ask or 0.0)
    maximum_price = float(maximum_price or 0.0)
    if bid <= 0 or ask < bid or maximum_price <= 0 or tick <= 0:
        return []
    ceiling = min(ask, maximum_price)
    midpoint = round((bid + ask) / 2.0 / tick) * tick
    raw = [midpoint, midpoint + tick, ceiling]
    prices: list[float] = []
    for value in raw:
        price = round(min(max(value, bid), ceiling) + 1e-12, 2)
        if price > 0 and price <= maximum_price + 1e-9 and price not in prices:
            prices.append(price)
    return prices


def marketable_exit_limits(
    bid: float,
    *,
    tick: float = 0.01,
    concessions: int = 2,
) -> list[float]:
    """Return aggressive sell limits; never emits a market order sentinel."""
    bid = float(bid or 0.0)
    if bid <= 0 or tick <= 0:
        return []
    return [
        round(max(tick, bid - tick * step), 2)
        for step in range(max(0, concessions) + 1)
    ]


def executable_ev_lower_bound(
    returns_pct: Iterable[float],
    *,
    extra_cost_pct: float = 0.0,
    z_score: float = 1.645,
) -> dict[str, Any]:
    """One-sided normal lower confidence bound on cost-adjusted returns."""
    values = [float(value) for value in returns_pct if _number(value) is not None]
    count = len(values)
    if count < 2:
        return {
            "count": count,
            "mean_return_pct": None,
            "standard_error_pct": None,
            "executable_ev_lower_bound_pct": None,
            "status": "insufficient_sample",
        }
    mean = sum(values) / count
    variance = sum((value - mean) ** 2 for value in values) / (count - 1)
    standard_error = math.sqrt(max(0.0, variance)) / math.sqrt(count)
    lower = mean - z_score * standard_error - max(0.0, float(extra_cost_pct or 0.0))
    return {
        "count": count,
        "mean_return_pct": round(mean, 4),
        "standard_error_pct": round(standard_error, 4),
        "extra_cost_pct": round(max(0.0, float(extra_cost_pct or 0.0)), 4),
        "z_score": z_score,
        "executable_ev_lower_bound_pct": round(lower, 4),
        "status": "positive" if lower > 0 else "non_positive",
    }


def edge_gate_decision(
    report: dict[str, Any],
    *,
    symbol: str,
    strategy: str,
    time_bucket: str | None = None,
) -> dict[str, Any]:
    """Resolve the most-specific preregistered paper gate cohort."""
    symbol = str(symbol or "").upper()
    strategy = str(strategy or "unknown")
    requested = []
    if time_bucket:
        requested.append(("setup_symbol_time", f"{symbol}|{strategy}|{time_bucket}"))
    requested.append(("setup_symbol", f"{symbol}|{strategy}"))
    cohorts = report.get("cohorts") if isinstance(report, dict) else []
    for cohort_type, cohort_name in requested:
        cohort = next(
            (
                row for row in cohorts or []
                if row.get("cohort_type") == cohort_type and row.get("cohort") == cohort_name
            ),
            None,
        )
        if not cohort:
            continue
        lower = _number((cohort.get("chronological_holdout") or {}).get("executable_ev_lower_bound_pct"))
        ready = bool(cohort.get("paper_gate_ready")) and lower is not None and lower > 0
        return {
            "allowed": ready,
            "reason": "positive_executable_ev_lower_bound" if ready else "executable_ev_gate_not_ready",
            "cohort_type": cohort_type,
            "cohort": cohort_name,
            "lower_bound_pct": lower,
            "blockers": list(cohort.get("paper_gate_blockers") or []),
            "report_generated_at": report.get("generated_at"),
        }
    return {
        "allowed": False,
        "reason": "executable_ev_cohort_missing",
        "cohort_type": requested[-1][0],
        "cohort": requested[-1][1],
        "lower_bound_pct": None,
        "blockers": ["cohort_missing"],
        "report_generated_at": report.get("generated_at") if isinstance(report, dict) else None,
    }


def evaluate_underlying_exit(
    trade: dict[str, Any],
    mark: dict[str, Any],
    *,
    pnl_pct: float,
    now: datetime | None = None,
    time_stop_minutes: int = 25,
) -> dict[str, Any]:
    """Evaluate thesis invalidation and stagnation from the underlying.

    Option-premium catastrophe stops stay outside this function as an emergency
    fail-safe. This controller exits because the underlying thesis failed.
    """
    now = now or datetime.now(timezone.utc)
    close = _number(mark.get("underlying_close"))
    prior = _number(mark.get("underlying_prior_5m_close"))
    vwap = _number(mark.get("underlying_vwap"))
    right = str(trade.get("right") or "").upper()
    if right not in {"CALL", "PUT"} or close is None:
        return {"exit": False, "reason": None, "status": "underlying_data_incomplete"}

    structure = _number(trade.get("underlying_structure_level"))
    if structure is not None and prior is not None:
        if right == "CALL" and close < structure and prior < structure and (vwap is None or close < vwap):
            return {
                "exit": True,
                "reason": f"UNDERLYING THESIS INVALIDATED close={close:.2f} level={structure:.2f}",
                "status": "structure_invalidated",
            }
        if right == "PUT" and close > structure and prior > structure and (vwap is None or close > vwap):
            return {
                "exit": True,
                "reason": f"UNDERLYING THESIS INVALIDATED close={close:.2f} level={structure:.2f}",
                "status": "structure_invalidated",
            }

    entry_underlying = _number(trade.get("entry_underlying_price"))
    entry_at = trade.get("entry_at")
    try:
        parsed = datetime.fromisoformat(str(entry_at).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        minutes_open = max(0.0, (now.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 60.0)
    except (TypeError, ValueError):
        minutes_open = None
    stalled = (
        entry_underlying is not None
        and ((right == "CALL" and close <= entry_underlying) or (right == "PUT" and close >= entry_underlying))
    )
    if minutes_open is not None and minutes_open >= time_stop_minutes and pnl_pct <= 0 and stalled:
        return {
            "exit": True,
            "reason": f"UNDERLYING TIME STOP {minutes_open:.0f}m no progress",
            "status": "time_stop",
        }
    return {"exit": False, "reason": None, "status": "thesis_intact"}


def rank_instruments(candidates: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Rank SPY/XSP/SPX candidates by conservative net expected payoff."""
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        gross = _number(candidate.get("gross_expected_payoff"))
        costs = {
            "spread_cost": _number(candidate.get("spread_cost")) or 0.0,
            "fees": _number(candidate.get("fees")) or 0.0,
            "slippage": _number(candidate.get("slippage")) or 0.0,
            "staleness_penalty": _number(candidate.get("staleness_penalty")) or 0.0,
            "model_uncertainty": _number(candidate.get("model_uncertainty")) or 0.0,
        }
        supported = bool(candidate.get("broker_support_verified"))
        authoritative = str(candidate.get("quote_authority") or "") == "opra"
        net = gross - sum(costs.values()) if gross is not None else None
        eligible = supported and authoritative and net is not None and net > 0
        rows.append(
            {
                **candidate,
                **costs,
                "net_expected_payoff": round(net, 4) if net is not None else None,
                "eligible": eligible,
                "ineligibility_reasons": [
                    reason
                    for condition, reason in (
                        (not supported, "broker_support_unverified"),
                        (not authoritative, "opra_quote_required"),
                        (net is None, "expected_payoff_unavailable"),
                        (net is not None and net <= 0, "net_expected_payoff_not_positive"),
                    )
                    if condition
                ],
            }
        )
    rows.sort(key=lambda row: row.get("net_expected_payoff") if row.get("net_expected_payoff") is not None else -math.inf, reverse=True)
    return {
        "mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "ranked": rows,
        "selected": next((row for row in rows if row.get("eligible")), None),
    }
