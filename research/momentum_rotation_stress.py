#!/usr/bin/env python3
"""Block-bootstrap Monte Carlo stress for the frozen momentum-rotation candidate.

Uses the candidate's actual daily return series (no new parameters searched).
Promotion-gate reference: MC 95th-percentile drawdown must stay within $300
on the $1,000 model account. Research only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.momentum_rotation_backtest import (
    _momentum_equity_curve,
    _momentum_signal,
    fetch_universe,
)

SYMBOLS = ["SPY", "QQQ", "GLD", "XLE", "TLT", "IWM", "XLK", "XLV", "XLF", "XLI"]
OUT = ROOT / "data" / "momentum_rotation_stress.json"
ACCOUNT = 1000.0
BLOCK_MEAN_DAYS = 21
RESAMPLES = 2000
HORIZON_DAYS = 252
SEED = 20260719


def candidate_daily_returns(cost_pct: float) -> pd.Series:
    universe = fetch_universe(SYMBOLS, "2015-01-01", "2026-07-18")
    signal = _momentum_signal(universe, lookback_days=12 * 21, rebalance_days=5, top_n=2)
    equity = _momentum_equity_curve(universe, signal, slippage_pct=cost_pct, commission_pct=0.0)
    return equity.pct_change().dropna()


def stationary_bootstrap(returns: np.ndarray, rng: np.random.Generator, length: int) -> np.ndarray:
    out = np.empty(length)
    i = rng.integers(0, returns.size)
    p = 1.0 / BLOCK_MEAN_DAYS
    for t in range(length):
        out[t] = returns[i]
        i = rng.integers(0, returns.size) if rng.random() < p else (i + 1) % returns.size
    return out


def max_drawdown_dollars(path: np.ndarray) -> float:
    equity = ACCOUNT * np.cumprod(1.0 + path)
    peak = np.maximum.accumulate(np.concatenate(([ACCOUNT], equity)))[1:]
    return float(np.max(peak - equity))


def stress(returns: pd.Series) -> dict:
    rng = np.random.default_rng(SEED)
    values = returns.to_numpy()
    drawdowns, annual_returns = [], []
    for _ in range(RESAMPLES):
        path = stationary_bootstrap(values, rng, HORIZON_DAYS)
        drawdowns.append(max_drawdown_dollars(path))
        annual_returns.append(float(np.prod(1.0 + path) - 1.0))
    drawdowns = np.array(drawdowns)
    annual_returns = np.array(annual_returns)
    return {
        "resamples": RESAMPLES,
        "horizon_days": HORIZON_DAYS,
        "block_mean_days": BLOCK_MEAN_DAYS,
        "seed": SEED,
        "median_annual_return_pct": round(float(np.median(annual_returns)) * 100.0, 2),
        "p05_annual_return_pct": round(float(np.percentile(annual_returns, 5)) * 100.0, 2),
        "prob_losing_year": round(float((annual_returns < 0).mean()), 4),
        "median_max_drawdown_usd": round(float(np.median(drawdowns)), 2),
        "p95_max_drawdown_usd": round(float(np.percentile(drawdowns, 95)), 2),
        "p99_max_drawdown_usd": round(float(np.percentile(drawdowns, 99)), 2),
        "gate_p95_drawdown_within_300": bool(np.percentile(drawdowns, 95) <= 300.0),
    }


def main() -> None:
    results = {
        "candidate": "frozen 2024 momentum rotation (10 ETF, 12m lookback, top-2, 5d rebalance)",
        "return_series": "2015-01-01 to 2026-07-17 daily, actual candidate equity curve",
        "mode": "research_only",
    }
    for label, cost in (("base_costs", 0.06), ("double_costs", 0.12)):
        returns = candidate_daily_returns(cost)
        results[label] = {
            "observed_days": int(returns.size),
            "stress": stress(returns),
        }
    OUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
