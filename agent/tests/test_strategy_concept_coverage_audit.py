import json

from scripts import strategy_concept_coverage_audit as audit


def test_registry_covers_every_taxonomy_pattern() -> None:
    report = audit.build_audit()
    assert report["registry_complete"] is True
    assert report["missing_registry_ids"] == []
    assert report["orphaned_registry_ids"] == []


def test_implementation_does_not_count_as_tested() -> None:
    report = audit.build_audit()
    by_id = {row["id"]: row for row in report["patterns"]}
    assert by_id["inverse_head_shoulders"]["implementation_status"].startswith("live_")
    assert by_id["inverse_head_shoulders"]["evidence_status"] == "implementation_only"
    assert by_id["inverse_head_shoulders"]["isolated_tested"] is False


def test_completed_tournament_advances_evidence_without_claiming_edge() -> None:
    report = audit.build_audit()
    by_id = {row["id"]: row for row in report["patterns"]}
    assert by_id["cbc_strong_flip"]["isolated_tested"] is True
    assert "uncovered_concept_tournament.json" in by_id["cbc_strong_flip"]["evidence"][0]


def test_proxy_does_not_count_as_named_concept_validation() -> None:
    report = audit.build_audit()
    by_id = {row["id"]: row for row in report["patterns"]}
    assert by_id["fvg_retest"]["evidence_status"] == "partial_proxy_only"
    assert by_id["fvg_retest"]["isolated_tested"] is False


def test_output_is_json_serializable_and_has_no_rank_authority() -> None:
    report = audit.build_audit()
    json.dumps(report)
    assert report["execution_enabled"] is False
    assert report["rank_effect"] == "none"
    assert report["data_ready_untested_count"] > 0
