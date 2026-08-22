from __future__ import annotations

from research import options_exit_policy_lab as exit_lab
from research import paired_direction_decision_lab as lab


def _life(
    day: str,
    right: str,
    bucket: str,
    outcome: float,
    features: dict | None = None,
    *,
    pair_id: str = "",
    entry_at: str | None = None,
) -> exit_lab.Lifecycle:
    bid = 1.0 + outcome / 100.0
    return exit_lab.Lifecycle(
        lifecycle_id=f"{day}|SPY|{bucket}|{right}",
        date=day,
        symbol="SPY",
        right=right,
        strategy="0dte",
        day_type="trend",
        entry_premium=1.0,
        marks=(
            exit_lab.Mark(
                ts=f"{day}T10:00:00",
                bid=bid,
                mark=bid,
                ret_pct=outcome,
                best_pct=outcome,
                reason="hard_close",
                ask=1.02,
            ),
        ),
        entry_at=entry_at or f"{day}T09:30:00Z",
        features=features or {},
        episode_bucket_et=bucket,
        decision_pair_id=pair_id,
        decision_lattice_role="source_direction" if right == "CALL" else "opposite_direction",
        entry_quote_timestamp=f"{day}T09:29:59Z" if pair_id else "",
        entry_quote_age_seconds=1.0 if pair_id else None,
        pair_construction_method="symmetric_log_moneyness_single_snapshot" if pair_id else "",
        pair_sync_status="synchronized_forward" if pair_id else "",
    )


def test_build_pairs_requires_same_symbol_date_and_bucket() -> None:
    lives = [
        _life("2026-01-01", "CALL", "10:00", 20),
        _life("2026-01-01", "PUT", "10:00", -10),
        _life("2026-01-01", "CALL", "10:30", 5),
    ]

    pairs = lab.build_pairs(lives)

    assert len(pairs) == 1
    assert pairs[0]["call"].right == "CALL"
    assert pairs[0]["put"].right == "PUT"
    assert pairs[0]["eligible_for_causal_review"] is False


def test_explicit_synchronized_pair_is_eligible_for_causal_review() -> None:
    lives = [
        _life("2026-01-01", "CALL", "10:00", 20, pair_id="pair-1"),
        _life("2026-01-01", "PUT", "10:00", -10, pair_id="pair-1"),
    ]

    pairs = lab.build_pairs(lives)

    assert len(pairs) == 1
    assert pairs[0]["pair_quality"] == "synchronized_forward"
    assert pairs[0]["eligible_for_causal_review"] is True
    assert pairs[0]["entry_time_skew_seconds"] == 0.0


def test_legacy_bucket_pair_exposes_entry_time_skew() -> None:
    lives = [
        _life("2026-01-01", "CALL", "10:00", 20, entry_at="2026-01-01T10:01:00Z"),
        _life("2026-01-01", "PUT", "10:00", -10, entry_at="2026-01-01T10:11:00Z"),
    ]

    pair = lab.build_pairs(lives)[0]

    assert pair["pair_quality"] == "legacy_bucket_approximate"
    assert pair["entry_time_skew_seconds"] == 600.0
    assert pair["eligible_for_causal_review"] is False


def test_market_force_rule_can_choose_call_put_or_abstain() -> None:
    rule = lab.RULES["market_force"]
    assert rule({"market_force_classification": "bullish_lean"}) == "CALL"
    assert rule({"market_force_classification": "bearish_lean"}) == "PUT"
    assert rule({"market_force_classification": "mixed"}) == "NONE"


def test_opportunity_surface_separates_direction_and_no_edge(monkeypatch) -> None:
    monkeypatch.setitem(
        lab.exit_lab.POLICIES,
        "baseline_current",
        lambda life: (life.marks[-1].ret_pct or 0.0, "test"),
    )
    pairs = []
    for index, (call_result, put_result) in enumerate(((20, -10), (-5, 15), (10, 5), (-5, -10))):
        pairs.extend(lab.build_pairs([
            _life("2026-01-01", "CALL", f"10:{index:02d}", call_result),
            _life("2026-01-01", "PUT", f"10:{index:02d}", put_result),
        ]))

    surface = lab.opportunity_surface(pairs, fee_pct=0.0)

    assert surface["category_counts"] == {
        "call_only_profitable": 1,
        "put_only_profitable": 1,
        "both_profitable": 1,
        "neither_profitable": 1,
    }
    assert surface["tradable_move_available_rate"] == 0.75
    assert surface["execution_authority"].startswith("none_")


def test_rule_report_counts_abstention_as_zero_and_blocks_clustered_edge(monkeypatch) -> None:
    pairs = []
    for index in range(10):
        features = {"market_force_classification": "bullish_lean" if index < 2 else "mixed"}
        call = _life("2026-01-01", "CALL", f"10:{index:02d}", 20, features)
        put = _life("2026-01-01", "PUT", f"10:{index:02d}", -20, features)
        pairs.extend(lab.build_pairs([call, put]))
    monkeypatch.setitem(
        lab.exit_lab.POLICIES,
        "baseline_current",
        lambda life: (life.marks[-1].ret_pct or 0.0, "test"),
    )

    report = lab.evaluate_rule("market_force", lab.RULES["market_force"], pairs, fee_pct=0.0)

    assert report["triggered_trades"] == 2
    assert report["per_signal_metrics"]["gross_pct"] == 40.0
    assert report["action_counts"] == {"CALL": 2, "NONE": 8}
    assert "positive_returns_too_concentrated_by_date" in report["review_gate"]["failed_checks"]


def test_report_has_no_execution_authority(tmp_path) -> None:
    report = lab.build_report(tmp_path / "missing.jsonl")
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["automatic_parameter_changes"] is False
    assert report["promotion_authority"].startswith("none_")


def test_walk_forward_selector_uses_prior_dates_only(monkeypatch) -> None:
    monkeypatch.setattr(lab, "SELECTOR_MIN_TRAIN_DATES", 2)
    monkeypatch.setattr(lab, "SELECTOR_MIN_NEIGHBOR_DATES", 2)
    monkeypatch.setattr(lab, "SELECTOR_MIN_NEIGHBORS", 2)
    monkeypatch.setattr(lab, "SELECTOR_MIN_SIMILARITY", 0.0)
    features = {
        "market_force_classification": "bullish_lean",
        "above_vwap": True,
        "green_session": True,
    }
    pairs = []
    for day in ("2026-01-01", "2026-01-02", "2026-01-03"):
        pairs.extend(lab.build_pairs([
            _life(day, "CALL", "10:00", 20, features, pair_id=f"pair-{day}"),
            _life(day, "PUT", "10:00", -20, features, pair_id=f"pair-{day}"),
        ]))
    monkeypatch.setitem(
        lab.exit_lab.POLICIES,
        "baseline_current",
        lambda life: (life.marks[-1].ret_pct or 0.0, "test"),
    )

    report = lab.evaluate_walk_forward_context_selector(pairs, fee_pct=0.0)

    assert [row["action"] for row in report["outcomes"]] == ["NONE", "NONE", "CALL"]
    assert report["outcomes"][2]["prior_training_dates"] == 2
    assert report["selection_is_strictly_walk_forward"] is True
