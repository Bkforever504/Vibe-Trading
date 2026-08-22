from __future__ import annotations

import json

from scripts.promote_validated_patterns import promote


def _taxonomy() -> dict:
    return {
        "schema_version": 2,
        "patterns": [{"id": "ict_cisd_universal_model", "governance_status": "unvalidated_pattern_hypothesis"}],
    }


def _status(eligible: bool = True) -> dict:
    return {
        "pattern_id": "ict_cisd_universal_model",
        "eligible_for_validated_promotion": eligible,
        "n_outcomes": 100,
        "n_unique_dates": 30,
        "wilson_lower_bound_95": 0.551,
        "brier_skill": 0.1,
    }


def test_promoter_updates_taxonomy_and_appends_one_audit_row(tmp_path) -> None:
    taxonomy = tmp_path / "taxonomy.json"
    status = tmp_path / "status.json"
    ledger = tmp_path / "promotions.jsonl"
    taxonomy.write_text(json.dumps(_taxonomy()), encoding="utf-8")
    status.write_text(json.dumps(_status()), encoding="utf-8")

    result = promote(status_path=status, taxonomy_path=taxonomy, ledger_path=ledger, now_utc="2026-08-22T22:00:00Z")

    assert result["status"] == "promoted"
    assert json.loads(taxonomy.read_text(encoding="utf-8"))["patterns"][0]["governance_status"] == "validated_pattern"
    audit = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert audit["prior_status"] == "unvalidated_pattern_hypothesis"
    assert audit["new_status"] == "validated_pattern"
    assert audit["execution_enabled"] is False
    assert audit["can_submit_orders"] is False


def test_promoter_is_idempotent_and_fails_closed_on_pending_gate(tmp_path) -> None:
    taxonomy = tmp_path / "taxonomy.json"
    status = tmp_path / "status.json"
    ledger = tmp_path / "promotions.jsonl"
    taxonomy.write_text(json.dumps(_taxonomy()), encoding="utf-8")
    status.write_text(json.dumps(_status(False)), encoding="utf-8")
    assert promote(status_path=status, taxonomy_path=taxonomy, ledger_path=ledger)["status"] == "gate_not_eligible"
    assert not ledger.exists()

    status.write_text(json.dumps(_status(True)), encoding="utf-8")
    assert promote(status_path=status, taxonomy_path=taxonomy, ledger_path=ledger)["status"] == "promoted"
    assert promote(status_path=status, taxonomy_path=taxonomy, ledger_path=ledger)["status"] == "already_validated"
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1
