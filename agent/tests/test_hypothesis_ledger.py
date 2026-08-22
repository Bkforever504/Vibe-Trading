from __future__ import annotations

from pathlib import Path

import pytest

from scripts.hypothesis_ledger import (
    append_hypothesis_event,
    experiment_family_size,
    latest_hypotheses,
    read_jsonl,
    record_frozen_spec,
)


HASH = "sha256:" + "a" * 64


def _candidate(status: str) -> dict:
    return {
        "id": "candidate-a",
        "spec_hash": HASH,
        "spec_path": "research/candidate-a.md",
        "family_id": "family-a",
        "origin": "research",
        "status": status,
        "n_resolved": 0,
        "verdict_reason": "test",
    }


def test_hypothesis_events_are_append_only_and_latest_state_is_derived(tmp_path: Path) -> None:
    path = tmp_path / "hypotheses.jsonl"
    assert append_hypothesis_event(_candidate("proposed"), path)["recorded"] is True
    assert append_hypothesis_event(_candidate("development"), path)["recorded"] is True
    rows = read_jsonl(path)
    assert [row["status"] for row in rows] == ["proposed", "development"]
    assert latest_hypotheses(path)["candidate-a"]["status"] == "development"
    assert all(row["execution_enabled"] is False for row in rows)
    assert all(row["can_submit_orders"] is False for row in rows)


def test_hypothesis_identity_is_immutable_and_transitions_are_guarded(tmp_path: Path) -> None:
    path = tmp_path / "hypotheses.jsonl"
    append_hypothesis_event(_candidate("proposed"), path)
    changed = _candidate("development")
    changed["spec_hash"] = "sha256:" + "b" * 64
    with pytest.raises(ValueError, match="immutable_candidate_fields_changed"):
        append_hypothesis_event(changed, path)
    with pytest.raises(ValueError, match="invalid_status_transition"):
        append_hypothesis_event(_candidate("approved"), path)


def test_family_ledger_counts_each_frozen_hash_once_and_never_decrements(tmp_path: Path) -> None:
    path = tmp_path / "families.jsonl"
    kwargs = {
        "candidate_id": "candidate-a",
        "family_id": "family-a",
        "spec_hash": HASH,
        "spec_path": "research/candidate-a.md",
        "origin": "research",
        "path": path,
    }
    assert record_frozen_spec(**kwargs)["recorded"] is True
    assert record_frozen_spec(**kwargs)["recorded"] is False
    assert experiment_family_size(path) == 1
    assert experiment_family_size(path, "family-a") == 1
    assert len(read_jsonl(path)) == 1
