from __future__ import annotations

from scripts.move_universe_ground_truth import ground_truth_spec_status, load_ground_truth


def test_placeholder_is_empty_and_fail_closed_before_kenny_approval(tmp_path) -> None:
    missing_spec = tmp_path / "MOVE_GROUND_TRUTH_SPEC_2026-08-20.md"
    report = load_ground_truth(
        {"date": "2026-08-21", "market_movers": [{"symbol": "WIN", "percent_change": 9, "price": 20}]},
        liquidity_by_symbol={"WIN": 100_000_000},
        spec_path=missing_spec,
    )

    assert report["ground_truth_status"] == "pending_kenny_signoff"
    assert report["metrics_qualified"] is False
    assert report["moves"] == []
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_approved_spec_keeps_legacy_radar_proxy_unqualified_until_spec_builder_exists(tmp_path) -> None:
    spec = tmp_path / "MOVE_GROUND_TRUTH_SPEC_2026-08-20.md"
    spec.write_text("# MOVE denominator\nStatus: frozen\nKenny Approval: approved\n", encoding="utf-8")
    report = load_ground_truth(
        {"date": "2026-08-21", "market_movers": [{"symbol": "WIN", "percent_change": 9, "price": 20}]},
        liquidity_by_symbol={"WIN": 100_000_000},
        spec_path=spec,
    )

    assert report["ground_truth_status"] == "approved_frozen_legacy_proxy_unqualified"
    assert report["metrics_qualified"] is False
    assert [row["symbol"] for row in report["moves"]] == ["WIN"]
    assert report["spec"]["approved"] is True


def test_markdown_bold_approval_markers_are_recognized(tmp_path) -> None:
    spec = tmp_path / "MOVE_GROUND_TRUTH_SPEC_2026-08-20.md"
    spec.write_text("# MOVE denominator\n**Status:** frozen\n**Kenny Approval:** approved\n", encoding="utf-8")

    status = ground_truth_spec_status(spec)

    assert status["approved"] is True
    assert status["status"] == "approved_frozen"
