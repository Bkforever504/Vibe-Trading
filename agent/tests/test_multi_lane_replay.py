from __future__ import annotations

from datetime import datetime, timedelta, timezone

from research.multi_lane_replay import evaluate_replay


def qualified(row: dict) -> dict:
    candidate_id = str(row["candidate_id"])
    session = str(row["session"])
    return {
        **row,
        "plan_id": row.get("plan_id", f"{candidate_id}:{session}"),
        "strategy_id": row.get("strategy_id", candidate_id),
        "session_date": session,
        "promotion_eligible": True,
        "data_source": "databento_glbx_mdp3_mbo",
        "terminal_data_source": "databento_glbx_mdp3_mbo",
        "source_agreement": True,
        "evidence_tier": "databento_mbo_executable",
        "terminal_evidence_tier": "databento_mbo_executable",
        "evidence_blockers": [],
        "entry_fill_executable": 100.0,
        "exit_fill_executable": 101.0,
    }


def test_multi_lane_replay_is_deterministic_and_reports_every_gate() -> None:
    start = datetime(2026, 1, 2, tzinfo=timezone.utc)
    rows = []
    for index in range(60):
        session = (start + timedelta(days=index)).date().isoformat()
        signal = 1 if index % 2 == 0 else -1
        forward = signal * (0.35 + (index % 5) * 0.01)
        rows.append(qualified({"candidate_id": "lane-a", "session": session, "signal": signal, "forward_return_r": forward, "outcome_r": signal * forward, "doubled_cost_outcome_r": signal * forward - 0.05}))
        rows.append(qualified({"candidate_id": "lane-b", "session": session, "signal": signal, "forward_return_r": -forward, "outcome_r": -signal * forward, "doubled_cost_outcome_r": -signal * forward - 0.05}))
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)

    first = evaluate_replay(rows, family_size=2, now=now)
    second = evaluate_replay(rows, family_size=2, now=now)

    assert first == second
    lane = first["results"][0]
    assert lane["n_resolved"] == 60
    assert lane["distinct_sessions"] == 60
    assert lane["expectancy_lower_95_ci"] > 0
    assert lane["placebo"]["status"] == "pass"
    assert lane["cost_stress"]["status"] == "pass"
    assert lane["pbo"] is not None
    assert lane["execution_enabled"] is False
    assert lane["can_submit_orders"] is False


def test_missing_placebo_inputs_never_pass() -> None:
    report = evaluate_replay(
        [qualified({"candidate_id": "lane-a", "session": f"2026-01-{day:02d}", "outcome_r": 0.2}) for day in range(1, 11)],
        family_size=1,
        now=datetime(2026, 8, 22, tzinfo=timezone.utc),
    )
    assert report["results"][0]["placebo"]["status"] == "unavailable"
    assert report["results"][0]["pbo_status"] == "unavailable_single_lane"


def test_replay_excludes_proxy_and_missing_eligibility_with_reason_counts() -> None:
    report = evaluate_replay(
        [
            {
                "plan_id": "proxy-1",
                "strategy_id": "lane-a",
                "session_date": "2026-01-01",
                "outcome_r": 1.0,
                "promotion_eligible": False,
                "data_source": "yfinance_proxy_MES=F",
                "terminal_data_source": "yfinance_proxy_MES=F",
                "source_agreement": True,
                "evidence_tier": "proxy_ohlcv_non_executable",
                "terminal_evidence_tier": "proxy_ohlcv_non_executable",
                "entry_fill_executable": None,
                "exit_fill_executable": None,
            },
            {
                "plan_id": "missing-flag",
                "strategy_id": "lane-a",
                "session_date": "2026-01-02",
                "outcome_r": 1.0,
                "data_source": "databento_glbx_mdp3_mbo",
                "terminal_data_source": "databento_glbx_mdp3_mbo",
                "source_agreement": True,
                "evidence_tier": "databento_mbo_executable",
                "terminal_evidence_tier": "databento_mbo_executable",
                "entry_fill_executable": 100.0,
                "exit_fill_executable": 101.0,
            },
        ],
        family_size=1,
    )

    assert report["results"] == []
    assert report["excluded_rows"] == 2
    assert report["exclusion_reasons"]["promotion_eligible_false"] == 1
    assert report["exclusion_reasons"]["promotion_eligible_missing"] == 1
    assert report["exclusion_reasons"]["data_source_not_whitelisted"] == 1


def test_replay_dedupes_by_plan_prefers_latest_qualified_regrade_and_stable_strategy() -> None:
    old = qualified(
        {
            "candidate_id": "daily-plan-id",
            "strategy_id": "mes-orb-0932-vix-v2",
            "plan_id": "mes-orb-0932-vix-v2:2026-08-24",
            "session": "2026-08-24",
            "outcome_r": -1.0,
            "outcome_version": 1,
            "resolved_at": "2026-08-24T16:00:00Z",
        }
    )
    regraded = {
        **old,
        "outcome_r": 0.5,
        "outcome_version": 2,
        "regraded_at": "2026-08-25T12:00:00Z",
    }
    unqualified_later = {
        **regraded,
        "outcome_r": 9.0,
        "outcome_version": 3,
        "promotion_eligible": False,
    }

    report = evaluate_replay([old, unqualified_later, regraded], family_size=1)

    assert report["duplicate_rows"] == 2
    assert report["excluded_rows"] == 0
    assert len(report["results"]) == 1
    assert report["results"][0]["candidate_id"] == "mes-orb-0932-vix-v2"
    assert report["results"][0]["n_resolved"] == 1
    assert report["results"][0]["expectancy"] == 0.5


def test_replay_emits_v2_regime_latency_integrity_and_universe_evidence() -> None:
    row = qualified({
        "candidate_id": "mes-orb-0932-vix-v2",
        "session": "2026-08-24",
        "outcome_r": 0.5,
        "doubled_cost_outcome_r": 0.4,
        "signal": 1,
        "forward_return_r": 0.6,
        "preregistration_schema": "hypothesis-v2",
        "regime_tags": ["trend", "low_vol"],
        "alert_latency_fraction": 0.1,
        "universe": {
            "version": "cme-mes-front-month-roll8-v1",
            "hash": "sha256:" + "a" * 64,
            "membership_as_of": "2026-08-22",
            "drift_status": "unchanged",
        },
    })

    result = evaluate_replay([row], family_size=1)["results"][0]

    assert result["preregistration_schema"] == "hypothesis-v2"
    assert result["regime_coverage"]["trend"]["independent_dates"] == 1
    assert result["regime_coverage"]["chop"]["independent_dates"] == 0
    assert result["latency"]["observations"] == 1
    assert result["latency"]["p90_fraction_of_expected_window"] == 0.1
    assert result["data_integrity"]["contaminated_outcomes_remaining"] == 0
    assert result["universe"]["drift_status"] == "unchanged"
    assert result["revalidation"]["latest_brier_skill"] is None
