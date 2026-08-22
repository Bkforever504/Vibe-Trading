#!/usr/bin/env python3
"""Strict point-in-time event-surprise edge evaluator for MES."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "point_in_time_event_surprises.csv"
OUTPUT = ROOT / "data" / "event_surprise_edge_results.json"
REQUIRED_COLUMNS = {
    "event_id", "event_name", "released_at_utc", "consensus", "consensus_asof_utc",
    "actual_first_release", "actual_vintage", "entry_at_utc", "entry_bid", "entry_ask",
    "exit_at_utc", "exit_bid", "exit_ask", "source",
}
RELATION = {
    "cpi_yoy": -1,
    "core_cpi_mom": -1,
    "core_pce_mom": -1,
    "fed_funds_upper": -1,
}
MES_POINT_VALUE = 5.0
BASE_COMMISSION = 2.48
MIN_HISTORY_PER_EVENT = 12
MIN_RESOLVED = 60


def _parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp_missing_timezone")
    return parsed.astimezone(timezone.utc)


def validate_rows(rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not rows:
        return ["no_rows"]
    missing = REQUIRED_COLUMNS - set(rows[0])
    if missing:
        return [f"missing_columns:{','.join(sorted(missing))}"]
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        event_id = row.get("event_id", "")
        if not event_id or event_id in seen:
            errors.append(f"row_{index}:invalid_or_duplicate_event_id")
        seen.add(event_id)
        try:
            released = _parse_ts(row["released_at_utc"])
            consensus_asof = _parse_ts(row["consensus_asof_utc"])
            entry = _parse_ts(row["entry_at_utc"])
            exit_at = _parse_ts(row["exit_at_utc"])
            if consensus_asof > released:
                errors.append(f"row_{index}:consensus_not_point_in_time")
            if entry < released:
                errors.append(f"row_{index}:entry_before_release")
            if exit_at <= entry:
                errors.append(f"row_{index}:exit_not_after_entry")
            if (exit_at - entry).total_seconds() > 20 * 60:
                errors.append(f"row_{index}:exit_horizon_over_20_minutes")
        except (KeyError, ValueError):
            errors.append(f"row_{index}:invalid_timestamp")
        if row.get("actual_vintage") != "first_release":
            errors.append(f"row_{index}:actual_not_first_release")
        if row.get("event_name") not in RELATION:
            errors.append(f"row_{index}:unsupported_event")
        for field in ("consensus", "actual_first_release", "entry_bid", "entry_ask", "exit_bid", "exit_ask"):
            try:
                value = float(row[field])
                if not math.isfinite(value):
                    raise ValueError
            except (KeyError, ValueError):
                errors.append(f"row_{index}:invalid_{field}")
    return errors


def _metrics(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"trades": 0, "expectancy_dollars": None, "profit_factor": None, "one_sided_p": None}
    mean = sum(values) / len(values)
    gross_win = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    profit_factor = math.inf if gross_loss == 0 and gross_win > 0 else (gross_win / gross_loss if gross_loss else 0.0)
    p_value = None
    if len(values) >= 2:
        variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
        if variance > 0:
            p_value = 1 - NormalDist().cdf(mean / math.sqrt(variance / len(values)))
    return {
        "trades": len(values), "expectancy_dollars": round(mean, 6),
        "profit_factor": round(profit_factor, 6) if math.isfinite(profit_factor) else math.inf,
        "one_sided_p": round(p_value, 10) if p_value is not None else None,
    }


def evaluate(rows: list[dict[str, str]]) -> dict[str, Any]:
    errors = validate_rows(rows)
    if errors:
        return {
            "status": "data_integrity_failed", "errors": errors[:100], "resolved_count": 0,
            "execution_enabled": False, "can_submit_orders": False,
        }
    history: dict[str, list[float]] = defaultdict(list)
    pnls: list[float] = []
    for row in sorted(rows, key=lambda value: _parse_ts(value["released_at_utc"])):
        name = row["event_name"]
        surprise = float(row["actual_first_release"]) - float(row["consensus"])
        prior = history[name]
        if len(prior) >= MIN_HISTORY_PER_EVENT:
            mean = sum(prior) / len(prior)
            variance = sum((value - mean) ** 2 for value in prior) / (len(prior) - 1)
            stddev = math.sqrt(variance)
            if stddev > 0 and abs((surprise - mean) / stddev) >= 1.0:
                direction = RELATION[name] * (1 if surprise > mean else -1)
                if direction > 0:
                    gross = (float(row["exit_bid"]) - float(row["entry_ask"])) * MES_POINT_VALUE
                else:
                    gross = (float(row["entry_bid"]) - float(row["exit_ask"])) * MES_POINT_VALUE
                pnls.append(gross - BASE_COMMISSION)
        prior.append(surprise)
    metrics = _metrics(pnls)
    return {
        "status": "eligible_for_review" if metrics["trades"] >= MIN_RESOLVED else "insufficient_resolved_events",
        "resolved_count": metrics["trades"], "metrics": metrics,
        "execution_enabled": False, "can_submit_orders": False,
    }


def run(input_path: Path = INPUT, output_path: Path = OUTPUT) -> dict[str, Any]:
    if not input_path.exists():
        report = {
            "provider": "event_surprise_edge_lab", "status": "missing_point_in_time_consensus_data",
            "required_columns": sorted(REQUIRED_COLUMNS), "resolved_count": 0,
            "execution_enabled": False, "can_submit_orders": False,
            "source_audit": {
                "official_actuals_and_revisions": "available_from_BLS_FRED_ALFRED",
                "historical_consensus_as_known": "not_available_in_free_official_sources",
                "licensed_candidate": "Trading_Economics_point_in_time_calendar",
                "unversioned_public_calendar": "rejected_for_promotion_evidence",
            },
        }
    else:
        with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        report = {"provider": "event_surprise_edge_lab", **evaluate(rows)}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_suffix(output_path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, output_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = run(args.input, args.output)
    print(json.dumps(report, indent=2, sort_keys=True) if args.print_report else report["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

