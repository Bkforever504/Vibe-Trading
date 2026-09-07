#!/usr/bin/env python3
"""Join BLSH predictions to future bars and evaluate the human-review stat gate."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from agent.src.research.blsh_bakeoff import join_forward_returns, statistical_promotion_gate

DEFAULT_LEDGER = ROOT / "data" / "blsh_predictions.parquet"
DEFAULT_OUTCOMES = ROOT / "data" / "blsh_outcomes.parquet"
DEFAULT_REPORT = Path.home() / ".vibe-trading" / "reports" / "blsh-bakeoff-stat-gate.json"

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--bars", type=Path, required=True); parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER); parser.add_argument("--outcomes", type=Path, default=DEFAULT_OUTCOMES); parser.add_argument("--report", type=Path, default=DEFAULT_REPORT); args = parser.parse_args()
    try:
        raw = json.loads(args.bars.read_text(encoding="utf-8")); bars = raw.get("bars", raw) if isinstance(raw, dict) else raw
        predictions = pd.read_parquet(args.ledger); outcomes = join_forward_returns(predictions, pd.DataFrame(bars))
        args.outcomes.parent.mkdir(parents=True, exist_ok=True); temporary = args.outcomes.with_suffix(args.outcomes.suffix + ".tmp"); outcomes.to_parquet(temporary, index=False); temporary.replace(args.outcomes)
        scored = outcomes.dropna(subset=["forward_return_5"]).copy(); sign = scored["side"].map({"LONG": 1.0, "SHORT": -1.0, "ABSTAIN": 0.0}).fillna(0); scored["excess_return"] = sign * scored["forward_return_5"]
        report = {"schema_version": 1, "status": "outcomes_joined", "rows": len(outcomes), "resolved_5d": len(scored), "statistical_gate": statistical_promotion_gate(scored), "execution_enabled": False, "can_submit_orders": False}
    except Exception as exc:
        report = {"schema_version": 1, "status": "unavailable", "reason": type(exc).__name__, "execution_enabled": False, "can_submit_orders": False}
    args.report.parent.mkdir(parents=True, exist_ok=True); args.report.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"); return 0
if __name__ == "__main__": raise SystemExit(main())
