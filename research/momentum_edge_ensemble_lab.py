#!/usr/bin/env python3
"""Preregistered, research-only momentum edge ensemble.

This module combines three previously defined momentum sleeves. It has no
broker imports, order methods, or execution authority.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.pyquant_strategy_family_lab import (
    CANONICAL,
    COST_PER_TRADED_NOTIONAL,
    SECTORS,
    _scheduled_rank_weights,
    fetch_closes,
    strategy_returns,
)


DEFAULT_OUTPUT = ROOT / "data" / "momentum_edge_ensemble_results.json"
ALL_SYMBOLS = tuple(dict.fromkeys((*SECTORS, *CANONICAL)))
MAX_ASSET_WEIGHT = 0.35


def build_ensemble_weights(closes: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Build the one-third-per-sleeve portfolio fixed in the preregistration."""
    missing = sorted(set(ALL_SYMBOLS) - set(closes.columns))
    if missing:
        raise ValueError(f"missing required symbols: {', '.join(missing)}")

    sector = closes.loc[:, list(SECTORS)]
    canonical = closes.loc[:, list(CANONICAL)]
    sector_momentum = _scheduled_rank_weights(
        sector,
        lookback=252,
        top_n=3,
        rebalance_days=None,
    )
    positive_12m = sector.pct_change(252) > 0
    sector_low_vol = _scheduled_rank_weights(
        sector,
        lookback=63,
        top_n=3,
        rebalance_days=None,
        lowest=True,
        eligibility=positive_12m,
    )
    canonical_momentum = _scheduled_rank_weights(
        canonical,
        lookback=252,
        top_n=2,
        rebalance_days=5,
    )

    sleeves = {
        "sector_momentum_12m_top3_monthly": sector_momentum,
        "sector_low_vol_positive_momentum_top3_monthly": sector_low_vol,
        "canonical_12m_top2_weekly": canonical_momentum,
    }
    combined = pd.DataFrame(0.0, index=closes.index, columns=list(ALL_SYMBOLS))
    for sleeve in sleeves.values():
        combined = combined.add(sleeve.reindex(columns=combined.columns, fill_value=0.0), fill_value=0.0)
    combined = (combined / len(sleeves)).clip(lower=0.0, upper=MAX_ASSET_WEIGHT)
    return combined, sleeves


def _metrics(returns: pd.Series) -> dict[str, Any]:
    clean = returns.dropna().astype(float)
    if clean.empty:
        return {"observations": 0}
    equity = (1.0 + clean).cumprod()
    years = len(clean) / 252.0
    ending = float(equity.iloc[-1])
    cagr = ending ** (1.0 / years) - 1.0 if years > 0 and ending > 0 else -1.0
    standard_deviation = float(clean.std(ddof=1)) if len(clean) > 1 else 0.0
    annual_volatility = standard_deviation * math.sqrt(252.0)
    sharpe = float(clean.mean() / standard_deviation * math.sqrt(252.0)) if standard_deviation else 0.0
    drawdown = equity / equity.cummax() - 1.0
    yearly = (1.0 + clean).groupby(clean.index.year).prod() - 1.0
    remove_count = max(1, math.ceil(len(clean) * 0.01))
    best_dates = clean.nlargest(remove_count).index
    trimmed = clean.copy()
    trimmed.loc[best_dates] = 0.0
    trimmed_equity = float((1.0 + trimmed).prod())
    trimmed_cagr = trimmed_equity ** (1.0 / years) - 1.0 if trimmed_equity > 0 else -1.0
    max_drawdown = abs(float(drawdown.min()))
    return {
        "observations": int(len(clean)),
        "start": str(clean.index[0].date()),
        "end": str(clean.index[-1].date()),
        "total_return_pct": round((ending - 1.0) * 100.0, 3),
        "cagr_pct": round(cagr * 100.0, 3),
        "annual_volatility_pct": round(annual_volatility * 100.0, 3),
        "sharpe_ratio": round(sharpe, 3),
        "max_drawdown_pct": round(max_drawdown * 100.0, 3),
        "calmar_ratio": round(cagr / max_drawdown, 3) if max_drawdown else None,
        "positive_year_rate": round(float((yearly > 0).mean()), 3),
        "worst_year_pct": round(float(yearly.min()) * 100.0, 3),
        "best_one_pct_removed_cagr_pct": round(trimmed_cagr * 100.0, 3),
    }


def _windows(returns: pd.Series) -> dict[str, dict[str, Any]]:
    return {
        "development_2007_2021": _metrics(returns.loc[:"2021-12-31"]),
        "selection_2022_2024": _metrics(returns.loc["2022-01-01":"2024-12-31"]),
        "final_diagnostic_2025_plus": _metrics(returns.loc["2025-01-01":]),
    }


def run_lab(closes: pd.DataFrame | None = None) -> dict[str, Any]:
    prices = fetch_closes(ALL_SYMBOLS, start="2007-01-01") if closes is None else closes.copy()
    prices = prices.loc[:, list(ALL_SYMBOLS)].dropna().sort_index()
    weights, sleeves = build_ensemble_weights(prices)
    active = weights.sum(axis=1) > 0
    if not active.any():
        raise ValueError("ensemble produced no active observations")
    start = active[active].index[0]

    base = strategy_returns(prices, weights, cost_per_notional=COST_PER_TRADED_NOTIONAL).loc[start:]
    stressed = strategy_returns(
        prices,
        weights,
        cost_per_notional=COST_PER_TRADED_NOTIONAL * 2.0,
    ).loc[start:]
    benchmark = prices["SPY"].pct_change().fillna(0.0).loc[start:]
    base_windows = _windows(base)
    benchmark_windows = _windows(benchmark)
    overall = _metrics(base)
    benchmark_overall = _metrics(benchmark)
    stressed_overall = _metrics(stressed)

    selection = base_windows["selection_2022_2024"]
    final = base_windows["final_diagnostic_2025_plus"]
    benchmark_selection = benchmark_windows["selection_2022_2024"]
    benchmark_final = benchmark_windows["final_diagnostic_2025_plus"]
    maximum_weight = float(weights.max().max())
    gates = {
        "selection_cagr_positive": selection.get("cagr_pct", -1.0) > 0,
        "final_diagnostic_cagr_positive": final.get("cagr_pct", -1.0) > 0,
        "overall_sharpe_above_spy": overall.get("sharpe_ratio", 0.0) > benchmark_overall.get("sharpe_ratio", 0.0),
        "overall_drawdown_below_spy": overall.get("max_drawdown_pct", 100.0) < benchmark_overall.get("max_drawdown_pct", 100.0),
        "selection_drawdown_below_spy": selection.get("max_drawdown_pct", 100.0) < benchmark_selection.get("max_drawdown_pct", 100.0),
        "final_drawdown_below_spy": final.get("max_drawdown_pct", 100.0) < benchmark_final.get("max_drawdown_pct", 100.0),
        "double_cost_cagr_positive": stressed_overall.get("cagr_pct", -1.0) > 0,
        "best_one_pct_removed_cagr_positive": overall.get("best_one_pct_removed_cagr_pct", -1.0) > 0,
        "maximum_asset_weight_lte_35pct": maximum_weight <= MAX_ASSET_WEIGHT + 1e-12,
    }
    all_pass = all(gates.values())
    return {
        "schema_version": 1,
        "protocol": "MOMENTUM_EDGE_ENSEMBLE_V1_2026-08-17",
        "mode": "research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "configuration_count": 1,
        "rules": {
            "sleeves": list(sleeves),
            "sleeve_weight": round(1.0 / len(sleeves), 6),
            "maximum_asset_weight": MAX_ASSET_WEIGHT,
            "unallocated_weight": "cash",
            "signal_execution_lag_days": 1,
            "base_cost_per_traded_notional": COST_PER_TRADED_NOTIONAL,
            "stress_cost_per_traded_notional": COST_PER_TRADED_NOTIONAL * 2.0,
        },
        "overall": overall,
        "windows": base_windows,
        "benchmark_spy": {"overall": benchmark_overall, "windows": benchmark_windows},
        "double_cost": {"overall": stressed_overall, "windows": _windows(stressed)},
        "portfolio_diagnostics": {
            "maximum_asset_weight": round(maximum_weight, 6),
            "average_invested_weight": round(float(weights.sum(axis=1).loc[start:].mean()), 6),
        },
        "gates": {**gates, "all_pass": all_pass},
        "decision": "forward_shadow_candidate" if all_pass else "rejected",
        "promotion_authority": "forward_shadow_only" if all_pass else "blocked",
        "minimum_forward_review": {
            "completed_monthly_observations": 12,
            "elapsed_trading_sessions": 252,
        },
        "warnings": [
            "The component sleeves were chosen after historical results were observed.",
            "The final diagnostic is not a pristine holdout and cannot authorize capital.",
            "ETF adjusted closes are research marks, not broker-confirmed fills.",
            "Universe membership is static and contains survivorship bias.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run_lab()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
