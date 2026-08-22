#!/usr/bin/env python3
"""Audit synchronized CALL/PUT evidence collection and failure reasons.

The report separates missing market setups from infrastructure failures, quote
quality rejection, capacity pressure, orphaned pairs, and unresolved outcomes.
It is observability-only and has no execution or parameter authority.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATTEMPTS_PATH = ROOT / "data" / "paired_direction_collection_log.jsonl"
DEFAULT_CANDIDATES_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "paired_direction_collection_health.json"
TARGET_RESOLVED_PAIRS = 100


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _pair_lifecycle_health(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_pair: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        pair_id = str(row.get("decision_pair_id") or "")
        if pair_id:
            by_pair[pair_id].append(row)
    dual_entry_ids = set()
    resolved_ids = set()
    orphan_ids = set()
    sealed_context_ids = set()
    sealed_policy_ids = set()
    seal_mismatch_ids = set()
    for pair_id, pair_rows in by_pair.items():
        entries = [row for row in pair_rows if row.get("event_type") == "shadow_entry"]
        entry_contracts = {str(row.get("option_symbol") or "") for row in entries}
        entry_roles = {str(row.get("decision_lattice_role") or "") for row in entries}
        if len(entry_contracts) == 2 and entry_roles == {"source_direction", "opposite_direction"}:
            dual_entry_ids.add(pair_id)
        else:
            orphan_ids.add(pair_id)
            continue
        context_hashes = {str(row.get("decision_context_sha256") or "") for row in entries}
        policy_hashes = {str(row.get("paired_direction_policy_spec_sha256") or "") for row in entries}
        if len(context_hashes) == 1 and len(next(iter(context_hashes), "")) == 64:
            sealed_context_ids.add(pair_id)
        else:
            seal_mismatch_ids.add(pair_id)
        if len(policy_hashes) == 1 and len(next(iter(policy_hashes), "")) == 64:
            sealed_policy_ids.add(pair_id)
        else:
            seal_mismatch_ids.add(pair_id)
        exits = [row for row in pair_rows if row.get("event_type") == "shadow_exit"]
        exited_contracts = {str(row.get("option_symbol") or "") for row in exits}
        if entry_contracts.issubset(exited_contracts):
            resolved_ids.add(pair_id)
    pair_dates = {
        str(row.get("date") or "")
        for pair_id, pair_rows in by_pair.items()
        if pair_id in dual_entry_ids
        for row in pair_rows[:1]
        if row.get("date")
    }
    completed_dates = {
        str(row.get("date") or "")
        for pair_id, pair_rows in by_pair.items()
        if pair_id in resolved_ids
        for row in pair_rows[:1]
        if row.get("date")
    }
    resolved_per_date = len(resolved_ids) / len(completed_dates) if completed_dates else 0.0
    remaining = max(0, TARGET_RESOLVED_PAIRS - len(resolved_ids))
    return {
        "observed_pair_ids": len(by_pair),
        "dual_entry_pairs": len(dual_entry_ids),
        "resolved_dual_pairs": len(resolved_ids),
        "active_or_unresolved_dual_pairs": len(dual_entry_ids - resolved_ids),
        "orphan_pair_count": len(orphan_ids),
        "orphan_pair_ids": sorted(orphan_ids)[:25],
        "sealed_context_pairs": len(sealed_context_ids),
        "sealed_policy_spec_pairs": len(sealed_policy_ids),
        "seal_mismatch_count": len(seal_mismatch_ids),
        "seal_mismatch_pair_ids": sorted(seal_mismatch_ids)[:25],
        "pair_entry_dates": len(pair_dates),
        "resolved_pair_dates": len(completed_dates),
        "resolved_pairs_per_observed_date": round(resolved_per_date, 3),
        "target_resolved_pairs": TARGET_RESOLVED_PAIRS,
        "remaining_pairs_to_target": remaining,
        "estimated_additional_collection_dates": (
            round(remaining / resolved_per_date, 1) if resolved_per_date > 0 else None
        ),
    }


def build_report(attempts_path: Path, candidates_path: Path) -> dict[str, Any]:
    attempts = _read_jsonl(attempts_path)
    candidates = _read_jsonl(candidates_path)
    statuses = Counter(str(row.get("status") or "unknown") for row in attempts)
    reasons = Counter(str(row.get("reason") or "unknown") for row in attempts)
    accepted = statuses.get("accepted", 0)
    actionable_attempts = accepted + statuses.get("rejected", 0)
    accepted_rate = accepted / actionable_attempts if actionable_attempts else 0.0
    lifecycle = _pair_lifecycle_health(candidates)
    accepted_ids = {
        str(row.get("decision_pair_id") or "")
        for row in attempts
        if row.get("status") == "accepted" and row.get("decision_pair_id")
    }
    entry_ids = {
        str(row.get("decision_pair_id") or "")
        for row in candidates
        if row.get("event_type") == "shadow_entry" and row.get("decision_pair_id")
    }
    accepted_without_entry = sorted(accepted_ids - entry_ids)
    blockers = []
    if not attempts:
        status = "no_attempts_recorded"
        blockers.append("paired_collection_has_not_run_with_diagnostics")
    elif actionable_attempts >= 10 and accepted_rate < 0.20:
        status = "degraded"
        blockers.append("synchronized_pair_acceptance_rate_below_20pct")
    else:
        status = "collecting"
    if lifecycle["orphan_pair_count"]:
        status = "degraded"
        blockers.append("orphan_pair_lifecycles_detected")
    if lifecycle["seal_mismatch_count"]:
        status = "degraded"
        blockers.append("paired_entry_context_or_policy_seal_mismatch")
    if accepted_without_entry:
        status = "degraded"
        blockers.append("accepted_pair_missing_atomic_dual_entry")
    return {
        "provider": "paired_direction_collection_health",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "blockers": blockers,
        "execution_enabled": False,
        "can_submit_orders": False,
        "automatic_parameter_changes": False,
        "attempts_path": str(attempts_path),
        "candidates_path": str(candidates_path),
        "attempt_summary": {
            "total_records": len(attempts),
            "actionable_attempts": actionable_attempts,
            "accepted_pairs": accepted,
            "accepted_rate": round(accepted_rate, 4),
            "status_counts": dict(statuses),
            "reason_counts": dict(reasons),
            "unique_attempt_dates": len({str(row.get("date") or "") for row in attempts if row.get("date")}),
            "unique_symbols": len({str(row.get("symbol") or "") for row in attempts if row.get("symbol")}),
        },
        "lifecycle_health": lifecycle,
        "accepted_without_entry_count": len(accepted_without_entry),
        "accepted_without_entry_ids": accepted_without_entry[:25],
        "interpretation": {
            "source_setup_unavailable": "signal coverage, not quote infrastructure failure",
            "snapshot_batch_unavailable": "broker/data transport failure",
            "quote_too_stale": "market-data freshness failure",
            "quote_timestamp_skew_exceeded": "contracts were not observed at a comparable instant",
            "symmetric_opposite_contract_unavailable": "contract geometry or chain coverage failure",
            "atomic_pair_capacity_or_strategy_slot_unavailable": "shadow scheduler capacity pressure",
        },
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=Path, default=DEFAULT_ATTEMPTS_PATH)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    args = parser.parse_args()
    report = build_report(args.attempts, args.candidates)
    write_report(report, args.out)
    print(json.dumps({
        "status": report["status"],
        "blockers": report["blockers"],
        "attempt_summary": report["attempt_summary"],
        "lifecycle_health": report["lifecycle_health"],
        "report": str(args.out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
