from __future__ import annotations

from datetime import datetime, timezone

from scripts.mes_v2_evidence_status import build_status


NOW = datetime(2026, 8, 23, 20, 0, tzinfo=timezone.utc)


def test_status_counts_only_explicit_qualified_regrade_and_deduplicates_plan() -> None:
    rows = [
        {
            "plan_id": "mes-orb-0932-vix-v2:2026-08-17",
            "candidate_id": "mes-orb-0932-vix-v2",
            "session_date": "2026-08-17",
            "promotion_eligible": False,
            "resolved_at": "2026-08-17T16:00:00Z",
        },
        {
            "plan_id": "mes-orb-0932-vix-v2:2026-08-17",
            "candidate_id": "mes-orb-0932-vix-v2",
            "session_date": "2026-08-17",
            "promotion_eligible": True,
            "evidence_tier": "databento_mbo_executable_quote_observed",
            "regime_tags": ["trend", "low_vol"],
            "alert_latency_fraction": 0.1,
            "resolved_at": "2026-08-19T16:00:00Z",
        },
    ]

    report = build_status(
        rows,
        capability={"live_status": "unavailable", "live_reason": "license_required"},
        now=NOW,
    )

    orb = report["candidates"][0]
    assert orb["qualified_outcomes"] == 1
    assert orb["excluded_outcomes"] == 0
    assert orb["distinct_dates"] == 1
    assert orb["regime_dates"]["trend"] == 1
    assert orb["regime_dates"]["low_vol"] == 1
    assert orb["latency"]["p90_fraction_of_expected_window"] == 0.1
    assert "databento_live_license_unavailable_historical_regrade_only" in orb["blockers"]
    assert report["execution_enabled"] is False


def test_status_does_not_infer_eligibility_from_missing_flag() -> None:
    report = build_status(
        [
            {
                "plan_id": "mes-reopen-drift-v2:2026-08-17",
                "strategy_id": "mes-reopen-drift-v2",
                "session_date": "2026-08-17",
            }
        ],
        now=NOW,
    )

    reopen = report["candidates"][1]
    assert reopen["qualified_outcomes"] == 0
    assert reopen["excluded_outcomes"] == 1
    assert "no_promotion_qualified_databento_mbo_outcomes" in reopen["blockers"]
