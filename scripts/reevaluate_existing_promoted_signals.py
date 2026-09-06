"""One-shot advisory re-evaluation; never mutates promotion status."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.governance.statistical_gate import (GATE_HISTORY, PROMOTED_STATUSES,
                                                REGISTRY_PATH, StatisticalGate,
                                                append_gate_history)
from agent.governance.trial_ledger import DEFAULT_LEDGER, hypothesis_hash, record_trial

REPORT_DIR = ROOT / "data" / "governance"


def build(*, dry_run: bool, registry_path: Path = REGISTRY_PATH,
          ledger_path: Path = DEFAULT_LEDGER, history_dir: Path = GATE_HISTORY,
          report_dir: Path = REPORT_DIR) -> tuple[dict, Path]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    promoted = [row for row in registry.get("signals") or [] if row.get("status") in PROMOTED_STATUSES]
    if not dry_run:
        for signal in registry.get("signals") or []:
            record_trial(str(signal.get("id") or ""), hypothesis_hash(signal),
                         family_key=str(signal.get("family_key") or "unassigned"),
                         legacy_backfill=True, path=ledger_path)
    gate = StatisticalGate(registry_path=registry_path, ledger_path=ledger_path)
    decisions = [gate.evaluate(str(signal["id"])) for signal in promoted]
    if not dry_run:
        for decision in decisions:
            append_gate_history(decision, directory=history_dir)
    day = datetime.now(timezone.utc).date().isoformat()
    target = report_dir / f"reevaluation_report_{day}.md"
    lines = ["# Existing promoted signal statistical re-evaluation", "",
             f"Generated: {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}", "",
             "Advisory only. No registry promotion flag or execution setting was changed.", "",
             "| Signal | Family | n | trials | Sharpe | DSR | PSR | PBO | Status | Reason |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for row in decisions:
        value = row.to_dict()
        lines.append("| {signal_id} | {family_key} | {n_outcomes} | {n_trials} | {sharpe} | {deflated_sharpe} | {psr} | {pbo} | {status} | {reason} |".format(**value))
    lines += ["", "## Required human review", "",
              "- Confirm every family assignment in `config/signal_families.json` and `research/signal_registry.json`.",
              "- Legacy trial counts are lower bounds because unrecorded historical experiments cannot be reconstructed.",
              "- Do not demote or promote from this report automatically."]
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"dry_run": dry_run, "promoted_signals": len(promoted),
            "needs_review": sum(row.status == "needs_review" for row in decisions),
            "registry_mutations": 0, "execution_enabled": False,
            "can_submit_orders": False}, target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    summary, target = build(dry_run=args.dry_run)
    print(json.dumps({**summary, "report": None if args.dry_run else str(target)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
