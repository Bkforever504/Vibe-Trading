#!/usr/bin/env python3
"""Stress executable one-contract MES finalists without routing orders."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.mes_futures_strategy_search import Candidate, _by_date, _configs, _slice
from strategies.topstep_prop_bot import load_candles_csv
from strategies.topstep_replay_backtester import run_backtest


FINALISTS = (
    Candidate("pullback", 3.0, 2.5, 60, 16, "full_target_stop", "trend20"),
    Candidate("pullback", 3.0, 1.0, 80, 16, "full_target_stop", "trend20"),
)


def monte_carlo(
    pnls: list[float], *, account: float = 1_000.0, samples: int = 20_000, seed: int = 20260719
) -> dict[str, float | int | list[float]]:
    if not pnls:
        return {"samples": samples, "trades_per_path": 0}
    rng = np.random.default_rng(seed)
    paths = rng.choice(np.asarray(pnls, dtype=float), size=(samples, len(pnls)), replace=True).cumsum(axis=1)
    equity = account + paths
    peaks = np.maximum.accumulate(np.concatenate((np.full((samples, 1), account), equity), axis=1), axis=1)[:, 1:]
    drawdowns = (peaks - equity).max(axis=1)
    endings = paths[:, -1]
    return {
        "samples": samples,
        "trades_per_path": len(pnls),
        "ending_pnl_p05_p50_p95": [round(float(np.quantile(endings, q)), 2) for q in (0.05, 0.50, 0.95)],
        "max_drawdown_p50_p95": [round(float(np.quantile(drawdowns, q)), 2) for q in (0.50, 0.95)],
        "probability_30pct_drawdown": round(float((drawdowns >= account * 0.30).mean()), 4),
        "probability_50pct_drawdown": round(float((drawdowns >= account * 0.50).mean()), 4),
        "probability_ending_loss": round(float((endings < 0).mean()), 4),
        "probability_account_ruin": round(float((equity.min(axis=1) <= 0).mean()), 4),
    }


def evaluate(csv_path: Path, account: float, samples: int) -> dict[str, object]:
    candles = load_candles_csv(csv_path)
    dates, grouped = _by_date(candles)
    holdout_start = int(len(dates) * 0.80)
    periods = {"full": dates, "holdout": dates[holdout_start:]}
    rows = []
    for candidate in FINALISTS:
        row: dict[str, object] = {"candidate": asdict(candidate), "periods": {}}
        for period_name, period_dates in periods.items():
            subset = _slice(grouped, period_dates)
            period: dict[str, object] = {}
            for cost_multiple in (1, 2, 3):
                orb, bt = _configs(candidate, doubled_costs=cost_multiple > 1)
                if cost_multiple == 3:
                    bt = type(bt)(**{**asdict(bt), "slippage_ticks": 3, "commission_per_rt": 12.0})
                result = run_backtest(subset, orb_config=orb, bt_config=bt, symbol="MES")
                period[f"cost_{cost_multiple}x"] = {
                    "trades": result.days_traded,
                    "total_pnl": result.total_pnl,
                    "expectancy": result.expectancy,
                    "profit_factor": result.profit_factor,
                    "max_drawdown": result.max_drawdown,
                    "win_rate": result.win_rate,
                    "monte_carlo": monte_carlo([trade.pnl for trade in result.trades], account=account, samples=samples),
                }
            row["periods"][period_name] = period  # type: ignore[index]
        rows.append(row)
    return {"dataset": str(csv_path), "account": account, "results": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=ROOT / "examples" / "es_1h_730d_fresh.csv")
    parser.add_argument("--account", type=float, default=1_000.0)
    parser.add_argument("--samples", type=int, default=20_000)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "mes_candidate_stress.json")
    args = parser.parse_args()
    report = evaluate(args.csv, args.account, args.samples)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
