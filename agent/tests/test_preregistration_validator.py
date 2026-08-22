from __future__ import annotations

import json
from pathlib import Path

from scripts.preregistration_validator import compute_spec_hash_text, discover_specs, validate_spec
from scripts.hypothesis_ledger import append_hypothesis_event
from scripts.weekly_candidate_intake import run_intake


def _spec_text(spec_hash: str = "sha256:<SPEC_HASH>") -> str:
    return f"""# Trading Hypothesis Preregistration

Preregistration Schema: hypothesis-v1
Spec ID: candidate-a
Family ID: family-a
Origin: research
Status: frozen
Spec Hash: {spec_hash}

## Entry Rule
Enter on the next completed bar after the fixed signal confirms.

## Exit Rule
Exit at the frozen stop, target, or session time, adverse first.

## Universe
Use the point-in-time SPY and QQQ universe defined before evaluation.

## Timestamp Basis
All observations use America/New_York exchange timestamps available then.

## Execution Policy
execution_enabled=false
can_submit_orders=false
Use executable ask entries and executable bid exits with no midpoint claim.

## Cost Stress
Use commissions, one tick per side, and doubled-cost stress.
"""


def _write_valid_spec(path: Path) -> None:
    draft = _spec_text()
    path.write_text(_spec_text(compute_spec_hash_text(draft)), encoding="utf-8")


def test_validator_accepts_complete_frozen_spec_with_matching_hash(tmp_path: Path) -> None:
    path = tmp_path / "candidate.md"
    _write_valid_spec(path)
    result = validate_spec(path)
    assert result["valid"] is True
    assert result["errors"] == []
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False


def test_validator_rejects_missing_rule_and_hash_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "candidate.md"
    text = _spec_text("sha256:" + "0" * 64).replace(
        "Exit at the frozen stop, target, or session time, adverse first.", "short"
    )
    path.write_text(text, encoding="utf-8")
    errors = validate_spec(path)["errors"]
    assert "missing_or_empty_section:Exit Rule" in errors
    assert "spec_hash_mismatch" in errors


def test_weekly_intake_is_idempotent_and_only_develops_valid_specs(tmp_path: Path) -> None:
    valid = tmp_path / "valid.md"
    invalid = tmp_path / "invalid.md"
    _write_valid_spec(valid)
    invalid.write_text(_spec_text("sha256:" + "0" * 64), encoding="utf-8")
    hypothesis = tmp_path / "hypothesis.jsonl"
    family = tmp_path / "family.jsonl"

    first = run_intake(spec_paths=[valid, invalid], hypothesis_path=hypothesis, family_path=family)
    second = run_intake(spec_paths=[valid, invalid], hypothesis_path=hypothesis, family_path=family)

    assert first["development_events_added"] == 1
    assert first["invalid_specs"] == 1
    assert first["experiment_wide_family_size"] == 1
    assert second["development_events_added"] == 0
    assert second["experiment_wide_family_size"] == 1
    rows = [json.loads(line) for line in hypothesis.read_text(encoding="utf-8").splitlines()]
    assert [row["status"] for row in rows] == ["proposed", "development"]
    assert all(row["can_submit_orders"] is False for row in rows)


def test_discovery_ignores_unfilled_templates(tmp_path: Path) -> None:
    template = tmp_path / "PREREGISTRATION_TEMPLATE.md"
    candidate = tmp_path / "CANDIDATE_PREREGISTRATION.md"
    template.write_text(_spec_text(), encoding="utf-8")
    _write_valid_spec(candidate)
    assert discover_specs(tmp_path) == [candidate]


def test_weekly_intake_resumes_interrupted_proposed_transition(tmp_path: Path) -> None:
    spec = tmp_path / "candidate.md"
    _write_valid_spec(spec)
    validation = validate_spec(spec)
    hypothesis = tmp_path / "hypothesis.jsonl"
    family = tmp_path / "family.jsonl"
    append_hypothesis_event(
        {
            "id": "candidate-a",
            "spec_hash": validation["metadata"]["Spec Hash"],
            "spec_path": str(spec.resolve()),
            "family_id": "family-a",
            "origin": "research",
            "status": "proposed",
            "n_resolved": 0,
            "verdict_reason": "interrupted",
        },
        hypothesis,
    )

    report = run_intake(spec_paths=[spec], hypothesis_path=hypothesis, family_path=family)

    assert report["development_events_added"] == 1
    assert report["family_specs_added"] == 1
    assert report["results"][0]["action"] == "resumed_to_development"
