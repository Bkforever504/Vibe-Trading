from __future__ import annotations

from scripts.adversarial_strategy_audit import audit_manifest, build_report


def strong_manifest() -> dict:
    winners = [0.8, 1.0, 1.2, 0.7, 1.4, 0.9] * 10
    return {
        "subject_id": "SPY",
        "strategy_version": "v1",
        "builder_id": "builder",
        "reviewer_id": "independent-reviewer",
        "preregistered": True,
        "execution_delay_bars": 1,
        "operation_count": 8,
        "trials_considered": 1,
        "timestamp_audit": {"passed": True},
        "backtest_forward_parity": {"passed": True},
        "returns": {"final": winners, "forward": winners, "cost_2x": winners, "cost_3x": winners},
        "parameter_neighbors": [{"returns": winners} for _ in range(5)],
        "regimes": {name: winners for name in ("bull", "bear", "sideways")},
        "walk_forward_folds": [{"returns": winners[:12]} for _ in range(5)],
    }


def test_strong_independent_evidence_passes_human_review_only() -> None:
    result = audit_manifest(strong_manifest())
    assert result["passed"] is True
    assert result["promotion_authority"] == "human_review_only"
    assert result["can_submit_orders"] is False


def test_lookahead_and_self_review_fail_closed() -> None:
    manifest = strong_manifest()
    manifest["reviewer_id"] = manifest["builder_id"]
    manifest["execution_delay_bars"] = 0
    manifest["timestamp_audit"] = {"passed": False}
    result = audit_manifest(manifest)
    assert result["passed"] is False
    assert "independent_reviewer" in result["failed_checks"]
    assert "execution_delay_positive" in result["failed_checks"]
    assert "point_in_time_timestamp_audit" in result["failed_checks"]


def test_outlier_dependent_edge_fails() -> None:
    manifest = strong_manifest()
    fragile = [-0.1] * 59 + [10.0]
    manifest["returns"]["final"] = fragile
    result = audit_manifest(manifest)
    assert "top_one_pct_not_decisive" in result["failed_checks"]


def test_missing_manifests_block_promotion(tmp_path) -> None:
    report = build_report(tmp_path)
    assert report["summary"]["subject_count"] == 0
    assert report["promotion_blockers"] == ["no_adversarial_manifests"]
