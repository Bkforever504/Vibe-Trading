#!/usr/bin/env python3
"""Preregistered Treasury cash sleeve for the technology swing portfolio."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.higher_timeframe_volume_screen_lab import load_symbol, period_candidates
from research.swing_risk_overlay_lab import (
    BASELINE,
    DEV_END,
    OVERLAYS,
    SELECTION_END,
    SYMBOLS,
    build_context,
    eligible_candidates,
    exposure_for_overlay,
    gross_period_return,
    metrics,
)


DEFAULT_OUTPUT = ROOT / "data" / "swing_cash_sleeve_results.json"
BASE_OVERLAY = OVERLAYS[0]
BREADTH_OVERLAY = next(row for row in OVERLAYS if row.name == "breadth_scaled")


def asset_period_return(frame: pd.DataFrame, decision_date: str, hold_days: int) -> float:
    future = frame.index[frame.index > pd.Timestamp(decision_date)]
    if future.empty:
        return 0.0
    entry_pos = int(frame.index.get_loc(future[0]))
    exit_pos = entry_pos + hold_days - 1
    if exit_pos >= len(frame):
        return 0.0
    return float(frame["close"].iloc[exit_pos]) / float(frame["open"].iloc[entry_pos]) - 1.0


def blend_return(
    equity_return: float,
    cash_return: float,
    equity_exposure: float,
    cost_bps: float,
    *,
    cost_exposure: float = 1.0,
) -> float:
    if not 0.0 <= equity_exposure <= 1.0:
        raise ValueError("equity exposure must remain between zero and one")
    cash_exposure = 1.0 - equity_exposure
    if not 0.0 <= cost_exposure <= 1.0:
        raise ValueError("cost exposure must remain between zero and one")
    return (
        equity_exposure * equity_return
        + cash_exposure * cash_return
        - cost_exposure * cost_bps / 10_000
    )


def replay_variant(
    frames: dict[str, pd.DataFrame],
    bil: pd.DataFrame,
    candidates: list[dict[str, Any]],
    variant: str,
    *,
    cost_bps: float,
) -> list[dict[str, Any]]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        by_date.setdefault(row["decision_date"], []).append(row)
    rows: list[dict[str, Any]] = []
    for decision_date, date_candidates in sorted(by_date.items()):
        context = build_context(frames, decision_date)
        baseline_selected = eligible_candidates(date_candidates, BASE_OVERLAY, context)
        _, baseline_symbols, _ = gross_period_return(frames, baseline_selected, BASE_OVERLAY)
        if not baseline_symbols:
            continue
        overlay = BASE_OVERLAY if variant == "equal_weight_baseline" else BREADTH_OVERLAY
        selected = eligible_candidates(date_candidates, overlay, context)
        gross, symbols, weights = gross_period_return(frames, selected, overlay)
        exposure = exposure_for_overlay(overlay, context, 0.0)
        cash_return = (
            asset_period_return(bil, decision_date, BASELINE.hold_days)
            if variant == "breadth_bil_cash"
            else 0.0
        )
        equity_cost_exposure = exposure if symbols else 0.0
        cash_cost_exposure = 1.0 - exposure if variant == "breadth_bil_cash" else 0.0
        net = blend_return(
            gross if symbols else 0.0,
            cash_return,
            exposure,
            cost_bps,
            cost_exposure=equity_cost_exposure + cash_cost_exposure,
        )
        rows.append(
            {
                "decision_date": decision_date,
                "return": net,
                "exposure": exposure,
                "weights": weights,
                "symbols": symbols,
                "cash_exposure": 1.0 - exposure,
                "cash_return": cash_return,
            }
        )
    return rows


def split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "development_2015_2022": metrics([row for row in rows if row["decision_date"] <= DEV_END]),
        "selection_2023_2025": metrics([row for row in rows if DEV_END < row["decision_date"] <= SELECTION_END]),
        "final_2026": metrics([row for row in rows if row["decision_date"] > SELECTION_END]),
    }


def improved(candidate: dict[str, Any], baseline: dict[str, Any], window: str) -> dict[str, bool]:
    return {
        f"{window}_equity_improved": candidate[window]["ending_equity"] > baseline[window]["ending_equity"],
        f"{window}_drawdown_reduced": abs(candidate[window]["max_drawdown_pct"]) < abs(baseline[window]["max_drawdown_pct"]),
    }


def build_report() -> dict[str, Any]:
    frames = {symbol: load_symbol(symbol, "2015-01-01", "2026-07-21", False) for symbol in SYMBOLS}
    bil = load_symbol("BIL", "2015-01-01", "2026-07-21", False)
    candidates = [row for symbol, frame in frames.items() for row in period_candidates(symbol, frame, "monthly")]
    variants = ("equal_weight_baseline", "breadth_zero_cash", "breadth_bil_cash")
    results = []
    for variant in variants:
        normal = replay_variant(frames, bil, candidates, variant, cost_bps=10.0)
        stress = replay_variant(frames, bil, candidates, variant, cost_bps=30.0)
        results.append({"variant": variant, **split(normal), "stress": split(stress)})
    baseline = results[0]
    for result in results:
        gates = {
            **improved(result, baseline, "development_2015_2022"),
            **improved(result, baseline, "selection_2023_2025"),
            "stress_positive_all_windows": all(
                (result["stress"][window].get("expectancy_bps") or 0) > 0
                for window in ("development_2015_2022", "selection_2023_2025", "final_2026")
            ),
            "positive_without_top_one_pct_all_windows": all(
                (result[window].get("top_one_pct_removed_expectancy_bps") or 0) > 0
                for window in ("development_2015_2022", "selection_2023_2025", "final_2026")
            ),
            "development_bootstrap_lower_bound_positive": (
                result["development_2015_2022"].get("bootstrap", {}).get("ci95_bps", [None])[0] or 0
            ) > 0,
        }
        result["gates"] = {**gates, "all_pass": all(gates.values())}
        result["shadow_candidate"] = result["variant"] == "breadth_bil_cash" and all(gates.values())
    return {
        "schema_version": 1,
        "protocol": "SWING_CASH_SLEEVE_PREREGISTRATION_2026-08-13",
        "mode": "research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "configuration_count": len(results),
        "results": results,
        "warnings": [
            "Adjusted daily bars are research marks rather than broker quotes.",
            "The equity universe has survivorship bias.",
            "The 2026 comparison is not a pristine independent holdout.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["results"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
