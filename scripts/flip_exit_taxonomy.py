"""Canonical Flip exit-quality taxonomy shared by read-only analytics."""
from __future__ import annotations

from typing import Any


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_exit_quality(
    best_pnl_pct: Any,
    exit_return_pct: Any,
    exit_reason: Any = None,
) -> dict[str, Any]:
    """Separate profitable capture from losses that only had favorable excursion."""
    best = _number(best_pnl_pct)
    realized = _number(exit_return_pct)
    reason = str(exit_reason or "").lower()
    result: dict[str, Any] = {
        "best_pnl_pct": round(best, 2) if best is not None else None,
        "exit_return_pct": round(realized, 2) if realized is not None else None,
        "exit_quality_classification": "insufficient_data",
        "winner_capture_eligible": False,
        "capture_efficiency": None,
        "giveback_pct": None,
        "favorable_excursion_surrendered_pct": None,
    }
    if best is None or realized is None:
        return result

    if realized > 0:
        result["exit_quality_classification"] = (
            "profitable_exit_capture" if best > 0 else "profitable_exit_without_observed_mfe"
        )
        if best > 0:
            result["winner_capture_eligible"] = True
            result["capture_efficiency"] = round(realized / best, 3)
            result["giveback_pct"] = round(max(0.0, best - realized), 2)
        return result

    if realized == 0:
        result["exit_quality_classification"] = (
            "flat_exit_after_favorable_excursion" if best > 0 else "flat_exit"
        )
    elif "stop" in reason:
        result["exit_quality_classification"] = (
            "stop_loss_after_favorable_excursion" if best > 0 else "stop_loss_no_favorable_excursion"
        )
    else:
        result["exit_quality_classification"] = (
            "losing_exit_after_favorable_excursion" if best > 0 else "losing_exit_no_favorable_excursion"
        )
    if best > 0:
        result["favorable_excursion_surrendered_pct"] = round(best - realized, 2)
    return result

