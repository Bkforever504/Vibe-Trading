"""Paired stationary-bootstrap confidence interval for pipeline comparisons."""
from __future__ import annotations

from typing import Any, Iterable

import numpy as np

from agent.analytics.outcome_bootstrap import bootstrap_ci, mean_expectancy


def paired_diff_ci(series_a: Iterable[float], series_b: Iterable[float],
                   iterations: int = 1000, ci: float = 0.95,
                   random_state: int = 20260905) -> dict[str, Any]:
    left = np.asarray(list(series_a), dtype=float).reshape(-1)
    right = np.asarray(list(series_b), dtype=float).reshape(-1)
    if len(left) != len(right):
        raise ValueError("paired series must have equal length")
    if not np.all(np.isfinite(left)) or not np.all(np.isfinite(right)):
        raise ValueError("paired series must contain only finite values")
    result = bootstrap_ci(right - left, mean_expectancy, iterations=iterations,
                          ci=ci, random_state=random_state)
    return {**result, "diff_mean": result.get("point"),
            "diff_ci_low": result.get("ci_low"), "diff_ci_high": result.get("ci_high"),
            "excludes_zero": bool(result.get("ci_low") is not None and
                                  (result["ci_low"] > 0 or result["ci_high"] < 0)),
            "comparison": "series_b_minus_series_a"}

