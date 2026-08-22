"""Deterministic, manual-only pattern quality rubric.

The score ranks observable setup quality.  It is not a win probability and it
never grants order authority.  Research priors and locally forward-validated
base rates remain explicitly distinguishable in the returned evidence block.
"""
from __future__ import annotations

import math
from typing import Any, Mapping


RUBRIC_VERSION = "pattern_grade_v1"
WEIGHTS: dict[str, float] = {
    "base_rate": 0.25,
    "volume_rvol": 0.15,
    "mtf_alignment": 0.20,
    "regime_fit": 0.15,
    "confluence": 0.15,
    "reward_risk": 0.10,
}
PENALTY_FACTORS: dict[str, float] = {
    "anti_pattern": 0.5,
    "macro_window": 0.6,
    "wide_spread": 0.7,
    "stale_feed": 0.5,
}


def _score(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return round(max(0.0, min(100.0, number)), 2)


def _grade(score: float) -> str:
    if score >= 85.0:
        return "A"
    if score >= 70.0:
        return "B"
    if score >= 55.0:
        return "C"
    return "D"


def score_pattern_grade(
    *,
    components: Mapping[str, Any],
    penalties: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the canonical A/B/C/D score with transparent evidence labels."""
    supplied = dict(components)
    normalized = {
        name: _score(supplied.get(name), 55.0 if name == "base_rate" else 0.0)
        for name in WEIGHTS
    }
    evidence_labels = dict(evidence or {})
    if "base_rate" not in supplied:
        evidence_labels["base_rate"] = "unknown_neutral_prior"
    else:
        evidence_labels.setdefault("base_rate", "research_prior_not_local_probability")
    for name in WEIGHTS:
        evidence_labels.setdefault(name, "observed_or_derived")

    base_rate_status = str(evidence_labels.get("base_rate") or "")
    if base_rate_status.startswith("local_forward_validated"):
        validation_status = "LOCAL_FORWARD_VALIDATED"
    elif "research_prior" in base_rate_status:
        validation_status = "RESEARCH_PRIOR"
    else:
        validation_status = "UNCALIBRATED"

    raw_score = round(sum(normalized[name] * weight for name, weight in WEIGHTS.items()), 2)
    requested_penalties = dict(penalties or {})
    applied = {
        name: (factor if bool(requested_penalties.get(name, False)) else 1.0)
        for name, factor in PENALTY_FACTORS.items()
    }
    multiplier = math.prod(applied.values())
    final_score = round(raw_score * multiplier, 2)
    grade = _grade(final_score)
    all_aligned = (
        grade == "A"
        and multiplier == 1.0
        and normalized["volume_rvol"] >= 70.0
        and normalized["mtf_alignment"] >= 70.0
        and normalized["regime_fit"] >= 70.0
        and normalized["reward_risk"] >= 75.0
    )
    if all_aligned:
        label = "ALL_OBSERVED_CONDITIONS_ALIGNED"
    elif grade == "A":
        label = "HIGH_QUALITY_MANUAL_REVIEW"
    elif grade == "B":
        label = "CONDITIONAL_MANUAL_REVIEW"
    elif grade == "C":
        label = "WATCH_ONLY"
    else:
        label = "PASS"

    warnings = ["Pattern grade ranks observable setup quality; it is not a win probability."]
    if validation_status != "LOCAL_FORWARD_VALIDATED":
        warnings.append("The pattern base rate is not locally forward-validated for this instrument and timeframe.")

    return {
        "rubric_version": RUBRIC_VERSION,
        "components": normalized,
        "weights": dict(WEIGHTS),
        "raw_score": raw_score,
        "penalty_factors": applied,
        "penalty_multiplier": round(multiplier, 4),
        "final_score": final_score,
        "grade": grade,
        "label": label,
        "all_observed_conditions_aligned": all_aligned,
        "validation_status": validation_status,
        "evidence": evidence_labels,
        "warnings": warnings,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


__all__ = ["PENALTY_FACTORS", "RUBRIC_VERSION", "WEIGHTS", "score_pattern_grade"]
