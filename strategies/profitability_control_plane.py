"""Unified, broker-free capital allocation and counterfactual control plane.

Every strategy competes with cash under the same conservative economics.  The
module has no broker imports and cannot submit orders.  Its output may demote a
paper candidate to exploration, but it cannot promote a strategy or increase
size without the existing evidence and human-review gates.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


CONTROL_VERSION = "profitability-control-plane-v1"
CAPITAL_ELIGIBLE_STATES = {"paper_approved", "live_approved"}
RETIRED_STATES = {"retired", "suspended", "research_only"}


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _weighted_quantile(values: list[tuple[float, float]], quantile: float) -> float:
    rows = sorted((value, max(0.0, weight)) for value, weight in values if math.isfinite(value))
    total = sum(weight for _, weight in rows)
    if not rows or total <= 0:
        return 0.0
    target = min(1.0, max(0.0, quantile)) * total
    running = 0.0
    for value, weight in rows:
        running += weight
        if running >= target:
            return value
    return rows[-1][0]


def regime_weighted_loss_buffer(
    residuals: Iterable[dict[str, Any]],
    *,
    current_regime: str,
    quantile: float = 0.90,
    decay: float = 0.94,
) -> float:
    """Return a one-sided buffer for losses underestimated by the model.

    ``adverse_error`` is positive when realized PnL was worse than forecast.
    Recent, same-regime errors receive more weight.  This is an operational
    conformal-style calibration, not a claim of formal coverage under drift.
    """
    rows = list(residuals)
    weighted: list[tuple[float, float]] = []
    for age, row in enumerate(reversed(rows)):
        error = _finite(row.get("adverse_error"))
        if error is None:
            continue
        regime_multiplier = 1.0 if str(row.get("regime") or "unknown") == current_regime else 0.35
        weighted.append((max(0.0, error), (decay**age) * regime_multiplier))
    return round(_weighted_quantile(weighted, quantile), 6)


@dataclass(frozen=True)
class OpportunityCandidate:
    candidate_id: str
    lane: str
    risk_cluster: str
    expected_pnl: float | None
    lower_confidence_pnl: float | None
    estimated_round_trip_cost: float | None
    max_loss: float | None
    current_signal: bool
    lifecycle_state: str
    paper_review_eligible: bool
    data_status: str = "current"
    regime: str = "unknown"
    regime_compatible: bool | None = None
    forward_observations: int = 0
    residuals: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    source: str = "unknown"


@dataclass(frozen=True)
class ControlConfig:
    account_equity: float = 25_000.0
    max_daily_risk_fraction: float = 0.005
    max_candidate_risk_fraction: float = 0.0025
    max_cluster_risk_fraction: float = 0.0035
    minimum_forward_observations: int = 30
    loss_buffer_quantile: float = 0.90


def evaluate_candidate(
    candidate: OpportunityCandidate,
    *,
    config: ControlConfig = ControlConfig(),
) -> dict[str, Any]:
    blockers: list[str] = []
    if not candidate.current_signal:
        blockers.append("no_current_signal")
    if candidate.data_status != "current":
        blockers.append(f"data_{candidate.data_status}")
    if candidate.lifecycle_state in RETIRED_STATES:
        blockers.append(f"lifecycle_{candidate.lifecycle_state}")
    if candidate.lifecycle_state not in CAPITAL_ELIGIBLE_STATES:
        blockers.append("lifecycle_not_capital_approved")
    if not candidate.paper_review_eligible:
        blockers.append("paper_review_not_eligible")
    if candidate.forward_observations < config.minimum_forward_observations:
        blockers.append("insufficient_forward_observations")
    if candidate.regime_compatible is False:
        blockers.append("regime_mismatch")

    expected = _finite(candidate.expected_pnl)
    lower = _finite(candidate.lower_confidence_pnl)
    cost = _finite(candidate.estimated_round_trip_cost)
    max_loss = _finite(candidate.max_loss)
    if expected is None:
        blockers.append("expected_pnl_missing")
    if lower is None:
        blockers.append("lower_confidence_bound_missing")
    if cost is None:
        blockers.append("round_trip_cost_missing")
    if max_loss is None or max_loss <= 0:
        blockers.append("defined_max_loss_missing")

    buffer = regime_weighted_loss_buffer(
        candidate.residuals,
        current_regime=candidate.regime,
        quantile=config.loss_buffer_quantile,
    )
    after_cost_lower = lower - cost - buffer if lower is not None and cost is not None else None
    if after_cost_lower is None or after_cost_lower <= 0:
        blockers.append("after_cost_lower_bound_not_positive")

    per_candidate_budget = config.account_equity * config.max_candidate_risk_fraction
    contracts = int(per_candidate_budget // max_loss) if max_loss and max_loss > 0 else 0
    if contracts < 1:
        blockers.append("risk_budget_cannot_fund_one_unit")

    eligible = not blockers
    return {
        **asdict(candidate),
        "conformal_style_loss_buffer": buffer,
        "after_cost_lower_confidence_pnl": round(after_cost_lower, 6) if after_cost_lower is not None else None,
        "capital_eligible": eligible,
        "recommended_units": contracts if eligible else 0,
        "blockers": sorted(set(blockers)),
        "shadow_action": "observe_and_resolve" if candidate.current_signal else "await_signal",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def run_opportunity_exchange(
    candidates: Iterable[OpportunityCandidate],
    *,
    config: ControlConfig = ControlConfig(),
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    evaluated = [evaluate_candidate(candidate, config=config) for candidate in candidates]
    ranked = sorted(
        evaluated,
        key=lambda row: (
            bool(row["capital_eligible"]),
            _finite(row.get("after_cost_lower_confidence_pnl")) or float("-inf"),
        ),
        reverse=True,
    )

    selected: list[dict[str, Any]] = []
    used_clusters: set[str] = set()
    remaining_daily_risk = config.account_equity * config.max_daily_risk_fraction
    cluster_budget = config.account_equity * config.max_cluster_risk_fraction
    for row in ranked:
        if not row["capital_eligible"] or row["risk_cluster"] in used_clusters:
            continue
        max_loss = float(row["max_loss"])
        units = min(
            int(row["recommended_units"]),
            int(remaining_daily_risk // max_loss),
            int(cluster_budget // max_loss),
        )
        if units < 1:
            continue
        selected.append({
            "candidate_id": row["candidate_id"],
            "lane": row["lane"],
            "risk_cluster": row["risk_cluster"],
            "recommended_units": units,
            "reserved_max_loss": round(units * max_loss, 2),
            "after_cost_lower_confidence_pnl": row["after_cost_lower_confidence_pnl"],
        })
        used_clusters.add(row["risk_cluster"])
        remaining_daily_risk -= units * max_loss

    timestamp = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    action = "paper_candidates_available" if selected else "hold_cash_collect_counterfactuals"
    report = {
        "schema_version": 1,
        "control_version": CONTROL_VERSION,
        "generated_at": timestamp.isoformat().replace("+00:00", "Z"),
        "capital_decision": {
            "action": action,
            "cash_is_explicit_competitor": True,
            "selected": selected,
            "remaining_daily_risk_budget": round(remaining_daily_risk, 2),
        },
        "candidates": ranked,
        "counterfactual_capture": {
            "required_for_every_signal": [
                "take_at_executable_quote",
                "abstain_cash_benchmark",
                "delayed_entry_same_policy",
                "opposite_direction_same_risk",
                "policy_exit_and_realized_exit",
            ],
            "promotion_rule": "Only preregistered forward outcomes may change lifecycle state.",
        },
        "guardrails": {
            "confidence_scores_cannot_override_failed_evidence": True,
            "one_selected_candidate_per_risk_cluster": True,
            "maximum_daily_risk_fraction": config.max_daily_risk_fraction,
            "maximum_candidate_risk_fraction": config.max_candidate_risk_fraction,
            "maximum_cluster_risk_fraction": config.max_cluster_risk_fraction,
            "automatic_live_promotion": False,
        },
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
    }
    report["decision_id"] = hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()[:24]
    return report

