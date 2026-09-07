#!/usr/bin/env python3
"""Pure shadow-only alert utility and uncertainty primitives.

The functions in this module never create a trading decision.  They schedule,
abstain, or annotate candidates that have already passed the deterministic
scanner gates.  A positive result cannot remove an upstream blocker.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence


AUTHORITY = {"execution_enabled": False, "can_submit_orders": False}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _stamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile_requires_values")
    index = min(len(ordered) - 1, max(0, math.ceil(probability * len(ordered)) - 1))
    return ordered[index]


def estimate_alert_half_life(
    outcomes: Iterable[Mapping[str, Any]],
    *,
    setup_family: str,
    regime: str,
    as_of: datetime,
    min_samples: int = 30,
    fallback_seconds: int = 180,
) -> dict[str, Any]:
    """Estimate opportunity survival from resolved, strictly prior observations.

    ``valid_for_seconds`` is the observed time until a chase, stop, or remaining
    reward/risk boundary failed.  Censored and unresolved rows are deliberately
    excluded from this first conservative implementation.
    """
    cutoff = _stamp(as_of)
    if cutoff is None:
        raise ValueError("as_of_required")
    samples: list[float] = []
    rejected_future = 0
    for row in outcomes:
        if str(row.get("setup_family") or "") != setup_family or str(row.get("regime") or "") != regime:
            continue
        resolved = _stamp(row.get("resolved_at"))
        valid_for = _number(row.get("valid_for_seconds"))
        if resolved is None or valid_for is None or valid_for < 0:
            continue
        if resolved >= cutoff:
            rejected_future += 1
            continue
        samples.append(valid_for)
    sufficient = len(samples) >= min_samples
    half_life = _quantile(samples, 0.5) if sufficient else float(fallback_seconds)
    conservative = _quantile(samples, 0.25) if sufficient else float(fallback_seconds)
    return {
        "status": "estimated" if sufficient else "insufficient_data",
        "setup_family": setup_family,
        "regime": regime,
        "eligible_samples": len(samples),
        "future_rows_rejected": rejected_future,
        "half_life_seconds": round(half_life, 3),
        "conservative_validity_seconds": round(conservative, 3),
        "fallback_used": not sufficient,
        "fallback_seconds": fallback_seconds,
        "automatic_promotion": False,
        **AUTHORITY,
    }


def build_action_deadline(
    candidate: Mapping[str, Any],
    half_life: Mapping[str, Any],
    *,
    now: datetime,
    predicted_transport_seconds: float = 1.0,
    human_delay_seconds: float = 15.0,
) -> dict[str, Any]:
    signal_at = _stamp(candidate.get("signal_available_at") or candidate.get("bar_completed_at"))
    current = _stamp(now)
    validity = _number(half_life.get("conservative_validity_seconds"))
    if signal_at is None or current is None or validity is None:
        return {"status": "unavailable", "reason": "timestamp_or_half_life_missing", **AUTHORITY}
    deadline = signal_at + timedelta(seconds=validity)
    slack = (deadline - current).total_seconds() - max(0.0, predicted_transport_seconds) - max(0.0, human_delay_seconds)
    blockers = list(candidate.get("blockers") or [])
    return {
        "status": "blocked_upstream" if blockers else "actionable" if slack >= 0 else "expired",
        "action_deadline_ts": deadline.isoformat().replace("+00:00", "Z"),
        "seconds_of_slack": round(slack, 3),
        "do_not_page_reason": "upstream_blocker" if blockers else "insufficient_slack" if slack < 0 else None,
        "upstream_blockers_preserved": blockers,
        **AUTHORITY,
    }


def adaptive_conformal_abstention(
    prediction: float,
    calibration_rows: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime,
    economic_threshold: float,
    coverage: float = 0.90,
    min_samples: int = 30,
) -> dict[str, Any]:
    """Return an abstention card using only errors resolved before ``as_of``."""
    point = _number(prediction)
    cutoff = _stamp(as_of)
    if point is None or cutoff is None or not 0 < coverage < 1:
        return {"status": "unavailable", "decision": "ABSTAIN", "reason": "invalid_inputs", **AUTHORITY}
    errors: list[float] = []
    future_rows = 0
    for row in calibration_rows:
        resolved = _stamp(row.get("resolved_at"))
        forecast, actual = _number(row.get("prediction")), _number(row.get("actual"))
        if resolved is None or forecast is None or actual is None:
            continue
        if resolved >= cutoff:
            future_rows += 1
            continue
        errors.append(abs(actual - forecast))
    if len(errors) < min_samples:
        return {
            "status": "insufficient_data", "decision": "ABSTAIN",
            "eligible_samples": len(errors), "future_rows_rejected": future_rows,
            "reason": "minimum_calibration_samples_not_met", **AUTHORITY,
        }
    radius = _quantile(errors, coverage)
    lower, upper = point - radius, point + radius
    decision = "RETAIN" if lower >= economic_threshold else "ABSTAIN"
    return {
        "status": "calibrated", "decision": decision,
        "prediction": point, "interval": [round(lower, 6), round(upper, 6)],
        "coverage_target": coverage, "eligible_samples": len(errors),
        "future_rows_rejected": future_rows,
        "reason": None if decision == "RETAIN" else "lower_bound_below_economic_threshold",
        "authority": "abstain_only_never_upgrade_or_unveto", **AUTHORITY,
    }


def _cosine(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    keys = set(left) | set(right)
    a = [_number(left.get(key)) or 0.0 for key in keys]
    b = [_number(right.get(key)) or 0.0 for key in keys]
    norm = math.sqrt(sum(value * value for value in a)) * math.sqrt(sum(value * value for value in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0


def diversify_discord_queue(
    candidates: Iterable[Mapping[str, Any]],
    *,
    capacity: int,
    reserved_symbols: Sequence[str] = ("SPY", "QQQ", "DELL"),
    redundancy_penalty: float = 0.35,
) -> dict[str, Any]:
    """Select distinct actionable ideas while retaining every row in the ledger."""
    rows = [dict(row) for row in candidates]
    eligible = [row for row in rows if not row.get("blockers") and _number(row.get("utility_score")) is not None]
    selected: list[dict[str, Any]] = []
    reserved = {symbol.upper() for symbol in reserved_symbols}
    for symbol in reserved_symbols:
        matches = [row for row in eligible if str(row.get("symbol") or "").upper() == symbol.upper()]
        if matches and len(selected) < capacity:
            winner = max(matches, key=lambda row: float(row["utility_score"]))
            if winner not in selected:
                selected.append(winner)
    while len(selected) < capacity:
        remaining = [row for row in eligible if row not in selected]
        if not remaining:
            break
        def marginal(row: Mapping[str, Any]) -> float:
            similarity = max((_cosine(row.get("exposure_vector") or {}, chosen.get("exposure_vector") or {}) for chosen in selected), default=0.0)
            return float(row["utility_score"]) - redundancy_penalty * 100.0 * max(0.0, similarity)
        selected.append(max(remaining, key=lambda row: (marginal(row), float(row["utility_score"]))))
    selected_ids = {str(row.get("candidate_id") or id(row)) for row in selected}
    companions: dict[str, list[str]] = defaultdict(list)
    for row in eligible:
        row_id = str(row.get("candidate_id") or id(row))
        if row_id in selected_ids or not selected:
            continue
        closest = max(selected, key=lambda chosen: _cosine(row.get("exposure_vector") or {}, chosen.get("exposure_vector") or {}))
        companions[str(closest.get("candidate_id") or closest.get("symbol"))].append(str(row.get("symbol") or row_id))
    return {
        "status": "ranked", "capacity": capacity,
        "selected": selected, "correlated_companions": dict(companions),
        "all_candidates_retained": rows,
        "reserved_symbols": sorted(reserved),
        "reserved_missing": sorted(symbol for symbol in reserved if not any(str(row.get("symbol") or "").upper() == symbol for row in rows)),
        "selection_authority": "shadow_alternative_queue_only", **AUTHORITY,
    }


def schedule_by_action_deadline(
    candidates: Iterable[Mapping[str, Any]], *, capacity: int,
) -> dict[str, Any]:
    """Order already-eligible candidates by usable deadline, then utility."""
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in candidates:
        row = dict(raw)
        card = row.get("alert_deadline_shadow") if isinstance(row.get("alert_deadline_shadow"), Mapping) else {}
        deadline = _stamp(card.get("action_deadline_ts"))
        utility = _number(row.get("utility_score"))
        if row.get("blockers") or card.get("status") != "actionable" or deadline is None or utility is None:
            rejected.append({"candidate_id": row.get("candidate_id"), "reason": card.get("do_not_page_reason") or "deadline_or_utility_unavailable"})
            continue
        row["_deadline"] = deadline
        eligible.append(row)
    eligible.sort(key=lambda row: (row["_deadline"], -float(row["utility_score"]), str(row.get("candidate_id") or "")))
    selected = []
    for row in eligible[:max(0, capacity)]:
        row.pop("_deadline", None)
        selected.append(row)
    return {
        "status": "scheduled" if selected else "no_actionable_candidates",
        "policy": "earliest_actionable_deadline_then_utility",
        "selected": selected,
        "rejected": rejected,
        "automatic_dispatch": False,
        **AUTHORITY,
    }


def event_intensity_challenger(
    recent_counts: Mapping[str, Any],
    baseline_rates: Mapping[str, Any],
    *,
    persistence_windows: int,
    minimum_ratio: float = 2.0,
) -> dict[str, Any]:
    ratios: dict[str, float] = {}
    for name in ("aggressive_trades", "quote_changes", "cancels", "price_ticks"):
        recent, baseline = _number(recent_counts.get(name)), _number(baseline_rates.get(name))
        if recent is not None and baseline is not None and baseline > 0:
            ratios[name] = round(recent / baseline, 4)
    if len(ratios) < 2:
        return {"status": "unavailable", "state": "UNKNOWN", "reason": "insufficient_event_channels", **AUTHORITY}
    accelerated = sum(value >= minimum_ratio for value in ratios.values()) >= 2 and persistence_windows >= 2
    return {
        "status": "observed", "state": "ACCELERATING" if accelerated else "NORMAL",
        "ratios": ratios, "persistence_windows": persistence_windows,
        "authority": "challenger_context_only_never_standalone_approval", **AUTHORITY,
    }


def market_data_quorum(
    observations: Iterable[Mapping[str, Any]],
    *,
    as_of: datetime,
    minimum_sources: int = 2,
    max_age_seconds: float = 2.0,
    max_midpoint_deviation_bps: float = 3.0,
) -> dict[str, Any]:
    """Compare independently labeled quotes; missing sources never agree by fiat."""
    current = _stamp(as_of)
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in observations:
        source = str(raw.get("source") or "").strip().lower()
        bid, ask = _number(raw.get("bid")), _number(raw.get("ask"))
        observed = _stamp(raw.get("event_at") or raw.get("timestamp"))
        reason = None
        if not source or source in seen:
            reason = "missing_or_duplicate_source"
        elif current is None or observed is None or (current - observed).total_seconds() < 0 or (current - observed).total_seconds() > max_age_seconds:
            reason = "stale_or_unordered"
        elif bid is None or ask is None or bid <= 0 or ask <= 0 or bid > ask:
            reason = "invalid_quote"
        if reason:
            rejected.append({"source": source or None, "reason": reason})
            continue
        seen.add(source)
        valid.append({"source": source, "midpoint": (bid + ask) / 2, "bid": bid, "ask": ask})
    if len(valid) < minimum_sources:
        return {
            "status": "unavailable", "agreement": False,
            "reason": "insufficient_independent_sources", "sources": valid,
            "rejected": rejected, **AUTHORITY,
        }
    midpoints = [row["midpoint"] for row in valid]
    center = sum(midpoints) / len(midpoints)
    deviation = (max(midpoints) - min(midpoints)) / center * 10_000 if center else math.inf
    agreed = deviation <= max_midpoint_deviation_bps
    return {
        "status": "agreed" if agreed else "data_disagreement",
        "agreement": agreed, "maximum_midpoint_deviation_bps": round(deviation, 6),
        "sources": valid, "rejected": rejected,
        "authority": "data_quality_veto_only_cannot_unveto", **AUTHORITY,
    }


def anytime_bounded_mean_interval(values: Sequence[float], *, alpha: float = 0.05) -> dict[str, Any]:
    """A conservative time-uniform interval via an alpha-spending union bound.

    Each value must lie in [0, 1]. At time n, Hoeffding uses
    alpha_n = alpha/(n(n+1)), whose sum over all n is alpha.
    """
    if not values or not 0 < alpha < 1 or any(_number(value) is None or not 0 <= float(value) <= 1 for value in values):
        return {"status": "unavailable", "reason": "bounded_samples_required", **AUTHORITY}
    n = len(values)
    mean = sum(float(value) for value in values) / n
    alpha_n = alpha / (n * (n + 1))
    radius = math.sqrt(math.log(2.0 / alpha_n) / (2.0 * n))
    return {
        "status": "observed", "samples": n, "mean": round(mean, 6),
        "lower": round(max(0.0, mean - radius), 6),
        "upper": round(min(1.0, mean + radius), 6),
        "alpha": alpha, "method": "hoeffding_alpha_spending_union_bound",
        "automatic_promotion": False, **AUTHORITY,
    }
