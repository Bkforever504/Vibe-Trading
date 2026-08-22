#!/usr/bin/env python3
"""Measure calendar-dependent options execution quality from shadow outcomes."""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TWIN_PATH = ROOT / "data" / "options_shadow_twin_log.jsonl"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "execution_seasonality_report.json"
ET = ZoneInfo("America/New_York")
MIN_BUCKET = 10


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed


def _midpoint_close_debit(legs: Any) -> float | None:
    if not isinstance(legs, list) or not legs:
        return None
    total = 0.0
    for leg in legs:
        if not isinstance(leg, dict):
            return None
        bid = _number(leg.get("bid"))
        ask = _number(leg.get("ask"))
        quantity = int(_number(leg.get("ratio_qty")) or 1)
        if bid is None or ask is None or bid < 0 or ask < bid:
            return None
        midpoint = (bid + ask) / 2.0
        side = str(leg.get("side") or "").lower()
        if side == "sell":
            total += midpoint * quantity
        elif side == "buy":
            total -= midpoint * quantity
        else:
            return None
    return max(0.0, total)


def _dte_bucket(dte: int) -> str:
    if dte <= 0:
        return "0"
    if dte <= 7:
        return "1-7"
    if dte <= 21:
        return "8-21"
    if dte <= 45:
        return "22-45"
    return "46+"


def _entry_window(value: datetime) -> str:
    minutes = value.hour * 60 + value.minute
    if 570 <= minutes < 630:
        return "open_0930_1030"
    if 630 <= minutes < 870:
        return "midday_1030_1430"
    if 870 <= minutes <= 960:
        return "close_1430_1600"
    return "outside_rth"


def _bucket_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    executable = [float(row["executable_pnl"]) for row in rows]
    midpoint = [float(row["midpoint_pnl"]) for row in rows if row.get("midpoint_pnl") is not None]
    friction = [float(row["round_trip_friction"]) for row in rows if row.get("round_trip_friction") is not None]
    mae = [float(row["mae"]) for row in rows if row.get("mae") is not None]
    mfe = [float(row["mfe"]) for row in rows if row.get("mfe") is not None]
    durations = [float(row["duration_hours"]) for row in rows if row.get("duration_hours") is not None]
    return {
        "count": len(rows),
        "status": "rankable" if len(rows) >= MIN_BUCKET else "insufficient_n",
        "win_rate": round(sum(value > 0 for value in executable) / len(executable), 4) if executable else None,
        "aggregate_executable_pnl_before_fees": round(sum(executable), 2),
        "average_executable_pnl_before_fees": round(mean(executable), 2) if executable else None,
        "median_executable_pnl_before_fees": round(median(executable), 2) if executable else None,
        "average_midpoint_benchmark_pnl": round(mean(midpoint), 2) if midpoint else None,
        "average_round_trip_friction_dollars": round(mean(friction), 2) if friction else None,
        "friction_measured_count": len(friction),
        "average_mae_dollars": round(mean(mae), 2) if mae else None,
        "average_mfe_dollars": round(mean(mfe), 2) if mfe else None,
        "average_duration_hours": round(mean(durations), 2) if durations else None,
        "complete_entry_quote_rate": round(sum(bool(row["quote_complete"]) for row in rows) / len(rows), 4)
        if rows else None,
    }


def build_report(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    candidates: dict[str, dict[str, Any]] = {}
    marks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    outcomes: dict[str, dict[str, Any]] = {}
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id:
            continue
        if row.get("type") == "candidate":
            candidates[candidate_id] = row
        elif row.get("type") == "mark":
            marks[candidate_id].append(row)
        elif row.get("type") == "outcome":
            outcomes[candidate_id] = row

    resolved: list[dict[str, Any]] = []
    for candidate_id, outcome in outcomes.items():
        candidate = candidates.get(candidate_id)
        executable_pnl = _number(outcome.get("pnl_before_fees"))
        created = _timestamp((candidate or {}).get("created_at"))
        resolved_at = _timestamp(outcome.get("resolved_at"))
        if candidate is None or executable_pnl is None or created is None:
            continue
        created_et = created.astimezone(ET)
        expiry = _timestamp(f"{candidate.get('expiry')}T16:00:00-04:00") if candidate.get("expiry") else None
        dte = max(0, (expiry.date() - created_et.date()).days) if expiry else int(_number(candidate.get("dte")) or 0)
        quantity = int(_number(outcome.get("quantity")) or _number(candidate.get("effective_qty")) or 1)
        entry_mid = _number(candidate.get("quoted_mid_credit"))
        entry_executable = _number(candidate.get("executable_entry_credit"))
        entry_friction = (
            max(0.0, entry_mid - entry_executable) * 100.0 * quantity
            if entry_mid is not None and entry_executable is not None else None
        )
        ordered_marks = sorted(
            marks.get(candidate_id, []),
            key=lambda value: _timestamp(value.get("marked_at")) or created,
        )
        last_mark = ordered_marks[-1] if ordered_marks else None
        exit_executable = _number((last_mark or {}).get("executable_close_debit"))
        exit_mid = _midpoint_close_debit((last_mark or {}).get("legs"))
        exit_friction = (
            max(0.0, exit_executable - exit_mid) * 100.0 * quantity
            if exit_executable is not None and exit_mid is not None else None
        )
        round_trip_friction = (
            entry_friction + exit_friction
            if entry_friction is not None and exit_friction is not None else None
        )
        path_pnls = []
        if entry_executable is not None:
            for mark in ordered_marks:
                debit = _number(mark.get("executable_close_debit"))
                if debit is not None:
                    path_pnls.append((entry_executable - debit) * 100.0 * quantity)
        midpoint_pnl = executable_pnl + round_trip_friction if round_trip_friction is not None else None
        same_expiry_week = (
            created_et.isocalendar()[:2] == expiry.astimezone(ET).isocalendar()[:2]
            if expiry else False
        )
        resolved.append({
            "candidate_id": candidate_id,
            "strategy": str(candidate.get("strategy") or "unknown"),
            "entry_et": created_et,
            "dte_bucket": _dte_bucket(dte),
            "expiry_week": "same_week" if same_expiry_week else "later_week",
            "entry_window": _entry_window(created_et),
            "executable_pnl": executable_pnl,
            "midpoint_pnl": midpoint_pnl,
            "round_trip_friction": round_trip_friction,
            "mae": min(path_pnls) if path_pnls else None,
            "mfe": max(path_pnls) if path_pnls else None,
            "duration_hours": (resolved_at - created).total_seconds() / 3600.0 if resolved_at else None,
            "quote_complete": bool(candidate.get("entry_quote_complete")),
        })

    dimensions: dict[str, Callable[[dict[str, Any]], str]] = {
        "strategy": lambda row: row["strategy"],
        "month": lambda row: row["entry_et"].strftime("%Y-%m"),
        "weekday": lambda row: row["entry_et"].strftime("%A"),
        "entry_hour_et": lambda row: row["entry_et"].strftime("%H"),
        "entry_window_et": lambda row: row["entry_window"],
        "dte_bucket": lambda row: row["dte_bucket"],
        "expiry_week": lambda row: row["expiry_week"],
    }
    buckets: dict[str, dict[str, Any]] = {}
    for dimension, key_function in dimensions.items():
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in resolved:
            grouped[key_function(row)].append(row)
        buckets[dimension] = {
            key: _bucket_metrics(group) for key, group in sorted(grouped.items())
        }
    return {
        "schema_version": 1,
        "provider": "execution_seasonality_report",
        "mode": "read_only_execution_context",
        "resolved_candidate_count": len(resolved),
        "minimum_rankable_bucket": MIN_BUCKET,
        "overall": _bucket_metrics(resolved),
        "buckets": buckets,
        "methodology": {
            "midpoint_benchmark": "executable_pnl_plus_measured_entry_and_exit_spread_friction",
            "entry_friction": "quoted_mid_credit_minus_executable_entry_credit",
            "exit_friction": "executable_close_debit_minus_leg_midpoint_close_debit",
            "fees": "not_subtracted_unless_already_present_in_source_outcome",
        },
        "limitations": [
            "Buckets are diagnostic and must not become gates without preregistered out-of-sample validation.",
            "The final available mark proxies exit friction; exact trigger-time quotes may be unavailable.",
            "Fill and rejection rates require broker order events and are not inferred from shadow candidates.",
        ],
        "promotion_authority": "blocked",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--twin", type=Path, default=DEFAULT_TWIN_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(read_jsonl(args.twin))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
