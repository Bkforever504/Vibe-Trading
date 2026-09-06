#!/usr/bin/env python3
"""Build the read-only statistical-gate and paired-latency dashboard artifact."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.analytics.paired_bootstrap import paired_diff_ci

GATE_HISTORY = ROOT / "data" / "governance" / "gate_history"
LATENCY_PAIRS = ROOT / "data" / "latency_pairs.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "statistical-governance.json"


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    values: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            values.append(row)
    return values


def latency_proof(path: Path = LATENCY_PAIRS) -> dict[str, Any]:
    rows = _rows(path)
    valid = [row for row in rows if isinstance(row.get("baseline_latency_ms"), (int, float))
             and isinstance(row.get("new_latency_ms"), (int, float))]
    base = {"records": len(rows), "paired_samples": len(valid), "minimum_paired_samples": 30,
            "claim_rule": "95pct_ci_excludes_zero_and_mean_new_minus_baseline_is_negative",
            "execution_enabled": False, "can_submit_orders": False}
    if not any(isinstance(row.get("baseline_latency_ms"), (int, float)) for row in rows):
        return {**base, "status": "no_baseline", "result": None,
                "reason": "no_defensible_parallel_baseline_recorded"}
    if len(valid) < 30:
        return {**base, "status": "insufficient_data", "result": None,
                "reason": f"paired_samples:{len(valid)}/30"}
    result = paired_diff_ci([row["baseline_latency_ms"] for row in valid],
                            [row["new_latency_ms"] for row in valid])
    supported = result.get("excludes_zero") and (result.get("point") or 0) < 0
    return {**base, "status": "improvement_supported" if supported else "cannot_claim_improvement",
            "result": result, "reason": None}


def build_report(history_dir: Path = GATE_HISTORY, latency_path: Path = LATENCY_PAIRS) -> dict[str, Any]:
    gates = []
    if history_dir.exists():
        for path in sorted(history_dir.glob("*.jsonl")):
            rows = _rows(path)
            if rows:
                gates.append(rows[-1])
    return {
        "provider": "statistical_governance_report",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "needs_human_review" if any(row.get("status") == "needs_review" for row in gates) else "ok",
        "signals": gates,
        "latency_proof": latency_proof(latency_path),
        "family_assignment_review_required": True,
        "automatic_promotion_or_demotion": False,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_report()
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.print_output:
        print(json.dumps(report, indent=2))
    else:
        print(json.dumps({"status": report["status"], "signals": len(report["signals"]),
                          "latency": report["latency_proof"]["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
