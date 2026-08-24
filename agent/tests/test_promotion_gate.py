from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.hypothesis_ledger import append_hypothesis_event, latest_hypotheses, record_frozen_spec
from scripts.promotion_gate import benjamini_hochberg_adjust, evaluate_promotion, run_gate


HASH = "sha256:" + "f" * 64


def _rules() -> dict:
    return {
        "rule_version": "test-v2",
        "minimum_resolved_outcomes": 30,
        "minimum_distinct_sessions": 20,
        "pbo_maximum": 0.5,
        "expectancy": {"minimum_lower_95_ci": 0},
        "placebo": {"required_status": "pass"},
        "preregistration": {"required_schema": "hypothesis-v2"},
        "multiple_testing": {"method": "benjamini_hochberg", "alpha": 0.05},
        "regime_coverage": {
            "required_regimes": ["trend", "chop", "high_vol", "low_vol"],
            "minimum_independent_dates_per_regime": 8,
        },
        "blocker_removal": {
            "minimum_net_ev_lower_95_ci": 0,
            "required_basis": "net_after_costs",
        },
        "latency": {
            "maximum_p90_fraction_of_expected_window": 0.2,
            "minimum_observations": 30,
        },
        "data_integrity": {"require_backfill_and_regrade_after_source_repair": True},
        "revalidation": {
            "minimum_rolling_windows": 3,
            "minimum_latest_brier_skill": 0,
            "maximum_age_days": 30,
        },
        "universe": {"allowed_drift_statuses": ["frozen", "unchanged"]},
    }


def _passing() -> dict:
    return {
        "candidate_id": "lane-a",
        "preregistration_schema": "hypothesis-v2",
        "n_resolved": 120,
        "distinct_sessions": 40,
        "dsr": 0.95,
        "dsr_lower_bound": 0.2,
        "pbo": 0.2,
        "expectancy_lower_95_ci": 0.1,
        "decay": {"same_sign": True},
        "placebo": {"status": "pass"},
        "cost_stress": {"status": "pass"},
        "multiple_testing": {
            "method": "benjamini_hochberg",
            "family_size": 3,
            "raw_p_value": 0.01,
            "adjusted_q": 0.02,
            "selected": True,
        },
        "regime_coverage": {
            regime: {"independent_dates": 8}
            for regime in ("trend", "chop", "high_vol", "low_vol")
        },
        "change_type": "new_detector",
        "latency": {"observations": 40, "p90_fraction_of_expected_window": 0.15},
        "data_integrity": {"source_repair_detected": False},
        "revalidation": {
            "rolling_windows": 4,
            "latest_brier_skill": 0.03,
            "last_revalidated_at": "2026-08-20T00:00:00Z",
        },
        "universe": {
            "version": "us-liquid-v1",
            "hash": "sha256:" + "a" * 64,
            "membership_as_of": "2026-08-01",
            "drift_status": "frozen",
        },
    }


def test_promotion_decision_requires_every_frozen_rule() -> None:
    now = datetime(2026, 8, 23, tzinfo=timezone.utc)
    promoted = evaluate_promotion(_passing(), _rules(), family_size=3, result_file="result.json", now=now)
    assert promoted["decision"] == "promote"
    assert promoted["failed_rules"] == []
    held = evaluate_promotion({**_passing(), "n_resolved": 12}, _rules(), family_size=3, result_file="result.json", now=now)
    assert held["decision"] == "hold"
    assert held["failed_rules"][0]["rule_id"] == "PROMO_MIN_SAMPLE_V1"
    rejected = evaluate_promotion({**_passing(), "pbo": 0.8}, _rules(), family_size=3, result_file="result.json", now=now)
    assert rejected["decision"] == "reject"


def test_bh_adjustment_is_computed_across_complete_family() -> None:
    adjusted = benjamini_hochberg_adjust({"a": 0.01, "b": 0.03, "c": 0.20})
    assert adjusted == pytest.approx({"a": 0.03, "b": 0.045, "c": 0.20})


def test_v2_governance_gates_hold_missing_evidence_and_reject_measured_failures() -> None:
    now = datetime(2026, 8, 23, tzinfo=timezone.utc)
    missing = _passing()
    missing.pop("latency")
    held = evaluate_promotion(missing, _rules(), family_size=3, result_file="result.json", now=now)
    assert held["decision"] == "hold"
    assert {row["rule_id"] for row in held["unavailable_rules"]} == {"PROMO_LATENCY_WINDOW_V2"}

    cases = {
        "PROMO_FDR_BH_V2": {"multiple_testing": {**_passing()["multiple_testing"], "adjusted_q": 0.08}},
        "PROMO_REGIME_COVERAGE_V2": {
            "regime_coverage": {**_passing()["regime_coverage"], "chop": {"independent_dates": 4}}
        },
        "PROMO_LATENCY_WINDOW_V2": {"latency": {"observations": 40, "p90_fraction_of_expected_window": 0.24}},
        "PROMO_ROLLING_REVALIDATION_V2": {
            "revalidation": {**_passing()["revalidation"], "latest_brier_skill": -0.01}
        },
        "PROMO_UNIVERSE_VERSION_V2": {"universe": {**_passing()["universe"], "drift_status": "changed"}},
    }
    for rule_id, replacement in cases.items():
        decision = evaluate_promotion({**_passing(), **replacement}, _rules(), family_size=3, result_file="result.json", now=now)
        assert decision["decision"] == "reject", rule_id
        assert rule_id in {row["rule_id"] for row in decision["failed_rules"]}


def test_blocker_ev_and_source_repair_use_value_and_clean_regraded_history() -> None:
    now = datetime(2026, 8, 23, tzinfo=timezone.utc)
    blocker = {
        **_passing(),
        "change_type": "blocker_removal",
        "blocker_removal": {
            "basis": "net_after_costs",
            "expected_value_lower_95_ci": -0.05,
            "loss_severity_included": True,
        },
    }
    rejected = evaluate_promotion(blocker, _rules(), family_size=3, result_file="result.json", now=now)
    assert rejected["decision"] == "reject"
    assert "PROMO_BLOCKER_NET_EV_V2" in {row["rule_id"] for row in rejected["failed_rules"]}

    repaired = {
        **_passing(),
        "data_integrity": {
            "source_repair_detected": True,
            "backfill_status": "complete",
            "regrade_status": "complete",
            "contaminated_outcomes_remaining": 1,
        },
    }
    rejected = evaluate_promotion(repaired, _rules(), family_size=3, result_file="result.json", now=now)
    assert rejected["decision"] == "reject"
    assert "PROMO_REPAIR_BACKFILL_REGRADE_V2" in {row["rule_id"] for row in rejected["failed_rules"]}


def test_gate_appends_auditable_decision_and_only_promotes_to_shadow(tmp_path: Path) -> None:
    replay = tmp_path / "replay.json"
    passing = _passing()
    passing["multiple_testing"] = {**passing["multiple_testing"], "family_size": 1}
    replay.write_text(json.dumps({"results": [passing]}), encoding="utf-8")
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps(_rules()), encoding="utf-8")
    hypothesis = tmp_path / "hypothesis.jsonl"
    family = tmp_path / "family.jsonl"
    decisions = tmp_path / "decisions.jsonl"
    record_frozen_spec(candidate_id="lane-a", family_id="family-a", spec_hash=HASH, spec_path="research/lane-a.md", origin="research", path=family)
    append_hypothesis_event({"id": "lane-a", "spec_hash": HASH, "spec_path": "research/lane-a.md", "family_id": "family-a", "origin": "research", "status": "proposed", "n_resolved": 0, "distinct_sessions": 0}, hypothesis)
    append_hypothesis_event({"id": "lane-a", "spec_hash": HASH, "spec_path": "research/lane-a.md", "family_id": "family-a", "origin": "research", "status": "development", "n_resolved": 0, "distinct_sessions": 0}, hypothesis)

    report = run_gate(replay_path=replay, rules_path=rules, hypothesis_path=hypothesis, family_path=family, decisions_path=decisions)

    assert report["decisions"][0]["decision"] == "promote"
    assert latest_hypotheses(hypothesis)["lane-a"]["status"] == "shadow"
    decision = json.loads(decisions.read_text(encoding="utf-8").splitlines()[0])
    assert decision["result_file"] == str(replay.resolve())
    assert decision["can_submit_orders"] is False


def test_gate_periodically_demotes_stale_approved_candidate_to_paper_review(tmp_path: Path) -> None:
    replay = tmp_path / "replay.json"
    stale = _passing()
    stale["multiple_testing"] = {**stale["multiple_testing"], "family_size": 1}
    stale["revalidation"] = {**stale["revalidation"], "last_revalidated_at": "2020-01-01T00:00:00Z"}
    replay.write_text(json.dumps({"results": [stale]}), encoding="utf-8")
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps(_rules()), encoding="utf-8")
    hypothesis = tmp_path / "hypothesis.jsonl"
    family = tmp_path / "family.jsonl"
    decisions = tmp_path / "decisions.jsonl"
    record_frozen_spec(candidate_id="lane-a", family_id="family-a", spec_hash=HASH, spec_path="research/lane-a.md", origin="research", path=family)
    base = {"id": "lane-a", "spec_hash": HASH, "spec_path": "research/lane-a.md", "family_id": "family-a", "origin": "research", "n_resolved": 0, "distinct_sessions": 0}
    for status in ("proposed", "development", "shadow", "paper_review", "approved"):
        append_hypothesis_event({**base, "status": status}, hypothesis)

    report = run_gate(replay_path=replay, rules_path=rules, hypothesis_path=hypothesis, family_path=family, decisions_path=decisions)

    assert report["decisions"][0]["decision"] == "reject"
    assert latest_hypotheses(hypothesis)["lane-a"]["status"] == "paper_review"
    assert latest_hypotheses(hypothesis)["lane-a"]["can_submit_orders"] is False
