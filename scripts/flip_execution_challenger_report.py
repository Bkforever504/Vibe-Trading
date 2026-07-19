#!/usr/bin/env python3
"""Read-only report for contract selection and passive-limit opportunities."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
DEFAULT_OUTPUT = Path.home() / ".vibe-trading" / "reports" / "flip-execution-challengers.json"
DEFAULT_LOG = ROOT / "data" / "flip_execution_challenger_report_log.jsonl"


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("action") == "exit_shadow":
            rows.append(row)
    return rows


def build_report(path: Path = DEFAULT_INPUT) -> dict:
    rows = _read_rows(path)
    buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "observations": 0,
        "delta_observations": 0,
        "passive_mid_eligible": 0,
        "passive_mid_fill_opportunities": 0,
        "passive_plus_tick_eligible": 0,
        "passive_plus_tick_fill_opportunities": 0,
        "marketable_limit_ask_coverage": 0,
        "executable_returns": [],
    })
    lifecycle_count = 0
    for row in rows:
        challengers = row.get("contract_selection_challengers") or []
        if challengers:
            lifecycle_count += 1
        for challenger in challengers:
            if not isinstance(challenger, dict):
                continue
            variant = str(challenger.get("variant") or "unknown")
            bucket = buckets[variant]
            bucket["observations"] += 1
            if _number(challenger.get("selection_delta")) is not None:
                bucket["delta_observations"] += 1
            if _number(challenger.get("passive_limit_mid")) is not None:
                bucket["passive_mid_eligible"] += 1
                bucket["passive_mid_fill_opportunities"] += int(bool(challenger.get("passive_mid_fill_observed")))
            if _number(challenger.get("passive_limit_mid_plus_tick")) is not None:
                bucket["passive_plus_tick_eligible"] += 1
                bucket["passive_plus_tick_fill_opportunities"] += int(bool(challenger.get("passive_plus_tick_fill_observed")))
            if _number(challenger.get("marketable_limit_ask")) is not None:
                bucket["marketable_limit_ask_coverage"] += 1
            executable_return = _number(challenger.get("executable_return_pct"))
            if executable_return is not None:
                bucket["executable_returns"].append(executable_return)

    summaries = []
    for variant, bucket in sorted(buckets.items()):
        returns = bucket.pop("executable_returns")
        mid_eligible = int(bucket["passive_mid_eligible"])
        plus_eligible = int(bucket["passive_plus_tick_eligible"])
        summaries.append({
            "variant": variant,
            **bucket,
            "passive_mid_fill_opportunity_rate": round(bucket["passive_mid_fill_opportunities"] / mid_eligible, 4) if mid_eligible else None,
            "passive_plus_tick_fill_opportunity_rate": round(bucket["passive_plus_tick_fill_opportunities"] / plus_eligible, 4) if plus_eligible else None,
            "avg_executable_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
        })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(path),
        "read_only": True,
        "can_submit_orders": False,
        "completed_lifecycles_with_challengers": lifecycle_count,
        "variants": summaries,
        "promotion_ready": False,
        "warnings": [
            "A future observed ask at or below a proposed limit is a conservative fill opportunity, not proof of queue-position fill.",
            "Alpaca indicative modified quotes are not licensed OPRA NBBO evidence.",
            "No execution policy changes automatically from this report.",
        ],
    }


def _write(path: Path, value: dict, *, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, sort_keys=True)
    if append:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    else:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(args.input)
    _write(args.output, report)
    _write(args.log, report, append=True)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
