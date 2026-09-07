#!/usr/bin/env python3
"""Run the common-fabric BLSH bake-off from a supplied OHLCV JSON file."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from agent.src.research.blsh_bakeoff import append_prediction_ledger, build_bakeoff

DEFAULT_REPORT = Path.home() / ".vibe-trading" / "reports" / "blsh-bakeoff-shadow.json"
DEFAULT_LEDGER = ROOT / "data" / "blsh_predictions.parquet"

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True); parser.add_argument("--report", type=Path, default=DEFAULT_REPORT); parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8")); rows = payload.get("bars", payload) if isinstance(payload, dict) else payload
        report = build_bakeoff(rows); import pandas as pd
        ledger_rows = pd.DataFrame(report.pop("predictions")); report["ledger_rows_added"] = append_prediction_ledger(ledger_rows, args.ledger)
    except Exception as exc:
        report = {"schema_version": 1, "status": "unavailable", "reason": type(exc).__name__, "execution_enabled": False, "can_submit_orders": False, "promotion_authority": "human_review_only"}
    args.report.parent.mkdir(parents=True, exist_ok=True); args.report.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return 0
if __name__ == "__main__": raise SystemExit(main())
