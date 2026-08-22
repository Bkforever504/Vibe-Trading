from __future__ import annotations

import json
from pathlib import Path

from scripts.hypothesis_ledger import append_hypothesis_event, latest_hypotheses, record_frozen_spec
from scripts.promotion_gate import evaluate_promotion, run_gate


HASH = "sha256:" + "f" * 64


def _rules() -> dict:
    return {
        "rule_version": "test-v1",
        "minimum_resolved_outcomes": 30,
        "minimum_distinct_sessions": 20,
        "pbo_maximum": 0.5,
        "expectancy": {"minimum_lower_95_ci": 0},
        "placebo": {"required_status": "pass"},
    }


def _passing() -> dict:
    return {"candidate_id": "lane-a", "n_resolved": 40, "distinct_sessions": 30, "dsr": 0.95, "dsr_lower_bound": 0.2, "pbo": 0.2, "expectancy_lower_95_ci": 0.1, "decay": {"same_sign": True}, "placebo": {"status": "pass"}, "cost_stress": {"status": "pass"}}


def test_promotion_decision_requires_every_frozen_rule() -> None:
    promoted = evaluate_promotion(_passing(), _rules(), family_size=3, result_file="result.json")
    assert promoted["decision"] == "promote"
    assert promoted["failed_rules"] == []
    held = evaluate_promotion({**_passing(), "n_resolved": 12}, _rules(), family_size=3, result_file="result.json")
    assert held["decision"] == "hold"
    assert held["failed_rules"][0]["rule_id"] == "PROMO_MIN_SAMPLE_V1"
    rejected = evaluate_promotion({**_passing(), "pbo": 0.8}, _rules(), family_size=3, result_file="result.json")
    assert rejected["decision"] == "reject"


def test_gate_appends_auditable_decision_and_only_promotes_to_shadow(tmp_path: Path) -> None:
    replay = tmp_path / "replay.json"
    replay.write_text(json.dumps({"results": [_passing()]}), encoding="utf-8")
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
