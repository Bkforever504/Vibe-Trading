#!/usr/bin/env python3
"""Build fail-closed dashboard evidence status for the MNQ SMT family."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DEFAULT_OUTPUT = Path.home() / ".vibe-trading" / "reports" / "mnq-smt-evidence-status.json"
CANDIDATES = ("mnq-smt-cisd-fvg-v1", "mnq-pdl-rejection-v1", "mnq-smt-only-v1", "mnq-cisd-only-v1")
REGIMES = ("trend", "chop", "high_vol", "low_vol")
APPROVAL_SHA256 = "ab852a4220196bdc42cc7c512349f90581318a22646b973309600201fcd8661a"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    result = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def build_status(rows: Iterable[Mapping[str, Any]], *, capability: Mapping[str, Any] | None = None,
                 approval_present: bool, now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    latest: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        plan_id = str(row.get("plan_id") or "")
        if plan_id and str(row.get("candidate_id") or row.get("strategy_id")) in CANDIDATES:
            prior = latest.get(plan_id)
            rank = (row.get("promotion_eligible") is True, str(row.get("regraded_at") or row.get("resolved_at") or ""))
            prior_rank = (prior.get("promotion_eligible") is True, str(prior.get("regraded_at") or prior.get("resolved_at") or "")) if prior else None
            if prior is None or rank >= prior_rank:
                latest[plan_id] = row
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in latest.values():
        grouped[str(row.get("candidate_id") or row.get("strategy_id"))].append(row)
    candidates = []
    for candidate in CANDIDATES:
        values = grouped[candidate]
        qualified = [row for row in values if row.get("promotion_eligible") is True]
        dates = {str(row.get("session_date")) for row in qualified if row.get("session_date")}
        regime_dates = {name: set() for name in REGIMES}
        for row in qualified:
            tags = row.get("regime_tags") or []
            for tag in tags if isinstance(tags, list) else []:
                if tag in regime_dates:
                    regime_dates[tag].add(str(row.get("session_date")))
        blockers = []
        if not approval_present:
            blockers.append("kenny_shadow_evidence_approval_missing")
        if len(qualified) < 100 or len(dates) < 30:
            blockers.append("natural_forward_sample_incomplete")
        if any(len(values_) < 8 for values_ in regime_dates.values()):
            blockers.append("regime_date_coverage_incomplete")
        candidates.append({"candidate_id": candidate, "family_id": "mnq-smt-cisd-family",
                           "qualified_outcomes": len(qualified), "excluded_outcomes": len(values) - len(qualified),
                           "distinct_dates": len(dates), "targets": {"resolved_outcomes": 100, "distinct_dates": 30, "dates_per_regime": 8},
                           "regime_dates": {name: len(values_) for name, values_ in regime_dates.items()},
                           "status": "evidence_complete_for_gate" if not blockers else "collecting_or_blocked",
                           "blockers": blockers, "execution_enabled": False, "can_submit_orders": False})
    live_status = str((capability or {}).get("live_status") or "not_probed")
    return {"schema_version": 1, "provider": "mnq_smt_family_evidence_status",
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "source_labels": ["data/shadow_outcomes.jsonl", "data/databento_mes_capability.json",
                              "research/approvals/MNQ_SMT_FAMILY_SHADOW_EVIDENCE_APPROVAL_2026-08-24.md",
                              "research/preregistrations/MNQ_SMT_EVIDENCE_REGIME_LABELER_V1.md"],
            "live_feed": {"provider": "databento", "dataset": "GLBX.MDP3", "status": live_status,
                          "reason": (capability or {}).get("live_reason")},
            "evidence_planes": {"timely_discovery": "proxy_non_executable_not_promotion_eligible",
                                "promotion_measurement": "delayed_databento_mbo_regrade"},
            "approval_present": approval_present, "candidates": candidates,
            "execution_enabled": False, "can_submit_orders": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcomes", type=Path, default=DATA / "shadow_outcomes.jsonl")
    parser.add_argument("--capability", type=Path, default=DATA / "databento_mes_capability.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    approval = ROOT / "research" / "approvals" / "MNQ_SMT_FAMILY_SHADOW_EVIDENCE_APPROVAL_2026-08-24.md"
    try:
        approval_present = hashlib.sha256(approval.read_bytes()).hexdigest() == APPROVAL_SHA256
    except OSError:
        approval_present = False
    report = build_status(_read_jsonl(args.outcomes), capability=_read_json(args.capability), approval_present=approval_present)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
