#!/usr/bin/env python3
"""Intake valid frozen hypothesis specs into append-only research ledgers."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.hypothesis_ledger import (
        EXPERIMENT_FAMILY_PATH,
        HYPOTHESIS_LEDGER_PATH,
        append_hypothesis_event,
        experiment_family_size,
        latest_hypotheses,
        record_frozen_spec,
    )
    from scripts.preregistration_validator import discover_specs, validate_spec
except ImportError:
    from hypothesis_ledger import (  # type: ignore
        EXPERIMENT_FAMILY_PATH,
        HYPOTHESIS_LEDGER_PATH,
        append_hypothesis_event,
        experiment_family_size,
        latest_hypotheses,
        record_frozen_spec,
    )
    from preregistration_validator import discover_specs, validate_spec  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "data" / "weekly_candidate_intake_report.json"


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def run_intake(
    *,
    spec_paths: list[Path],
    hypothesis_path: Path = HYPOTHESIS_LEDGER_PATH,
    family_path: Path = EXPERIMENT_FAMILY_PATH,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    proposed_added = 0
    developed_added = 0
    family_added = 0
    current = latest_hypotheses(hypothesis_path)
    for spec_path in sorted(spec_paths):
        validation = validate_spec(spec_path)
        metadata = validation.get("metadata") or {}
        item = {
            "spec_path": _relative(spec_path),
            "valid": validation["valid"],
            "errors": validation["errors"],
            "action": "rejected_with_reason",
        }
        if not validation["valid"]:
            results.append(item)
            continue
        candidate_id = str(metadata["Spec ID"])
        family_id = str(metadata["Family ID"])
        origin = str(metadata["Origin"])
        spec_hash = str(metadata["Spec Hash"])
        base = {
            "id": candidate_id,
            "spec_hash": spec_hash,
            "spec_path": _relative(spec_path),
            "family_id": family_id,
            "origin": origin,
            "preregistration_schema": metadata.get("Preregistration Schema"),
            "universe_id": metadata.get("Universe ID"),
            "universe_version": metadata.get("Universe Version"),
            "universe_hash": metadata.get("Universe Hash"),
            "membership_as_of": metadata.get("Membership As Of"),
            "n_resolved": 0,
            "distinct_sessions": 0,
            "first_resolved_at": None,
            "last_evaluated_at": None,
            "dsr": None,
            "dsr_lower_bound": None,
            "pbo": None,
            "expectancy_lb": None,
        }
        existing = current.get(candidate_id)
        if existing:
            conflict = any(existing.get(field) != base.get(field) for field in ("spec_hash", "spec_path", "family_id", "origin", "universe_id", "universe_version", "universe_hash", "membership_as_of"))
            if conflict:
                item["errors"] = ["immutable_candidate_identity_conflict"]
                results.append(item)
                continue
            family = record_frozen_spec(
                candidate_id=candidate_id,
                family_id=family_id,
                spec_hash=spec_hash,
                spec_path=base["spec_path"],
                origin=origin,
                universe_id=base["universe_id"],
                universe_version=base["universe_version"],
                universe_hash=base["universe_hash"],
                membership_as_of=base["membership_as_of"],
                path=family_path,
            )
            family_added += int(family["recorded"])
            if existing.get("status") == "proposed":
                developed = append_hypothesis_event(
                    {**base, "status": "development", "verdict_reason": "frozen_spec_validated"},
                    hypothesis_path,
                    event_type="preregistration_validated",
                )
                developed_added += int(developed["recorded"])
                item["action"] = "resumed_to_development"
                current = latest_hypotheses(hypothesis_path)
            else:
                item["action"] = "already_intaked"
            results.append(item)
            continue
        proposed = append_hypothesis_event(
            {**base, "status": "proposed", "verdict_reason": "frozen_spec_pending_intake_validation"},
            hypothesis_path,
            event_type="candidate_proposed",
        )
        proposed_added += int(proposed["recorded"])
        family = record_frozen_spec(
            candidate_id=candidate_id,
            family_id=family_id,
            spec_hash=spec_hash,
            spec_path=base["spec_path"],
            origin=origin,
            universe_id=base["universe_id"],
            universe_version=base["universe_version"],
            universe_hash=base["universe_hash"],
            membership_as_of=base["membership_as_of"],
            path=family_path,
        )
        family_added += int(family["recorded"])
        developed = append_hypothesis_event(
            {**base, "status": "development", "verdict_reason": "frozen_spec_validated"},
            hypothesis_path,
            event_type="preregistration_validated",
        )
        developed_added += int(developed["recorded"])
        current = latest_hypotheses(hypothesis_path)
        item["action"] = "promoted_to_development"
        item["candidate_id"] = candidate_id
        results.append(item)
    return {
        "provider": "weekly_candidate_intake",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "read_only_research_governance",
        "specs_seen": len(spec_paths),
        "valid_specs": sum(1 for row in results if row["valid"]),
        "invalid_specs": sum(1 for row in results if not row["valid"]),
        "proposed_events_added": proposed_added,
        "development_events_added": developed_added,
        "family_specs_added": family_added,
        "experiment_wide_family_size": experiment_family_size(family_path),
        "results": results,
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", action="append", type=Path, default=[])
    parser.add_argument("--research-root", type=Path, default=ROOT / "research")
    parser.add_argument("--hypothesis-ledger", type=Path, default=HYPOTHESIS_LEDGER_PATH)
    parser.add_argument("--family-ledger", type=Path, default=EXPERIMENT_FAMILY_PATH)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    specs = args.spec or discover_specs(args.research_root)
    report = run_intake(spec_paths=specs, hypothesis_path=args.hypothesis_ledger, family_path=args.family_ledger)
    _write_json_atomic(args.report, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
