import json
from pathlib import Path

import pytest

from scripts.external_strategy_evidence import (
    DEFAULT_REGISTRY,
    build_report,
    evidence_score,
    load_registry,
)


def test_registry_rejects_social_claims_and_never_grants_execution():
    report = build_report(load_registry())
    social = next(row for row in report["sources"] if row["source_id"] == "social_trader_screenshots")

    assert social["classification"] == "rejected_as_edge_evidence"
    assert report["automatic_promotion"] is False
    assert report["promotion_authority"] == "blocked"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_exact_high_quality_public_rules_can_only_enter_shadow_replay():
    report = build_report(load_registry())
    trend = next(row for row in report["sources"] if row["source_id"] == "aqr_century_trend_following")

    assert trend["classification"] == "shadow_replication_eligible"
    assert trend["missing_artifacts"] == []
    assert "aqr_century_trend_following" in report["shadow_replication_eligible"]


def test_proxy_methodology_cannot_be_mislabeled_as_exact_replication():
    report = build_report(load_registry())
    quality = next(row for row in report["sources"] if row["source_id"] == "alpha_architect_quality_momentum")

    assert quality["replication_scope"] == "proxy"
    assert quality["classification"] == "hypothesis_only"


def test_missing_artifact_blocks_exact_hypothesis(tmp_path: Path):
    registry = {
        "schema_version": 1,
        "as_of": "2026-08-17",
        "sources": [{
            "source_id": "missing",
            "name": "Missing implementation",
            "source_kind": "paper",
            "role": "research_hypothesis",
            "replication_scope": "exact",
            "evidence": {
                "rules_exact": True,
                **{field: 1.0 for field in (
                    "rule_completeness",
                    "independent_verification",
                    "transaction_cost_realism",
                    "holdout_quality",
                    "point_in_time_data",
                    "license_clarity",
                    "complete_loss_history",
                )},
            },
            "bot_mappings": [{"artifact": "research/not_here.py"}],
        }],
    }

    report = build_report(registry, root=tmp_path)

    assert report["sources"][0]["classification"] == "hypothesis_only"
    assert report["sources"][0]["missing_artifacts"] == ["research/not_here.py"]


def test_registry_is_json_and_evidence_values_are_bounded():
    payload = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    for source in payload["sources"]:
        score = evidence_score(source["evidence"])
        assert 0.0 <= score <= 10.0


def test_invalid_evidence_value_is_rejected():
    with pytest.raises(ValueError, match="between 0 and 1"):
        evidence_score({"rule_completeness": 1.1})
