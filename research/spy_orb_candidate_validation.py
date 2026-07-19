#!/usr/bin/env python3
"""Robustness report for the preregistered SPY 15m ORB + RVOL candidate."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.spy_orb_edge_lab import LabConfig, load_bars, metrics, replay

OUTPUT = Path.home() / ".vibe-trading" / "reports" / "spy-orb-candidate-validation.json"


def bootstrap_mean(values: list[float], samples: int = 10_000, seed: int = 20260719) -> dict:
    if not values:
        return {"mean_r": None, "ci95": [None, None], "probability_positive": None}
    rng = np.random.default_rng(seed)
    array = np.asarray(values, dtype=float)
    means = rng.choice(array, size=(samples, len(array)), replace=True).mean(axis=1)
    return {
        "mean_r": round(float(array.mean()), 4),
        "ci95": [round(float(np.quantile(means, 0.025)), 4), round(float(np.quantile(means, 0.975)), 4)],
        "probability_positive": round(float((means > 0).mean()), 4),
    }


def candidate_trades(slippage_bps: float) -> list[dict]:
    bars = load_bars("2022-01-01", None, False)
    config = replace(
        LabConfig(), opening_minutes=15, last_entry_et=time(10, 30),
        reward_risk=1.5, slippage_bps_per_side=slippage_bps,
    )
    return replay(bars, config)["relative_open_volume"]


def main() -> int:
    trades = candidate_trades(1.0)
    split = int(len(trades) * 0.70)
    holdout = trades[split:]
    yearly = {}
    for year in sorted({trade["date"][:4] for trade in trades}):
        yearly[year] = metrics([trade for trade in trades if trade["date"].startswith(year)])
    stressed = candidate_trades(2.0)
    stressed_split = int(len(stressed) * 0.70)
    report = {
        "strategy": "SPY 15-minute ORB with opening RVOL >= prior 20-session mean",
        "mode": "shadow_candidate",
        "execution_enabled": False,
        "rules": {
            "opening_range": "09:30-09:44 ET", "last_entry": "10:30 ET",
            "entry": "next 5-minute bar open after first close outside range",
            "stop": "opposite side of opening range", "target": "1.5R",
            "volume_gate": "09:30-09:34 volume >= prior 20-session mean",
            "maximum_trades_per_day": 1,
        },
        "base_costs": {"slippage_bps_per_side": 1.0},
        "train": metrics(trades[:split]),
        "holdout": metrics(holdout),
        "holdout_bootstrap": bootstrap_mean([float(trade["net_r"]) for trade in holdout]),
        "yearly": yearly,
        "double_slippage_holdout": metrics(stressed[stressed_split:]),
        "confidence_score": 5.5,
        "confidence_constraints": [
            "Holdout expectancy is positive but its bootstrap interval may include zero.",
            "IEX bars omit some consolidated-market prints.",
            "No historical option bid/ask P&L has been tested.",
            "The candidate was discovered within a finite sensitivity grid and needs a fresh untouched forward sample.",
        ],
        "promotion_gate": "30+ new forward signals, positive net expectancy, profit factor >= 1.15, and option bid/ask replay",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
