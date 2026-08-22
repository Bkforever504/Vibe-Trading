#!/usr/bin/env python3
"""Measure whether human approve/skip choices add forward shadow value."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.assisted_shadow_desk import DEFAULT_JOURNAL, load_states


DEFAULT_OUTPUT = Path("data/assisted_shadow_edge_report.json")


def _cohort(values: list[float]) -> dict[str, Any]:
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    expectancy = statistics.fmean(values) if values else None
    if len(values) >= 2:
        standard_error = statistics.stdev(values) / math.sqrt(len(values))
        lower_95 = expectancy - 1.96 * standard_error
    else:
        lower_95 = None
    loss_total = abs(sum(losses))
    profit_factor = sum(wins) / loss_total if loss_total > 0 else None
    return {
        "resolved_count": len(values),
        "expectancy": round(expectancy, 6) if expectancy is not None else None,
        "win_rate": round(len(wins) / len(values), 6) if values else None,
        "profit_factor": round(profit_factor, 6) if profit_factor is not None else None,
        "lower_95_expectancy": round(lower_95, 6) if lower_95 is not None else None,
        "total_net_pnl": round(sum(values), 6),
    }


def build_report(journal: Path = DEFAULT_JOURNAL) -> dict[str, Any]:
    states = load_states(journal)
    approved: list[float] = []
    skipped: list[float] = []
    dates: set[str] = set()
    for state in states.values():
        if state.decision is None or state.resolution is None:
            continue
        values = approved if state.decision["decision"] == "approve" else skipped
        values.append(float(state.resolution["net_pnl"]))
        dates.add(str(state.packet["created_at"])[:10])
    approve_stats = _cohort(approved)
    skip_stats = _cohort(skipped)
    delta = None
    if approve_stats["expectancy"] is not None and skip_stats["expectancy"] is not None:
        delta = approve_stats["expectancy"] - skip_stats["expectancy"]
    checks = {
        "approved_n_at_least_30": len(approved) >= 30,
        "skipped_n_at_least_30": len(skipped) >= 30,
        "distinct_dates_at_least_20": len(dates) >= 20,
        "approved_expectancy_positive": (approve_stats["expectancy"] or 0) > 0,
        "approved_profit_factor_at_least_1_20": (approve_stats["profit_factor"] or 0) >= 1.20,
        "approved_lower_95_expectancy_positive": (approve_stats["lower_95_expectancy"] or 0) > 0,
        "selection_delta_positive": (delta or 0) > 0,
    }
    return {
        "provider": "assisted_shadow_edge_report",
        "mode": "forward_only_counterfactual_shadow",
        "execution_enabled": False,
        "can_submit_orders": False,
        "approved": approve_stats,
        "skipped": skip_stats,
        "approve_minus_skip_expectancy": round(delta, 6) if delta is not None else None,
        "distinct_session_dates": len(dates),
        "review_checks": checks,
        "review_eligible": all(checks.values()),
        "warning": (
            "Human selection is not an edge until preregistered forward cohorts pass every check. "
            "This report has no execution authority."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(args.journal)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
