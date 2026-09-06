from __future__ import annotations

from scripts.social_evidence_coverage_audit import audit_claims


def test_audit_links_only_to_prior_snapshot_and_never_assumes_fill() -> None:
    claims = [{
        "claim_id": "tsla-claim",
        "symbol": "TSLA",
        "direction": "call",
        "claimed_entry_at": "2026-08-31T09:55:00-04:00",
        "timestamp_basis": "explicit_entry_time",
    }]
    snapshots = [{
        "as_of_et": "2026-08-31T09:50:00-04:00",
        "all_discovered_symbols": ["TSLA"],
        "coverage_trace": [{"symbol": "TSLA", "selected_for_intraday_bars": True, "stop_stage": "evaluated"}],
        "ranked_candidates": [{
            "symbol": "TSLA", "direction": "bullish", "grade": "B+", "state": "watch",
            "setup": "opening_range_breakout", "confirmation_stage": "completed_5m_confirmed", "blockers": [],
        }],
    }]

    report = audit_claims(claims, snapshots)
    row = report["claims"][0]

    assert row["status"] == "audited_nearest_prior_snapshot"
    assert row["radar_snapshot_at"] == "2026-08-31T13:50:00+00:00"
    assert row["discovered"] is True
    assert row["selected_for_intraday_bars"] is True
    assert row["setup_confirmed"] is True
    assert row["direction_aligned"] is True
    assert row["fill_assumed"] is False
    assert row["outcome_verified"] is False


def test_audit_rejects_share_time_without_timezone_or_symbol() -> None:
    report = audit_claims([{"claim_id": "bad", "symbol": "", "observed_at": "2026-08-31 09:55"}], [])

    assert report["claims"][0]["status"] == "unusable_claim_missing_symbol_or_timezone_aware_timestamp"
