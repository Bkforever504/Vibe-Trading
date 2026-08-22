#!/usr/bin/env python3
"""Apply frozen promotion rules to replay evidence; never grant order authority."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.hypothesis_ledger import append_hypothesis_event, experiment_family_size, latest_hypotheses
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from hypothesis_ledger import append_hypothesis_event, experiment_family_size, latest_hypotheses


ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "data" / "promotion_rules.json"
HYPOTHESES = ROOT / "data" / "hypothesis_ledger.jsonl"
FAMILY = ROOT / "data" / "experiment_family.jsonl"
DECISIONS = ROOT / "data" / "promotion_decisions.jsonl"


RULE_IDS = {
    "sample": "PROMO_MIN_SAMPLE_V1",
    "sessions": "PROMO_MIN_SESSIONS_V1",
    "dsr": "PROMO_DSR_BONFERRONI_LB_V1",
    "pbo": "PROMO_PBO_MAX_V1",
    "expectancy": "PROMO_EXPECTANCY_LB_V1",
    "decay": "PROMO_DECAY_SIGN_V1",
    "placebo": "PROMO_PLACEBO_SHUFFLED_LABELS_V1",
    "cost": "PROMO_DOUBLED_COST_STRESS_V1",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def evaluate_promotion(result: dict[str, Any], rules: dict[str, Any], *, family_size: int, result_file: str) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    unavailable: list[dict[str, str]] = []
    checks = [
        ("sample", int(result.get("n_resolved") or 0) >= int(rules.get("minimum_resolved_outcomes", 30)), "insufficient_resolved_outcomes"),
        ("sessions", int(result.get("distinct_sessions") or 0) >= int(rules.get("minimum_distinct_sessions", 20)), "insufficient_distinct_sessions"),
        ("dsr", result.get("dsr_lower_bound") is not None and float(result["dsr_lower_bound"]) > 0, "dsr_bonferroni_lower_bound_not_positive"),
        ("pbo", result.get("pbo") is not None and float(result["pbo"]) < float(rules.get("pbo_maximum", 0.5)), "pbo_unavailable_or_too_high"),
        ("expectancy", result.get("expectancy_lower_95_ci") is not None and float(result["expectancy_lower_95_ci"]) > float(rules.get("expectancy", {}).get("minimum_lower_95_ci", 0)), "expectancy_lower_bound_not_positive"),
        ("decay", result.get("decay", {}).get("same_sign") is True, "decay_sign_failed"),
        ("placebo", result.get("placebo", {}).get("status") == rules.get("placebo", {}).get("required_status", "pass"), "placebo_failed_or_unavailable"),
        ("cost", result.get("cost_stress", {}).get("status") == "pass", "doubled_cost_stress_failed_or_unavailable"),
    ]
    for name, passed, reason in checks:
        if passed:
            continue
        is_unavailable = (
            (name == "pbo" and result.get("pbo") is None)
            or (name == "placebo" and result.get("placebo", {}).get("status") == "unavailable")
            or (name == "cost" and result.get("cost_stress", {}).get("status") == "unavailable")
        )
        target = unavailable if is_unavailable else failures
        target.append({"rule_id": RULE_IDS[name], "reason": reason})
    sample_incomplete = any(item["rule_id"] in {RULE_IDS["sample"], RULE_IDS["sessions"]} for item in failures)
    decision = "hold" if sample_incomplete or unavailable else "reject" if failures else "promote"
    return {
        "schema_version": 1,
        "decision_id": hashlib.sha256(f"{result.get('candidate_id')}|{result_file}|{decision}".encode()).hexdigest()[:24],
        "decided_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "candidate_id": result.get("candidate_id"),
        "decision": decision,
        "rule_version": rules.get("rule_version"),
        "family_size": family_size,
        "result_file": result_file,
        "failed_rules": failures,
        "unavailable_rules": unavailable,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def run_gate(*, replay_path: Path, rules_path: Path = RULES, hypothesis_path: Path = HYPOTHESES, family_path: Path = FAMILY, decisions_path: Path = DECISIONS, update_hypotheses: bool = True) -> dict[str, Any]:
    replay = _read_json(replay_path)
    rules = _read_json(rules_path)
    size = experiment_family_size(family_path)
    current = latest_hypotheses(hypothesis_path)
    decisions = [evaluate_promotion(row, rules, family_size=size, result_file=str(replay_path.resolve())) for row in replay.get("results", []) if isinstance(row, dict)]
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids = {json.loads(line).get("decision_id") for line in decisions_path.read_text(encoding="utf-8-sig").splitlines()} if decisions_path.exists() else set()
    with decisions_path.open("a", encoding="utf-8", newline="\n") as handle:
        for decision in decisions:
            if decision["decision_id"] not in existing_ids:
                handle.write(json.dumps(decision, separators=(",", ":"), sort_keys=True) + "\n")
    if update_hypotheses:
        by_id = {row.get("candidate_id"): row for row in replay.get("results", []) if isinstance(row, dict)}
        for decision in decisions:
            prior = current.get(str(decision["candidate_id"]))
            result = by_id.get(decision["candidate_id"], {})
            if not prior or prior.get("status") != "development":
                continue
            next_status = "shadow" if decision["decision"] == "promote" else "rejected" if decision["decision"] == "reject" else "development"
            reasons = [item["rule_id"] for item in [*decision["failed_rules"], *decision["unavailable_rules"]]] or ["ALL_PROMOTION_RULES_PASS"]
            append_hypothesis_event({**prior, "status": next_status, "n_resolved": int(result.get("n_resolved") or 0), "distinct_sessions": int(result.get("distinct_sessions") or 0), "dsr": result.get("dsr"), "dsr_lower_bound": result.get("dsr_lower_bound"), "pbo": result.get("pbo"), "expectancy_lb": result.get("expectancy_lower_95_ci"), "last_evaluated_at": decision["decided_at"], "verdict_reason": f"{','.join(reasons)} result={decision['result_file']}"}, hypothesis_path, event_type="promotion_gate")
    return {"decisions": decisions, "family_size": size, "execution_enabled": False, "can_submit_orders": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path)
    parser.add_argument("--no-ledger-update", action="store_true")
    args = parser.parse_args()
    report = run_gate(replay_path=args.replay, update_hypotheses=not args.no_ledger_update)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
