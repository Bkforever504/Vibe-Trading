from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.hypothesis_ledger import latest_hypotheses, read_jsonl
from scripts.register_mnq_smt_family import (
    CANDIDATES,
    FAMILY_ID,
    ROOT,
    register_family,
)


SPEC_PATHS = [ROOT / candidate["spec_path"] for candidate in CANDIDATES]
UNIVERSE_PATH = ROOT / "data" / "universes" / "mnq_smt_family_2026-08-24.json"


def test_registration_adds_four_frozen_specs_and_transitions_each_to_shadow(tmp_path: Path) -> None:
    hypothesis = tmp_path / "hypothesis.jsonl"
    family = tmp_path / "family.jsonl"

    report = register_family(
        spec_paths=SPEC_PATHS,
        universe_path=UNIVERSE_PATH,
        hypothesis_path=hypothesis,
        family_path=family,
    )

    assert report["valid_specs"] == 4
    assert report["proposed_events_added"] == 4
    assert report["development_events_added"] == 4
    assert report["shadow_events_added"] == 4
    assert report["family_specs_added"] == 4
    assert report["family_size"] == 4
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["orders_submitted"] == 0

    latest = latest_hypotheses(hypothesis)
    assert set(latest) == {candidate["candidate_id"] for candidate in CANDIDATES}
    assert {row["status"] for row in latest.values()} == {"shadow"}
    assert all("promotion_ineligible" in str(row["verdict_reason"]) for row in latest.values())
    assert all(row["execution_enabled"] is False for row in read_jsonl(hypothesis))
    assert all(row["can_submit_orders"] is False for row in read_jsonl(family))
    assert [row["status"] for row in read_jsonl(hypothesis)] == [
        status for _candidate in CANDIDATES for status in ("proposed", "development", "shadow")
    ]


def test_registration_is_idempotent(tmp_path: Path) -> None:
    hypothesis = tmp_path / "hypothesis.jsonl"
    family = tmp_path / "family.jsonl"
    kwargs = {
        "spec_paths": SPEC_PATHS,
        "universe_path": UNIVERSE_PATH,
        "hypothesis_path": hypothesis,
        "family_path": family,
    }
    register_family(**kwargs)
    before_hypothesis = hypothesis.read_bytes()
    before_family = family.read_bytes()

    report = register_family(**kwargs)

    assert report["proposed_events_added"] == 0
    assert report["development_events_added"] == 0
    assert report["shadow_events_added"] == 0
    assert report["family_specs_added"] == 0
    assert report["family_size"] == 4
    assert report["writes_performed"] is False
    assert hypothesis.read_bytes() == before_hypothesis
    assert family.read_bytes() == before_family


def test_dry_run_projects_registration_without_writing_ledgers(tmp_path: Path) -> None:
    hypothesis = tmp_path / "hypothesis.jsonl"
    family = tmp_path / "family.jsonl"

    report = register_family(
        spec_paths=SPEC_PATHS,
        universe_path=UNIVERSE_PATH,
        hypothesis_path=hypothesis,
        family_path=family,
        dry_run=True,
    )

    assert report["dry_run"] is True
    assert report["writes_performed"] is False
    assert report["proposed_events_added"] == 4
    assert report["shadow_events_added"] == 4
    assert report["family_size"] == 4
    assert not hypothesis.exists()
    assert not family.exists()


def test_all_specs_are_validated_before_any_ledger_write(tmp_path: Path) -> None:
    copied_specs: list[Path] = []
    for source in SPEC_PATHS:
        target = tmp_path / source.name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        copied_specs.append(target)
    copied_specs[-1].write_text(
        copied_specs[-1].read_text(encoding="utf-8").replace("Status: frozen", "Status: draft"),
        encoding="utf-8",
    )
    hypothesis = tmp_path / "hypothesis.jsonl"
    family = tmp_path / "family.jsonl"

    with pytest.raises(ValueError, match="invalid_mnq_family_specs"):
        register_family(
            spec_paths=copied_specs,
            universe_path=UNIVERSE_PATH,
            hypothesis_path=hypothesis,
            family_path=family,
        )

    assert not hypothesis.exists()
    assert not family.exists()


def test_universe_membership_hash_is_verified_before_registration(tmp_path: Path) -> None:
    universe = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    universe["symbols"] = ["ES", "MES", "MNQ"]
    universe["symbol_count"] = 3
    bad_universe = tmp_path / "universe.json"
    bad_universe.write_text(json.dumps(universe), encoding="utf-8")

    with pytest.raises(ValueError, match="universe_membership_hash_mismatch"):
        register_family(
            spec_paths=SPEC_PATHS,
            universe_path=bad_universe,
            hypothesis_path=tmp_path / "hypothesis.jsonl",
            family_path=tmp_path / "family.jsonl",
        )


def test_family_is_fail_closed_if_an_unexpected_candidate_already_occupies_it(tmp_path: Path) -> None:
    family = tmp_path / "family.jsonl"
    family.write_text(
        json.dumps(
            {
                "candidate_id": "unexpected",
                "family_id": FAMILY_ID,
                "spec_hash": "sha256:" + "f" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unexpected_candidate_in_family"):
        register_family(
            spec_paths=SPEC_PATHS,
            universe_path=UNIVERSE_PATH,
            hypothesis_path=tmp_path / "hypothesis.jsonl",
            family_path=family,
        )
