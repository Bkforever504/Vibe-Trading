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
    from scripts.hypothesis_ledger import append_hypothesis_event, experiment_family_size, latest_hypotheses, read_jsonl
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from hypothesis_ledger import append_hypothesis_event, experiment_family_size, latest_hypotheses, read_jsonl


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
    "preregistration": "PROMO_PREREGISTRATION_SCHEMA_V2",
    "multiple_testing": "PROMO_FDR_BH_V2",
    "regime_coverage": "PROMO_REGIME_COVERAGE_V2",
    "blocker_ev": "PROMO_BLOCKER_NET_EV_V2",
    "latency": "PROMO_LATENCY_WINDOW_V2",
    "data_integrity": "PROMO_REPAIR_BACKFILL_REGRADE_V2",
    "revalidation": "PROMO_ROLLING_REVALIDATION_V2",
    "universe": "PROMO_UNIVERSE_VERSION_V2",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def benjamini_hochberg_adjust(p_values: dict[str, float]) -> dict[str, float]:
    """Return monotone BH q-values for the complete frozen experiment family."""
    if not p_values:
        return {}
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    size = len(ordered)
    adjusted: dict[str, float] = {}
    running = 1.0
    for rank_index in range(size - 1, -1, -1):
        candidate_id, p_value = ordered[rank_index]
        rank = rank_index + 1
        running = min(running, max(0.0, min(1.0, float(p_value))) * size / rank)
        adjusted[candidate_id] = min(1.0, running)
    return adjusted


def evaluate_promotion(
    result: dict[str, Any],
    rules: dict[str, Any],
    *,
    family_size: int,
    result_file: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    decided_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    checks: list[dict[str, str]] = []

    def record(name: str, status: str, reason: str) -> None:
        checks.append({"rule_id": RULE_IDS[name], "status": status, "reason": reason})

    def required_number(container: dict[str, Any], key: str) -> float | None:
        value = container.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    sample = required_number(result, "n_resolved")
    record("sample", "unavailable" if sample is None else "pass" if sample >= int(rules.get("minimum_resolved_outcomes", 30)) else "fail", "insufficient_resolved_outcomes")
    sessions = required_number(result, "distinct_sessions")
    record("sessions", "unavailable" if sessions is None else "pass" if sessions >= int(rules.get("minimum_distinct_sessions", 20)) else "fail", "insufficient_distinct_sessions")
    dsr_lb = required_number(result, "dsr_lower_bound")
    record("dsr", "unavailable" if dsr_lb is None else "pass" if dsr_lb > 0 else "fail", "dsr_bonferroni_lower_bound_not_positive")
    pbo = required_number(result, "pbo")
    record("pbo", "unavailable" if pbo is None else "pass" if pbo < float(rules.get("pbo_maximum", 0.5)) else "fail", "pbo_unavailable_or_too_high")
    expectancy = required_number(result, "expectancy_lower_95_ci")
    expectancy_minimum = float(rules.get("expectancy", {}).get("minimum_lower_95_ci", 0))
    record("expectancy", "unavailable" if expectancy is None else "pass" if expectancy > expectancy_minimum else "fail", "expectancy_lower_bound_not_positive")
    decay = result.get("decay") if isinstance(result.get("decay"), dict) else {}
    record("decay", "unavailable" if "same_sign" not in decay else "pass" if decay.get("same_sign") is True else "fail", "decay_sign_failed")
    placebo = result.get("placebo") if isinstance(result.get("placebo"), dict) else {}
    placebo_status = placebo.get("status")
    record("placebo", "unavailable" if placebo_status in {None, "unavailable"} else "pass" if placebo_status == rules.get("placebo", {}).get("required_status", "pass") else "fail", "placebo_failed_or_unavailable")
    cost = result.get("cost_stress") if isinstance(result.get("cost_stress"), dict) else {}
    cost_status = cost.get("status")
    record("cost", "unavailable" if cost_status in {None, "unavailable"} else "pass" if cost_status == "pass" else "fail", "doubled_cost_stress_failed_or_unavailable")

    prereg_rules = rules.get("preregistration")
    if isinstance(prereg_rules, dict):
        actual_schema = result.get("preregistration_schema")
        required_schema = prereg_rules.get("required_schema", "hypothesis-v2")
        record("preregistration", "unavailable" if not actual_schema else "pass" if actual_schema == required_schema else "fail", "preregistration_schema_missing_or_outdated")

    multiple_rules = rules.get("multiple_testing")
    if isinstance(multiple_rules, dict):
        evidence = result.get("multiple_testing") if isinstance(result.get("multiple_testing"), dict) else {}
        required_keys = {"method", "family_size", "adjusted_q", "selected"}
        if not required_keys.issubset(evidence):
            status = "unavailable"
        else:
            adjusted_q = required_number(evidence, "adjusted_q")
            status = "pass" if (
                evidence.get("method") == multiple_rules.get("method", "benjamini_hochberg")
                and int(evidence.get("family_size") or 0) == family_size
                and adjusted_q is not None
                and adjusted_q <= float(multiple_rules.get("alpha", 0.05))
                and evidence.get("selected") is True
            ) else "fail"
        record("multiple_testing", status, "fdr_adjustment_missing_family_mismatch_or_not_selected")

    regime_rules = rules.get("regime_coverage")
    if isinstance(regime_rules, dict):
        evidence = result.get("regime_coverage") if isinstance(result.get("regime_coverage"), dict) else {}
        required_regimes = list(regime_rules.get("required_regimes", []))
        minimum_dates = int(regime_rules.get("minimum_independent_dates_per_regime", 1))
        if not required_regimes or any(regime not in evidence for regime in required_regimes):
            status = "unavailable"
        else:
            counts = [
                required_number(evidence.get(regime, {}) if isinstance(evidence.get(regime), dict) else {}, "independent_dates")
                for regime in required_regimes
            ]
            status = "unavailable" if any(value is None for value in counts) else "pass" if all(value >= minimum_dates for value in counts if value is not None) else "fail"
        record("regime_coverage", status, "minimum_independent_dates_per_regime_not_met")

    blocker_rules = rules.get("blocker_removal")
    if isinstance(blocker_rules, dict):
        if result.get("change_type") != "blocker_removal":
            status = "pass"
        else:
            evidence = result.get("blocker_removal") if isinstance(result.get("blocker_removal"), dict) else {}
            ev_lb = required_number(evidence, "expected_value_lower_95_ci")
            if ev_lb is None or "basis" not in evidence or "loss_severity_included" not in evidence:
                status = "unavailable"
            else:
                status = "pass" if (
                    evidence.get("basis") == blocker_rules.get("required_basis", "net_after_costs")
                    and evidence.get("loss_severity_included") is True
                    and ev_lb > float(blocker_rules.get("minimum_net_ev_lower_95_ci", 0))
                ) else "fail"
        record("blocker_ev", status, "blocker_removal_net_ev_lower_bound_not_positive")

    latency_rules = rules.get("latency")
    if isinstance(latency_rules, dict):
        evidence = result.get("latency") if isinstance(result.get("latency"), dict) else {}
        observations = required_number(evidence, "observations")
        fraction = required_number(evidence, "p90_fraction_of_expected_window")
        if observations is None or fraction is None:
            status = "unavailable"
        else:
            status = "pass" if (
                observations >= int(latency_rules.get("minimum_observations", 30))
                and fraction <= float(latency_rules.get("maximum_p90_fraction_of_expected_window", 0.2))
            ) else "fail"
        record("latency", status, "p90_alert_latency_exceeds_setup_window_budget")

    integrity_rules = rules.get("data_integrity")
    if isinstance(integrity_rules, dict):
        evidence = result.get("data_integrity") if isinstance(result.get("data_integrity"), dict) else {}
        repaired = evidence.get("source_repair_detected")
        if repaired is None:
            status = "unavailable"
        elif repaired is False:
            status = "pass"
        else:
            contaminated = required_number(evidence, "contaminated_outcomes_remaining")
            if contaminated is None or "backfill_status" not in evidence or "regrade_status" not in evidence:
                status = "unavailable"
            else:
                status = "pass" if (
                    evidence.get("backfill_status") == "complete"
                    and evidence.get("regrade_status") == "complete"
                    and contaminated == 0
                ) else "fail"
        record("data_integrity", status, "source_repair_backfill_or_regrade_incomplete")

    revalidation_rules = rules.get("revalidation")
    if isinstance(revalidation_rules, dict):
        evidence = result.get("revalidation") if isinstance(result.get("revalidation"), dict) else {}
        windows = required_number(evidence, "rolling_windows")
        brier_skill = required_number(evidence, "latest_brier_skill")
        last_revalidated = _parse_utc(evidence.get("last_revalidated_at"))
        if windows is None or brier_skill is None or last_revalidated is None:
            status = "unavailable"
        else:
            age_days = max(0.0, (decided_at - last_revalidated).total_seconds() / 86400)
            status = "pass" if (
                windows >= int(revalidation_rules.get("minimum_rolling_windows", 3))
                and brier_skill > float(revalidation_rules.get("minimum_latest_brier_skill", 0))
                and age_days <= float(revalidation_rules.get("maximum_age_days", 30))
            ) else "fail"
        record("revalidation", status, "rolling_validation_failed_or_stale")

    universe_rules = rules.get("universe")
    if isinstance(universe_rules, dict):
        evidence = result.get("universe") if isinstance(result.get("universe"), dict) else {}
        required_keys = {"version", "hash", "membership_as_of", "drift_status"}
        if not required_keys.issubset(evidence) or not all(evidence.get(key) for key in required_keys):
            status = "unavailable"
        else:
            digest = str(evidence.get("hash"))
            allowed = set(universe_rules.get("allowed_drift_statuses", ["frozen", "unchanged"]))
            status = "pass" if digest.startswith("sha256:") and len(digest) == 71 and evidence.get("drift_status") in allowed else "fail"
        record("universe", status, "universe_version_missing_or_drifted")

    failures = [{"rule_id": row["rule_id"], "reason": row["reason"]} for row in checks if row["status"] == "fail"]
    unavailable = [{"rule_id": row["rule_id"], "reason": row["reason"]} for row in checks if row["status"] == "unavailable"]
    sample_incomplete = any(item["rule_id"] in {RULE_IDS["sample"], RULE_IDS["sessions"]} for item in failures)
    decision = "hold" if sample_incomplete or unavailable else "reject" if failures else "promote"
    evidence_digest = hashlib.sha256(json.dumps(result, separators=(",", ":"), sort_keys=True).encode()).hexdigest()[:16]
    return {
        "schema_version": 2,
        "decision_id": hashlib.sha256(f"{result.get('candidate_id')}|{result_file}|{rules.get('rule_version')}|{evidence_digest}|{decision}".encode()).hexdigest()[:24],
        "decided_at": decided_at.isoformat().replace("+00:00", "Z"),
        "candidate_id": result.get("candidate_id"),
        "decision": decision,
        "rule_version": rules.get("rule_version"),
        "family_size": family_size,
        "result_file": result_file,
        "failed_rules": failures,
        "unavailable_rules": unavailable,
        "rule_results": checks,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def run_gate(*, replay_path: Path, rules_path: Path = RULES, hypothesis_path: Path = HYPOTHESES, family_path: Path = FAMILY, decisions_path: Path = DECISIONS, update_hypotheses: bool = True) -> dict[str, Any]:
    replay = _read_json(replay_path)
    rules = _read_json(rules_path)
    size = experiment_family_size(family_path)
    current = latest_hypotheses(hypothesis_path)
    results = [dict(row) for row in replay.get("results", []) if isinstance(row, dict)]
    multiple_rules = rules.get("multiple_testing")
    if isinstance(multiple_rules, dict):
        family_ids = {
            str(row.get("candidate_id"))
            for row in read_jsonl(family_path)
            if row.get("candidate_id")
        }
        by_id = {str(row.get("candidate_id")): row for row in results if row.get("candidate_id")}
        raw_p_values: dict[str, float] = {}
        for candidate_id in family_ids:
            evidence = by_id.get(candidate_id, {}).get("multiple_testing")
            raw = evidence.get("raw_p_value") if isinstance(evidence, dict) else None
            raw_p_values[candidate_id] = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 1.0
        adjusted = benjamini_hochberg_adjust(raw_p_values)
        alpha = float(multiple_rules.get("alpha", 0.05))
        for row in results:
            candidate_id = str(row.get("candidate_id") or "")
            existing = row.get("multiple_testing") if isinstance(row.get("multiple_testing"), dict) else {}
            raw = existing.get("raw_p_value")
            if candidate_id in family_ids and isinstance(raw, (int, float)) and not isinstance(raw, bool):
                q_value = adjusted[candidate_id]
                row["multiple_testing"] = {
                    "method": multiple_rules.get("method", "benjamini_hochberg"),
                    "family_size": size,
                    "raw_p_value": float(raw),
                    "adjusted_q": q_value,
                    "selected": q_value <= alpha,
                    "source": "computed_from_raw_p_values_and_frozen_family_ledger",
                }
            else:
                row["multiple_testing"] = {
                    "method": multiple_rules.get("method", "benjamini_hochberg"),
                    "family_size": size,
                    "source": "raw_p_value_unavailable",
                }
    decisions = [evaluate_promotion(row, rules, family_size=size, result_file=str(replay_path.resolve())) for row in results]
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    existing_ids = {json.loads(line).get("decision_id") for line in decisions_path.read_text(encoding="utf-8-sig").splitlines()} if decisions_path.exists() else set()
    with decisions_path.open("a", encoding="utf-8", newline="\n") as handle:
        for decision in decisions:
            if decision["decision_id"] not in existing_ids:
                handle.write(json.dumps(decision, separators=(",", ":"), sort_keys=True) + "\n")
    if update_hypotheses:
        by_id = {row.get("candidate_id"): row for row in results}
        for decision in decisions:
            prior = current.get(str(decision["candidate_id"]))
            result = by_id.get(decision["candidate_id"], {})
            if not prior or prior.get("status") not in {"development", "shadow", "paper_review", "approved"}:
                continue
            prior_status = str(prior.get("status"))
            if prior_status == "development":
                next_status = "shadow" if decision["decision"] == "promote" else "rejected" if decision["decision"] == "reject" else "development"
            elif prior_status == "approved":
                next_status = "approved" if decision["decision"] == "promote" else "paper_review"
            elif prior_status == "paper_review":
                next_status = "paper_review" if decision["decision"] == "promote" else "shadow"
            else:
                # Shadow research remains observable while weak/stale evidence is
                # collected; it is never silently upgraded or granted authority.
                next_status = "shadow"
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
