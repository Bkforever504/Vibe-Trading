from __future__ import annotations

import json
from pathlib import Path

from scripts.preregistration_validator import compute_spec_hash_text, discover_specs, validate_spec
from scripts.hypothesis_ledger import append_hypothesis_event
from scripts.weekly_candidate_intake import run_intake


def _spec_text(spec_hash: str = "sha256:<SPEC_HASH>", *, schema: str = "hypothesis-v2") -> str:
    return f"""# Trading Hypothesis Preregistration

Preregistration Schema: {schema}
Spec ID: candidate-a
Family ID: family-a
Origin: research
Status: frozen
Spec Hash: {spec_hash}
Universe ID: us-liquid
Universe Version: us-liquid-v1
Universe Hash: sha256:{"a" * 64}
Membership As Of: 2026-08-01

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

## Experiment Family & Multiple Testing
Use family-a and Benjamini-Hochberg at alpha 0.05 across every challenger.

## Regime Coverage
Require eight independent dates in trend, chop, high-vol, and low-vol regimes.

## Latency Budget
Require p90 alert latency below 20% of the expected setup move window.

## Blocker EV Review
Judge blocker removal on net expected value with loss severity, never raw counts.

## Data Repair & Backfill
Any source repair requires a complete backfill and re-grade before promotion.

## Decay & Revalidation
Revalidate rolling Brier skill every 30 days and demote stale challengers.

## Universe Version
Freeze universe ID, hash, membership date, and record every membership change.
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


def test_validator_accepts_legacy_v1_but_requires_v2_governance_sections_for_v2(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.md"
    legacy_text = _spec_text(schema="hypothesis-v1")
    for heading in (
        "Experiment Family & Multiple Testing",
        "Regime Coverage",
        "Latency Budget",
        "Blocker EV Review",
        "Data Repair & Backfill",
        "Decay & Revalidation",
        "Universe Version",
    ):
        legacy_text = legacy_text.split(f"\n## {heading}\n", 1)[0] if heading == "Experiment Family & Multiple Testing" else legacy_text
    legacy.write_text(_spec_text(compute_spec_hash_text(legacy_text), schema="hypothesis-v1").split("\n## Experiment Family & Multiple Testing\n", 1)[0] + "\n", encoding="utf-8")
    # Re-hash after removing v2-only sections.
    raw = legacy.read_text(encoding="utf-8")
    legacy.write_text(raw.replace(raw.split("Spec Hash: ", 1)[1].splitlines()[0], compute_spec_hash_text(raw)), encoding="utf-8")
    assert validate_spec(legacy)["valid"] is True

    incomplete_v2 = tmp_path / "incomplete-v2.md"
    raw_v2 = _spec_text().split("\n## Experiment Family & Multiple Testing\n", 1)[0] + "\n"
    incomplete_v2.write_text(raw_v2.replace("sha256:<SPEC_HASH>", compute_spec_hash_text(raw_v2)), encoding="utf-8")
    errors = validate_spec(incomplete_v2)["errors"]
    assert "missing_or_empty_section:Regime Coverage" in errors
    assert "missing_or_empty_section:Universe Version" in errors


def test_v2_requires_structured_universe_identity(tmp_path: Path) -> None:
    path = tmp_path / "candidate.md"
    raw = _spec_text().replace("Universe Version: us-liquid-v1\n", "")
    path.write_text(raw.replace("sha256:<SPEC_HASH>", compute_spec_hash_text(raw)), encoding="utf-8")
    assert "missing_metadata:Universe Version" in validate_spec(path)["errors"]


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
                "universe_id": validation["metadata"]["Universe ID"],
                "universe_version": validation["metadata"]["Universe Version"],
                "universe_hash": validation["metadata"]["Universe Hash"],
                "membership_as_of": validation["metadata"]["Membership As Of"],
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
