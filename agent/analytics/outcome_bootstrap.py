"""Stationary-block bootstrap confidence intervals for dependent outcomes."""
from __future__ import annotations

import hashlib
import inspect
import math
import warnings
from importlib.metadata import version
from typing import Any, Callable, Iterable

import numpy as np
from arch.bootstrap import optimal_block_length
from tsbootstrap import StationaryBlock, bootstrap

MIN_N = 20
MIN_ITERATIONS = 1000


def _source_version() -> str:
    return hashlib.sha256(inspect.getsource(inspect.getmodule(_source_version)).encode()).hexdigest()[:12]


def library_versions() -> dict[str, str]:
    values = {name: version(name) for name in ("arch", "tsbootstrap", "numpy")}
    values["hash"] = hashlib.sha256(repr(sorted(values.items())).encode()).hexdigest()[:12]
    return values


def _values(series: Iterable[float]) -> np.ndarray:
    values = np.asarray(list(series), dtype=float).reshape(-1)
    return values[np.isfinite(values)]


def optimal_stationary_block_size(series: Iterable[float]) -> int | None:
    values = _values(series)
    if len(values) < 2:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        estimate = float(optimal_block_length(values)["stationary"].iloc[0])
    if not math.isfinite(estimate):
        return 1
    return max(1, min(len(values), int(math.ceil(estimate))))


def mean_expectancy(values: np.ndarray) -> float:
    return float(np.mean(values))


def win_rate(values: np.ndarray) -> float:
    return float(np.mean(values > 0))


def sharpe(values: np.ndarray) -> float:
    std = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    return float(np.mean(values) / std) if std > 0 else 0.0


def max_drawdown(values: np.ndarray) -> float:
    curve = np.cumsum(values)
    peaks = np.maximum.accumulate(np.r_[0.0, curve])
    drawdowns = peaks[1:] - curve
    return float(np.max(drawdowns)) if len(drawdowns) else 0.0


def latency_p50(values: np.ndarray) -> float:
    return float(np.percentile(values, 50))


def latency_p95(values: np.ndarray) -> float:
    return float(np.percentile(values, 95))


def bootstrap_ci(series: Iterable[float], statistic_fn: Callable[[np.ndarray], float],
                 iterations: int = MIN_ITERATIONS, ci: float = 0.95,
                 random_state: int = 20260905) -> dict[str, Any]:
    values = _values(series)
    iterations = max(MIN_ITERATIONS, int(iterations))
    versions = library_versions()
    base = {"n": len(values), "t": None, "b": None, "k": iterations,
            "block_size": None, "iterations": iterations,
            "model_version": _source_version(), "library_versions": versions,
            "library_version_hash": versions["hash"], "execution_enabled": False,
            "can_submit_orders": False}
    if len(values) < MIN_N:
        return {**base, "point": None, "ci_low": None, "ci_high": None,
                "reason": "insufficient_data"}
    if not 0 < ci < 1:
        raise ValueError("ci must be between zero and one")
    block_size = optimal_stationary_block_size(values)
    if block_size is None:
        return {**base, "point": None, "ci_low": None, "ci_high": None,
                "reason": "optimal_block_length_unavailable"}
    result = bootstrap(values, method=StationaryBlock(avg_block_length=block_size),
                       n_bootstraps=iterations, random_state=random_state)
    estimates = np.asarray([statistic_fn(np.asarray(sample.values, dtype=float))
                            for sample in result.iter_samples()], dtype=float)
    alpha = (1.0 - ci) / 2.0
    return {**base, "point": float(statistic_fn(values)),
            "ci_low": float(np.quantile(estimates, alpha)),
            "ci_high": float(np.quantile(estimates, 1.0 - alpha)),
            "b": block_size, "block_size": block_size, "reason": None}
