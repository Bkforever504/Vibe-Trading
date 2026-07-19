#!/usr/bin/env python3
"""Bootstrap and year-stability checks for leading volume-overlay hypotheses."""
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

from research.spy_orb_edge_lab import LabConfig, load_bars, replay
from research.spy_orb_volume_lab import _selected, adjusted_metrics, augment, intraday_features
from research.volume_overlay_lab import FILTERS, _metrics, build_strategy_trades, load_daily

OUTPUT = Path.home() / ".vibe-trading" / "reports" / "volume-candidate-validation.json"


def bootstrap(values: list[float], seed: int, samples: int = 10_000) -> dict:
    if not values:
        return {"mean": None, "ci95": [None, None], "probability_positive": None}
    rng = np.random.default_rng(seed)
    array = np.asarray(values, dtype=float)
    means = rng.choice(array, size=(samples, len(array)), replace=True).mean(axis=1)
    return {
        "mean": round(float(array.mean()), 6),
        "ci95": [round(float(np.quantile(means, 0.025)), 6), round(float(np.quantile(means, 0.975)), 6)],
        "probability_positive": round(float((means > 0).mean()), 4),
    }


def daily_candidates() -> list[dict]:
    trades = build_strategy_trades("QQQ", load_daily("QQQ"))["rsi2_prior_high_QQQ"]
    cutoff = trades[max(0, int(len(trades) * 0.70) - 1)]["decision_date"]
    rows = []
    for filter_name in ("rvol_ge_1", "rvol_ge_1_25", "volume_z_ge_1", "volume_osc_positive", "mavd_positive"):
        selected = []
        for trade in trades:
            import pandas as pd
            row = pd.Series(trade["features"])
            if not row.isna().any() and FILTERS[filter_name](row, int(trade["direction"])):
                selected.append(trade)
        holdout = [trade for trade in selected if trade["decision_date"] > cutoff]
        net_values = [float(trade["raw_return"]) - 4 / 10_000 for trade in holdout]
        yearly = {year: _metrics([trade for trade in selected if trade["decision_date"].startswith(year)]) for year in sorted({trade["decision_date"][:4] for trade in selected})}
        rows.append({
            "strategy": "rsi2_prior_high_QQQ", "filter": filter_name, "cutoff_date": cutoff,
            "holdout": _metrics(holdout), "holdout_bootstrap": bootstrap(net_values, 100 + len(rows)),
            "yearly": yearly,
        })
    return rows


def orb_candidate() -> dict:
    bars = load_bars("2022-01-01", None, False)
    config = replace(LabConfig(), opening_minutes=15, reward_risk=2.0, last_entry_et=time(10, 30))
    trades = augment(replay(bars, config)["baseline"], intraday_features(bars))
    cutoff = trades[max(0, int(len(trades) * 0.70) - 1)]["date"]
    selected = _selected(trades, "cmf_direction")
    holdout = [trade for trade in selected if trade["date"] > cutoff]
    values = [float(trade["net_r"]) for trade in holdout]
    yearly = {year: adjusted_metrics([trade for trade in selected if trade["date"].startswith(year)]) for year in sorted({trade["date"][:4] for trade in selected})}
    return {
        "strategy": "spy_15m_orb_2r", "filter": "cmf_direction", "cutoff_date": cutoff,
        "holdout": adjusted_metrics(holdout), "double_cost_holdout": adjusted_metrics(holdout, 1.0),
        "holdout_bootstrap": bootstrap(values, 200), "yearly": yearly,
    }


def main() -> int:
    rows = daily_candidates() + [orb_candidate()]
    for row in rows:
        years = list(row["yearly"].values())
        key = "expectancy_r" if row["strategy"].startswith("spy_15m") else "expectancy_bps"
        positive_years = sum((year.get(key) or 0) > 0 for year in years)
        row["positive_year_fraction"] = round(positive_years / len(years), 3) if years else 0
        ci_low = row["holdout_bootstrap"]["ci95"][0]
        row["post_selection_screen_pass"] = bool(ci_low is not None and ci_low > 0 and row["positive_year_fraction"] >= 0.75)
        row["high_confidence_ready"] = False
        row["forward_promotion_ready"] = False
        row["remaining_gates"] = [
            "30+ untouched shadow signals",
            "venue-specific realized quote costs",
            "independent data not used in configuration selection",
            "multiple-testing-aware review",
        ]
    report = {
        "mode": "research_only", "execution_enabled": False, "rows": rows,
        "post_selection_screen_pass_count": sum(row["post_selection_screen_pass"] for row in rows),
        "high_confidence_ready_count": 0,
        "forward_promotion_ready_count": 0,
        "note": "No candidate may affect execution without untouched forward validation and venue-specific quote costs.",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
