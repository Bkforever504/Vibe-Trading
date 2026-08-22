"""Shared, read-only decision intelligence for Alpaca and Topstep candidates.

This module combines independent evidence families, data health, regime fit,
execution economics, and evidence maturity. It deliberately cannot submit an
order. Broker adapters retain all execution authority and safety checks.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable


INTELLIGENCE_VERSION = "cross-market-intelligence-v1"
VALID_DIRECTIONS = {"bullish", "bearish", "neutral", "unknown"}


@dataclass(frozen=True)
class Evidence:
    source: str
    family: str
    direction: str
    confidence: float
    reliability: float = 1.0
    fresh: bool = True
    validated: bool = False
    detail: str = ""


@dataclass(frozen=True)
class IntelligenceConfig:
    minimum_independent_families: int = 2
    minimum_data_completeness: float = 0.65
    maximum_conflict_ratio: float = 0.35
    minimum_support_ratio: float = 0.60
    minimum_reward_risk: float = 1.0
    maximum_friction_to_reward: float = 0.35


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return low
    if not math.isfinite(parsed):
        return low
    return min(high, max(low, parsed))


def _direction(value: Any) -> str:
    normalized = str(value or "unknown").strip().lower()
    return normalized if normalized in VALID_DIRECTIONS else "unknown"


def _finite_optional(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _entropy(probability: float) -> float:
    probability = _clamp(probability)
    if probability in {0.0, 1.0}:
        return 0.0
    return -(probability * math.log2(probability) + (1.0 - probability) * math.log2(1.0 - probability))


def _collapse_correlated_evidence(evidence: Iterable[Evidence]) -> list[Evidence]:
    """Keep one strongest observation per correlation family.

    Multiple indicators derived from the same price series are not independent
    confirmations. Selecting one family representative prevents confidence
    inflation from indicator stacking.
    """
    selected: dict[str, Evidence] = {}
    for item in evidence:
        if not item.fresh or _direction(item.direction) in {"neutral", "unknown"}:
            continue
        family = str(item.family or item.source).strip().lower()
        strength = _clamp(item.confidence) * _clamp(item.reliability) * (1.0 if item.validated else 0.60)
        existing = selected.get(family)
        if existing is None:
            selected[family] = item
            continue
        existing_strength = (
            _clamp(existing.confidence)
            * _clamp(existing.reliability)
            * (1.0 if existing.validated else 0.60)
        )
        if strength > existing_strength:
            selected[family] = item
    return list(selected.values())


def assess_decision_intelligence(
    *,
    candidate_id: str,
    desired_direction: str,
    evidence: Iterable[Evidence],
    hard_blockers: Iterable[str] = (),
    data_completeness: float,
    regime: str = "unknown",
    regime_compatible: bool | None = None,
    reward_risk: float | None = None,
    friction_to_reward: float | None = None,
    forward_validated_edge: bool = False,
    config: IntelligenceConfig = IntelligenceConfig(),
) -> dict[str, Any]:
    desired = _direction(desired_direction)
    blockers = sorted({str(item) for item in hard_blockers if str(item)})
    evidence_rows = list(evidence)
    collapsed = _collapse_correlated_evidence(evidence_rows)
    support_rows: list[tuple[Evidence, float]] = []
    conflict_rows: list[tuple[Evidence, float]] = []
    for item in collapsed:
        weight = _clamp(item.confidence) * _clamp(item.reliability) * (1.0 if item.validated else 0.60)
        if _direction(item.direction) == desired:
            support_rows.append((item, weight))
        else:
            conflict_rows.append((item, weight))

    support_weight = sum(weight for _, weight in support_rows)
    conflict_weight = sum(weight for _, weight in conflict_rows)
    total_weight = support_weight + conflict_weight
    support_ratio = support_weight / total_weight if total_weight else 0.5
    conflict_ratio = conflict_weight / total_weight if total_weight else 0.5
    uncertainty = _entropy(support_ratio)
    completeness = _clamp(data_completeness)
    rr = _finite_optional(reward_risk)
    friction_value = _finite_optional(friction_to_reward)
    friction = max(0.0, friction_value) if friction_value is not None else None
    economics_ok = (
        rr is not None
        and rr >= config.minimum_reward_risk
        and friction is not None
        and friction <= config.maximum_friction_to_reward
    )
    independent_support = len(support_rows)

    reasons: list[str] = []
    missing: list[str] = []
    if desired == "unknown":
        blockers.append("candidate_direction_unknown")
    if completeness < config.minimum_data_completeness:
        reasons.append("data_completeness_below_threshold")
        missing.append("required_context")
    if independent_support < config.minimum_independent_families:
        reasons.append("insufficient_independent_evidence_families")
        missing.append("independent_confirmation")
    if conflict_ratio > config.maximum_conflict_ratio:
        reasons.append("evidence_conflict_too_high")
    if support_ratio < config.minimum_support_ratio:
        reasons.append("support_ratio_below_threshold")
    if regime_compatible is False:
        reasons.append("strategy_regime_mismatch")
    elif regime_compatible is None:
        missing.append("regime_compatibility")
    if not economics_ok:
        reasons.append("execution_economics_not_proven")
        if rr is None or friction is None:
            missing.append("execution_economics")
    if not forward_validated_edge:
        reasons.append("forward_validated_edge_absent")

    if blockers:
        status = "blocked"
        recommendation = "stand_aside"
    elif any(reason in reasons for reason in (
        "data_completeness_below_threshold",
        "evidence_conflict_too_high",
        "support_ratio_below_threshold",
        "strategy_regime_mismatch",
        "execution_economics_not_proven",
    )):
        status = "abstain"
        recommendation = "collect_counterfactual_only"
    elif not forward_validated_edge or independent_support < config.minimum_independent_families:
        status = "shadow_observe"
        recommendation = "observe_without_promotion"
    else:
        status = "paper_candidate"
        recommendation = "eligible_for_existing_paper_gates"

    independence_score = min(1.0, independent_support / max(1, config.minimum_independent_families))
    regime_score = 1.0 if regime_compatible is True else 0.5 if regime_compatible is None else 0.0
    economics_score = 1.0 if economics_ok else 0.0
    maturity_score = 1.0 if forward_validated_edge else 0.0
    intelligence_score = 100.0 * (
        0.25 * support_ratio
        + 0.20 * independence_score
        + 0.15 * completeness
        + 0.15 * regime_score
        + 0.15 * economics_score
        + 0.10 * maturity_score
    ) * (1.0 - 0.5 * conflict_ratio)

    payload = {
        "version": INTELLIGENCE_VERSION,
        "candidate_id": candidate_id,
        "desired_direction": desired,
        "regime": str(regime or "unknown"),
        "regime_compatible": regime_compatible,
        "status": status,
        "recommendation": recommendation,
        "intelligence_score": round(intelligence_score, 2),
        "support_ratio": round(support_ratio, 4),
        "conflict_ratio": round(conflict_ratio, 4),
        "uncertainty_entropy": round(uncertainty, 4),
        "data_completeness": round(completeness, 4),
        "independent_support_families": independent_support,
        "supporting_evidence": [dict(asdict(item), effective_weight=round(weight, 4)) for item, weight in support_rows],
        "conflicting_evidence": [dict(asdict(item), effective_weight=round(weight, 4)) for item, weight in conflict_rows],
        "correlated_evidence_collapsed": max(0, len(evidence_rows) - len(collapsed)),
        "reward_risk": round(rr, 4) if rr is not None else None,
        "friction_to_reward": round(friction, 4) if friction is not None else None,
        "execution_economics_ok": economics_ok,
        "forward_validated_edge": bool(forward_validated_edge),
        "reasons": sorted(set(reasons)),
        "hard_blockers": blockers,
        "missing_information": sorted(set(missing)),
        "execution_enabled": False,
        "can_submit_orders": False,
        "can_increase_size": False,
        "authority": "advisory_and_abstention_research_only",
    }
    payload["assessment_id"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()[:24]
    return payload
