#!/usr/bin/env python3
"""Run the single frozen MES MBO absorption hypothesis on discovery sessions."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.mes_mbo_phase_a import audit_records
DEFAULT_INPUTS = (
    ROOT / "data" / "databento" / "mes_v0_mbo_2026-07-16.dbn.zst",
    ROOT / "data" / "databento" / "mes_v0_mbo_2026-07-20.dbn.zst",
)
DEFAULT_OUTPUT = ROOT / "data" / "mes_mbo_absorption_discovery.json"
FILL_THRESHOLD = 0.43
CANCEL_ADD_THRESHOLD = 0.067
DEPTH_THRESHOLD = 0.48
MES_DOLLARS_PER_POINT = 5.0
ROUND_TRIP_FEES = 2.48
STRESS_FEES = 4.96
STRESS_SLIPPAGE_DOLLARS = 2.50


def direction(row: dict[str, Any]) -> int:
    values = (
        row.get("passive_fill_imbalance"),
        row.get("cancel_add_pressure"),
        row.get("depth_imbalance"),
    )
    if any(value is None for value in values):
        return 0
    fill, pressure, depth = (float(value) for value in values)
    if fill >= FILL_THRESHOLD and pressure >= CANCEL_ADD_THRESHOLD and depth >= DEPTH_THRESHOLD:
        return 1
    if fill <= -FILL_THRESHOLD and pressure <= -CANCEL_ADD_THRESHOLD and depth <= -DEPTH_THRESHOLD:
        return -1
    return 0


def evaluate_windows(rows: list[dict[str, Any]], session: str) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    blocked_until = -1
    for index, signal in enumerate(rows):
        if index <= blocked_until:
            continue
        side = direction(signal)
        entry_index = index + 1
        exit_index = index + 7
        if side == 0 or exit_index >= len(rows):
            continue
        path = rows[index : exit_index + 1]
        if any(not row.get("valid_book") for row in path):
            continue
        if any(path[offset + 1]["bucket"] != path[offset]["bucket"] + 1 for offset in range(len(path) - 1)):
            continue
        entry = rows[entry_index]
        exit_row = rows[exit_index]
        entry_price = entry["best_ask"] if side == 1 else entry["best_bid"]
        exit_price = exit_row["best_bid"] if side == 1 else exit_row["best_ask"]
        if entry_price is None or exit_price is None:
            continue
        gross_points = side * (int(exit_price) - int(entry_price)) / 1_000_000_000
        gross_dollars = gross_points * MES_DOLLARS_PER_POINT
        net = gross_dollars - ROUND_TRIP_FEES
        stressed = gross_dollars - STRESS_SLIPPAGE_DOLLARS - STRESS_FEES
        trades.append(
            {
                "session": session,
                "signal_bucket": int(signal["bucket"]),
                "direction": "bullish" if side == 1 else "bearish",
                "gross_points": round(gross_points, 4),
                "net_pnl_usd": round(net, 2),
                "stressed_pnl_usd": round(stressed, 2),
            }
        )
        blocked_until = exit_index
    return trades


def metrics(values: list[float]) -> dict[str, Any]:
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    return {
        "count": len(values),
        "total_pnl_usd": round(sum(values), 2),
        "expectancy_usd": round(sum(values) / len(values), 4) if values else None,
        "win_rate": round(len(wins) / len(values), 6) if values else None,
        "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else None,
    }


def build_report(paths: list[Path]) -> dict[str, Any]:
    import databento as db

    trades: list[dict[str, Any]] = []
    quality: dict[str, Any] = {}
    for path in paths:
        session = path.stem.replace(".dbn", "").rsplit("_", 1)[-1]
        audit = audit_records(iter(db.DBNStore.from_file(path)), include_windows=True)
        quality[session] = {
            "event_count": audit["event_count"],
            "rth_event_count": audit["rth_event_count"],
            "windows": audit["windows"],
            "book_state": audit["book_state"],
            "quality_gates": audit["quality_gates"],
        }
        if not audit["quality_gates"]["all_pass"]:
            raise RuntimeError(f"MBO quality gates failed for {session}")
        trades.extend(evaluate_windows(audit.pop("window_rows"), session))

    direction_counts = Counter(row["direction"] for row in trades)
    session_pnl: dict[str, float] = defaultdict(float)
    for row in trades:
        session_pnl[row["session"]] += row["net_pnl_usd"]
    positive_total = sum(value for value in session_pnl.values() if value > 0)
    best_positive_share = (
        max((value for value in session_pnl.values() if value > 0), default=0.0) / positive_total
        if positive_total > 0
        else None
    )
    base = metrics([float(row["net_pnl_usd"]) for row in trades])
    stress = metrics([float(row["stressed_pnl_usd"]) for row in trades])
    gates = {
        "at_least_30_signals": len(trades) >= 30,
        "base_positive_expectancy": (base["expectancy_usd"] or 0) > 0,
        "base_profit_factor_gte_1_20": (base["profit_factor"] or 0) >= 1.20,
        "stress_positive_expectancy": (stress["expectancy_usd"] or 0) > 0,
        "stress_profit_factor_gte_1_05": (stress["profit_factor"] or 0) >= 1.05,
        "at_least_10_each_direction": min(direction_counts.get("bullish", 0), direction_counts.get("bearish", 0)) >= 10,
        "best_positive_session_share_lte_50pct": best_positive_share is not None and best_positive_share <= 0.50,
    }
    return {
        "schema_version": 1,
        "protocol": "MES_MBO_ABSORPTION_PREREGISTRATION_2026-08-12",
        "stage": "discovery",
        "mode": "research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "fixed_parameters": {
            "fill_threshold": FILL_THRESHOLD,
            "cancel_add_threshold": CANCEL_ADD_THRESHOLD,
            "depth_threshold": DEPTH_THRESHOLD,
            "signal_window_seconds": 5,
            "markout_seconds": 30,
            "round_trip_fees_usd": ROUND_TRIP_FEES,
            "stress_round_trip_fees_usd": STRESS_FEES,
            "stress_extra_slippage_usd": STRESS_SLIPPAGE_DOLLARS,
        },
        "quality": quality,
        "direction_counts": dict(sorted(direction_counts.items())),
        "session_pnl_usd": {key: round(value, 2) for key, value in sorted(session_pnl.items())},
        "best_positive_session_share": None if best_positive_share is None else round(best_positive_share, 6),
        "base": base,
        "stress": stress,
        "promotion_gates": {**gates, "all_pass": all(gates.values())},
        "trades": trades,
        "verdict": "eligible_for_untouched_validation" if all(gates.values()) else "retire_exact_hypothesis",
        "warnings": [
            "Discovery results cannot authorize paper, prop-firm, or live execution.",
            "Failure retires this exact conjunction; thresholds and horizon must not be retuned on these sessions.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, nargs="+", default=list(DEFAULT_INPUTS))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report(args.inputs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items() if key != "trades"}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
