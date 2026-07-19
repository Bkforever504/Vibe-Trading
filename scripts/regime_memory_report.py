#!/usr/bin/env python3
"""Read-only memory of bot outcomes by market regime.

This answers the useful question: "Where do the bots actually perform well?"
It aggregates daily outcome reviews by regime labels without changing any bot
settings or execution gates.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
LOG_PATH = ROOT / "data" / "regime_memory_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "regime-memory.json"

SOURCE_PATHS = {
    "outcome": ROOT / "data" / "daily_outcome_review_log.jsonl",
    "market_force": ROOT / "data" / "market_force_score_log.jsonl",
    "breadth": ROOT / "data" / "market_breadth_uptrend_log.jsonl",
    "distribution": ROOT / "data" / "distribution_day_log.jsonl",
    "sector_rotation": ROOT / "data" / "sector_rotation_rank_log.jsonl",
    "exposure": ROOT / "data" / "exposure_coach_log.jsonl",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _row_date(row: dict[str, Any]) -> str:
    for key in ("date", "timestamp", "created_at", "ts"):
        value = row.get(key)
        if value:
            return str(value)[:10]
    return ""


def _latest_by_day(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        day = _row_date(row)
        if day:
            out[day] = row
    return out


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _bucket_pnl(value: float) -> str:
    if value >= 250:
        return "strong_green"
    if value > 0:
        return "green"
    if value <= -250:
        return "strong_red"
    if value < 0:
        return "red"
    return "flat"


def _day_context(day: str, rows: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    outcome = rows["outcome"].get(day, {})
    market_force = rows["market_force"].get(day, {})
    breadth = rows["breadth"].get(day, {})
    distribution = rows["distribution"].get(day, {})
    sector_rotation = rows["sector_rotation"].get(day, {})
    exposure = rows["exposure"].get(day, {})
    event_summary = outcome.get("event_summary") if isinstance(outcome.get("event_summary"), dict) else {}
    breadth_row = breadth.get("breadth") if isinstance(breadth.get("breadth"), dict) else {}
    distribution_row = distribution.get("aggregate") if isinstance(distribution.get("aggregate"), dict) else {}
    rotation = sector_rotation.get("rotation") if isinstance(sector_rotation.get("rotation"), dict) else {}
    pnl = _safe_float(event_summary.get("realized_pnl"))
    return {
        "date": day,
        "pnl": pnl,
        "pnl_bucket": _bucket_pnl(pnl),
        "trade_count": int(event_summary.get("trade_count") or 0),
        "guard_block_count": int(event_summary.get("guard_block_count") or 0),
        "market_force": str(market_force.get("classification") or outcome.get("market_force_classification") or "missing"),
        "market_force_score": _safe_float(market_force.get("total_score") or outcome.get("market_force_score")),
        "breadth": str(breadth_row.get("uptrend_status") or outcome.get("breadth_status") or "missing"),
        "distribution": str(distribution_row.get("regime") or outcome.get("distribution_regime") or "missing"),
        "sector_rotation": str(rotation.get("leadership") or "missing"),
        "exposure_posture": str(exposure.get("posture") or outcome.get("posture") or "missing"),
        "outcome_verdict": str(outcome.get("verdict") or "missing"),
    }


def _group_stats(days: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in days:
        grouped[str(row.get(key) or "missing")].append(row)
    out = []
    for label, rows in grouped.items():
        pnls = [float(row.get("pnl") or 0.0) for row in rows]
        green = sum(1 for pnl in pnls if pnl > 0)
        trade_days = sum(1 for row in rows if int(row.get("trade_count") or 0) > 0)
        out.append({
            "dimension": key,
            "label": label,
            "day_count": len(rows),
            "trade_day_count": trade_days,
            "total_pnl": round(sum(pnls), 2),
            "avg_pnl": round(sum(pnls) / len(pnls), 2) if rows else 0.0,
            "green_day_rate": round(green / len(rows), 4) if rows else 0.0,
            "avg_guard_blocks": round(sum(int(row.get("guard_block_count") or 0) for row in rows) / len(rows), 2) if rows else 0.0,
            "sample_dates": [row["date"] for row in rows[-5:]],
        })
    return sorted(out, key=lambda item: (item["day_count"], item["total_pnl"]), reverse=True)


def build_report(paths: dict[str, Path] | None = None, min_days: int = 3) -> dict[str, Any]:
    paths = paths or SOURCE_PATHS
    rows = {name: _latest_by_day(path) for name, path in paths.items()}
    days = sorted(set().union(*(set(value.keys()) for value in rows.values())))
    day_rows = [_day_context(day, rows) for day in days]
    dimensions = ["market_force", "breadth", "distribution", "sector_rotation", "exposure_posture", "outcome_verdict", "pnl_bucket"]
    regime_groups = {dimension: _group_stats(day_rows, dimension) for dimension in dimensions}
    enough_data = len(day_rows) >= min_days
    warnings = ["Read-only regime memory. No execution settings are changed."]
    if not enough_data:
        warnings.append(f"LOG BUILDING: only {len(day_rows)} days available; wait for {min_days}+ days before using conclusions.")
    return {
        "date": date.today().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "regime_memory_report",
        "mode": "read_only",
        "execution_enabled": False,
        "day_count": len(day_rows),
        "enough_data": enough_data,
        "days": day_rows[-60:],
        "regime_groups": regime_groups,
        "warnings": warnings,
    }


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), default=str) + "\n")


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    print("\nRegime Memory | read-only")
    print("=" * 72)
    print(f"days={report['day_count']} enough_data={report['enough_data']}")
    for dimension in ("market_force", "breadth", "distribution", "exposure_posture"):
        top = report["regime_groups"].get(dimension, [])[:3]
        print(f"\n{dimension}:")
        for row in top:
            print(
                f"  {row['label']:<24} days={row['day_count']:<3} "
                f"pnl={row['total_pnl']:<9} avg={row['avg_pnl']:<8} green={row['green_day_rate']}"
            )
    for warning in report["warnings"]:
        print(f"- {warning}")
    print(f"JSON: {REPORT_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-days", type=int, default=3)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_report(min_days=args.min_days)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Regime memory logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
