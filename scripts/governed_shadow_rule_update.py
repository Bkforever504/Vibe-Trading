#!/usr/bin/env python3
"""Turn reconciled outcomes into reviewable rule nominations, never auto-tuning."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VIBE_HOME = Path.home() / ".vibe-trading"
OUTCOME_PATH = VIBE_HOME / "data" / "governed_shadow_outcomes.jsonl"
DECISION_PATH = Path(__file__).resolve().parents[1] / "data" / "governed_shadow_decision_ledger.jsonl"
NOMINATION_PATH = VIBE_HOME / "data" / "governed_shadow_rule_nominations.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "governed-shadow-rule-updates.json"
MIN_SAMPLE = 10


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def build_nominations(outcomes: Iterable[Mapping[str, Any]], decisions: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    decision_by_id = {str(row.get("event_id")): row for row in decisions}
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in outcomes:
        if row.get("reconciliation_status") != "underlying_proxy_reconciled" or row.get("outcome_r") is None:
            continue
        groups[(str(row.get("setup") or "unknown"), str(row.get("direction") or "unknown"))].append(row)
    nominations: list[dict[str, Any]] = []
    for (setup, direction), rows in sorted(groups.items()):
        sample = len(rows)
        wins = sum(float(row.get("outcome_r") or 0.0) > 0 for row in rows)
        mean_r = sum(float(row.get("outcome_r") or 0.0) for row in rows) / sample
        vetoed = [row for row in rows if row.get("governed_decision") == "shadow_rejected"]
        vetoed_wins = sum(float(row.get("outcome_r") or 0.0) > 0 for row in vetoed)
        blocker_counts: dict[str, int] = defaultdict(int)
        for outcome in vetoed:
            decision = decision_by_id.get(str(outcome.get("decision_event_id")), {})
            for blocker in decision.get("blockers") or []:
                blocker_counts[str(blocker)] += 1
        action = "hold_collect_more_evidence"
        rationale = f"sample {sample} is below frozen minimum {MIN_SAMPLE}"
        if sample >= MIN_SAMPLE and vetoed and vetoed_wins / len(vetoed) >= 0.60:
            action = "nominate_veto_calibration_review"
            rationale = "vetoed counterfactual win rate is at least 60%; review the dominant blocker without weakening hard risk gates"
        elif sample >= MIN_SAMPLE and mean_r <= 0:
            action = "nominate_setup_tightening_or_pause"
            rationale = "cost-unadjusted underlying proxy expectancy is non-positive"
        elif sample >= MIN_SAMPLE:
            action = "retain_rule_observe_only"
            rationale = "underlying proxy evidence is positive but cannot promote without executable cost evidence"
        evidence = {
            "setup": setup,
            "direction": direction,
            "sample_count": sample,
            "win_rate": round(wins / sample, 4),
            "mean_outcome_r": round(mean_r, 4),
            "vetoed_count": len(vetoed),
            "vetoed_win_rate": round(vetoed_wins / len(vetoed), 4) if vetoed else None,
            "veto_blocker_counts": dict(sorted(blocker_counts.items())),
        }
        nominations.append({
            "nomination_id": _hash({"rule_family": [setup, direction], "evidence": evidence, "policy_version": 1}),
            "rule_family": {"setup": setup, "direction": direction},
            "action": action,
            "rationale": rationale,
            "evidence": evidence,
            "promotion_status": "human_review_required",
            "automatic_parameter_changes": False,
            "execution_enabled": False,
            "can_submit_orders": False,
        })
    return nominations


def run(*, outcome_path: Path = OUTCOME_PATH, decision_path: Path = DECISION_PATH, nomination_path: Path = NOMINATION_PATH, report_path: Path = REPORT_PATH) -> dict[str, Any]:
    outcomes, decisions = _read_jsonl(outcome_path), _read_jsonl(decision_path)
    nominations = build_nominations(outcomes, decisions)
    existing = {str(row.get("nomination_id")) for row in _read_jsonl(nomination_path)}
    review_nominations = [row for row in nominations if str(row.get("action") or "").startswith("nominate_")]
    new = [row for row in review_nominations if str(row.get("nomination_id")) not in existing]
    if new:
        nomination_path.parent.mkdir(parents=True, exist_ok=True)
        with nomination_path.open("a", encoding="utf-8") as handle:
            for row in new:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    report = {
        "provider": "governed_shadow_rule_update",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "minimum_sample": MIN_SAMPLE,
        "reconciled_outcomes": len(outcomes),
        "rule_families": len(nominations),
        "review_nominations": len(review_nominations),
        "new_nominations": len(new),
        "nominations": nominations,
        "policy": "outcomes_may_nominate_review_only; no automatic rule or parameter mutation",
        "automatic_parameter_changes": False,
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run()
    print(json.dumps({key: report[key] for key in ("reconciled_outcomes", "rule_families", "review_nominations", "new_nominations")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
