#!/usr/bin/env python3
"""Explain why causal ground-truth movers were absent from radar coverage."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VIBE_HOME = Path.home() / ".vibe-trading"


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _root_cause(move: dict[str, Any], discovered: set[str]) -> str:
    symbol = str(move.get("symbol") or "").upper()
    if symbol in discovered:
        return "covered"
    reasons = set(str(value) for value in move.get("exclusion_reasons") or [])
    if any("liquidity" in value for value in reasons):
        return "liquidity_filter"
    if any("price" in value for value in reasons):
        return "price_filter"
    if move.get("data_gap"):
        return "data_gap"
    return "discovery_source_gap"


def build_coverage_delta(ground_truth: dict[str, Any], radar: dict[str, Any]) -> dict[str, Any]:
    discovered = {str(value).upper() for value in radar.get("all_discovered_symbols") or []}
    rows = []
    for move in ground_truth.get("moves") or []:
        if not isinstance(move, dict):
            continue
        cause = _root_cause(move, discovered)
        rows.append({
            "move_id": move.get("move_id"),
            "symbol": move.get("symbol"),
            "move_pct": move.get("move_pct"),
            "in_discovery_universe": cause == "covered",
            "root_cause": cause,
            "execution_enabled": False,
            "can_submit_orders": False,
        })
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["root_cause"]] = counts.get(row["root_cause"], 0) + 1
    return {
        "schema_version": 1,
        "provider": "universe_coverage_delta",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": ground_truth.get("date"),
        "summary": {"ground_truth_count": len(rows), "covered": counts.get("covered", 0), "root_cause_counts": counts},
        "rows": rows,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--radar-report", type=Path, default=VIBE_HOME / "reports" / "intraday-opportunity-radar.json")
    args = parser.parse_args()
    compact = args.date.replace("-", "")
    report = build_coverage_delta(_read(args.data_dir / f"move_ground_truth_{compact}.json"), _read(args.radar_report))
    output = args.data_dir / f"universe_coverage_delta_{compact}.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(f"coverage_delta date={args.date} covered={report['summary']['covered']} truth={report['summary']['ground_truth_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
