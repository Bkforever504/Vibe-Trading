#!/usr/bin/env python3
"""Promote a pattern taxonomy label only after every frozen statistical gate passes."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = Path.home() / ".vibe-trading" / "reports" / "cisd-promotion-status.json"
TAXONOMY_PATH = ROOT / "research" / "pattern_taxonomy.json"
LEDGER_PATH = ROOT / "data" / "pattern_promotion_ledger.jsonl"


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def promote(
    *, status_path: Path = STATUS_PATH, taxonomy_path: Path = TAXONOMY_PATH,
    ledger_path: Path = LEDGER_PATH, now_utc: str | None = None,
) -> dict[str, Any]:
    status = _read(status_path)
    if status.get("eligible_for_validated_promotion") is not True:
        return {"status": "gate_not_eligible", "changed": False, "execution_enabled": False, "can_submit_orders": False}
    pattern_id = str(status.get("pattern_id") or "")
    taxonomy = _read(taxonomy_path)
    patterns = taxonomy.get("patterns") if isinstance(taxonomy.get("patterns"), list) else []
    pattern = next((row for row in patterns if isinstance(row, dict) and str(row.get("id")) == pattern_id), None)
    if pattern is None:
        return {"status": "pattern_not_found", "changed": False, "execution_enabled": False, "can_submit_orders": False}
    prior = str(pattern.get("governance_status") or "unvalidated_pattern_hypothesis")
    if prior == "validated_pattern":
        return {"status": "already_validated", "changed": False, "execution_enabled": False, "can_submit_orders": False}
    required = (
        int(status.get("n_outcomes") or 0) >= 100,
        int(status.get("n_unique_dates") or 0) >= 30,
        float(status.get("wilson_lower_bound_95") or 0) >= 0.55,
        float(status.get("brier_skill") or 0) > 0,
    )
    if not all(required):
        return {"status": "gate_snapshot_inconsistent", "changed": False, "execution_enabled": False, "can_submit_orders": False}
    pattern["governance_status"] = "validated_pattern"
    _atomic(taxonomy_path, taxonomy)
    stamp = now_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    audit = {
        "schema_version": 1,
        "ts": stamp,
        "pattern_id": pattern_id,
        "prior_status": prior,
        "new_status": "validated_pattern",
        "gate_snapshot": {
            key: status.get(key)
            for key in ("n_outcomes", "n_unique_dates", "win_rate_raw", "wilson_lower_bound_95", "brier_score", "brier_baseline", "brier_skill")
        },
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(audit, separators=(",", ":"), sort_keys=True) + "\n")
    return {"status": "promoted", "changed": True, "pattern_id": pattern_id, "execution_enabled": False, "can_submit_orders": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", type=Path, default=STATUS_PATH)
    parser.add_argument("--taxonomy", type=Path, default=TAXONOMY_PATH)
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    args = parser.parse_args()
    print(json.dumps(promote(status_path=args.status, taxonomy_path=args.taxonomy, ledger_path=args.ledger), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
