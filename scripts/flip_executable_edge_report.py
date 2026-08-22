#!/usr/bin/env python3
"""Build a chronological executable-EV report for the Flip paper gate.

The report uses shadow entries priced at ask and exits priced at bid. It
excludes explicitly designated design days, applies a chronological holdout,
and computes a one-sided lower confidence bound. It cannot submit orders.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.flip_shadow_time_bucket_report import _group_shadow_rows, _read_jsonl
from scripts.flip_shadow_pnl_evaluator import RESEARCH_ONLY_STRATEGIES
from strategies.spy_spx_execution_policy import executable_ev_lower_bound


SOURCE_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "flip-executable-edge.json"
LOG_PATH = ROOT / "data" / "flip_executable_edge_log.jsonl"
EXCLUDED_DESIGN_DATES = {"2026-08-04"}
MIN_COMPLETED = 100
MIN_HOLDOUT = 30
MIN_DATES = 20
MIN_QUOTE_COVERAGE = 0.95


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    all_returns = [
        value
        for row in rows
        if (value := _number(row.get("evidence_exit_return_pct"))) is not None
    ]
    quote_complete = [row for row in rows if row.get("executable_quote_coverage")]
    executable_rows = [
        row for row in rows
        if row.get("executable_quote_coverage")
        and _number(row.get("evidence_exit_return_pct")) is not None
    ]
    executable_returns = [float(row["evidence_exit_return_pct"]) for row in executable_rows]
    extra_costs = []
    for row in executable_rows:
        ask = _number(row.get("executable_entry_ask"))
        spread = (_number(row.get("best_spread_cents")) or 0.0) / 100.0
        if ask and ask > 0:
            extra_costs.append(spread / ask * 100.0)
    extra_cost = sum(extra_costs) / len(extra_costs) if len(extra_costs) == len(executable_rows) and extra_costs else 0.0
    bound = executable_ev_lower_bound(executable_returns, extra_cost_pct=extra_cost)
    return {
        "count": len(rows),
        "return_observation_count": len(all_returns),
        "executable_observation_count": len(executable_rows),
        "executable_quote_coverage": round(len(quote_complete) / len(rows), 4) if rows else 0.0,
        "doubled_cost_penalty_pct": round(extra_cost, 4),
        **bound,
    }


def _cohort(cohort_type: str, name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (str(row.get("date") or ""), str(row.get("entry_seen_at") or "")))
    dates = sorted({str(row.get("date") or "")[:10] for row in ordered if row.get("date")})
    split = min(len(dates) - 1, max(1, math.ceil(len(dates) * 0.70))) if len(dates) >= 2 else len(dates)
    training_dates = set(dates[:split])
    holdout_dates = set(dates[split:])
    training = [row for row in ordered if str(row.get("date") or "")[:10] in training_dates]
    holdout = [row for row in ordered if str(row.get("date") or "")[:10] in holdout_dates]
    full_metrics = _metrics(ordered)
    holdout_metrics = _metrics(holdout)
    blockers = []
    if len(ordered) < MIN_COMPLETED:
        blockers.append("fewer_than_100_completed")
    if len(holdout) < MIN_HOLDOUT:
        blockers.append("fewer_than_30_chronological_holdout")
    if len(dates) < MIN_DATES:
        blockers.append("fewer_than_20_distinct_dates")
    if float(full_metrics.get("executable_quote_coverage") or 0.0) < MIN_QUOTE_COVERAGE:
        blockers.append("executable_quote_coverage_below_95pct")
    if (_number(full_metrics.get("executable_ev_lower_bound_pct")) or -math.inf) <= 0:
        blockers.append("full_executable_ev_lower_bound_not_positive")
    if (_number(holdout_metrics.get("executable_ev_lower_bound_pct")) or -math.inf) <= 0:
        blockers.append("holdout_executable_ev_lower_bound_not_positive")
    return {
        "cohort_type": cohort_type,
        "cohort": name,
        "distinct_dates": len(dates),
        "training": _metrics(training),
        "chronological_holdout": holdout_metrics,
        "full": full_metrics,
        "paper_gate_ready": not blockers,
        "live_gate_ready": False,
        "paper_gate_blockers": blockers,
    }


def build_report(source_path: Path = SOURCE_PATH) -> dict[str, Any]:
    trades = [
        row for row in _group_shadow_rows(_read_jsonl(source_path))
        if str(row.get("strategy") or "") not in RESEARCH_ONLY_STRATEGIES
        and str(row.get("date") or "")[:10] not in EXCLUDED_DESIGN_DATES
    ]
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        symbol = str(trade.get("symbol") or "unknown").upper()
        strategy = str(trade.get("strategy") or "unknown")
        bucket = str(trade.get("episode_bucket_et") or "unknown")
        grouped[("setup_symbol", f"{symbol}|{strategy}")].append(trade)
        grouped[("setup_symbol_time", f"{symbol}|{strategy}|{bucket}")].append(trade)
    cohorts = [
        _cohort(cohort_type, name, rows)
        for (cohort_type, name), rows in sorted(grouped.items())
    ]
    cohorts.sort(
        key=lambda row: (
            bool(row.get("paper_gate_ready")),
            _number((row.get("chronological_holdout") or {}).get("executable_ev_lower_bound_pct")) or -math.inf,
        ),
        reverse=True,
    )
    return {
        "provider": "flip_executable_edge_report",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_path": str(source_path),
        "mode": "paper_gate_evidence",
        "execution_enabled": False,
        "can_submit_orders": False,
        "excluded_design_dates": sorted(EXCLUDED_DESIGN_DATES),
        "requirements": {
            "completed": MIN_COMPLETED,
            "chronological_holdout": MIN_HOLDOUT,
            "distinct_dates": MIN_DATES,
            "executable_quote_coverage": MIN_QUOTE_COVERAGE,
            "positive_full_and_holdout_lower_bound": True,
            "cost_model": "entry_ask_exit_bid_plus_one_additional_observed_spread",
        },
        "completed_lifecycle_count": len(trades),
        "cohort_count": len(cohorts),
        "paper_gate_ready_count": sum(bool(row.get("paper_gate_ready")) for row in cohorts),
        "cohorts": cohorts,
        "warnings": [
            "This report can block Alpaca paper entries but cannot enable live execution.",
            "A positive historical mean is insufficient; the chronological holdout lower bound must be positive.",
            "The August 4 design day is excluded from promotion evidence.",
        ],
    }


def _write(path: Path, report: dict[str, Any], *, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if append:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n")
        return
    temp = path.with_suffix(
        path.suffix + f".tmp-{os.getpid()}-{datetime.now(timezone.utc).timestamp()}"
    )
    try:
        temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--log", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(args.source)
    _write(args.output, report)
    _write(args.log, report, append=True)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Flip executable edge report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
