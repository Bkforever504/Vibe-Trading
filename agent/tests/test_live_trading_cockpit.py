from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.live_trading_cockpit import _apply_grade_calibration, _plan_id, build_cockpit, load_source


NOW = datetime(2026, 8, 19, 15, 0, tzinfo=timezone.utc)


def test_plan_id_is_stable_across_display_time_and_distinguishes_trigger_events() -> None:
    base = {
        "symbol": "SPY",
        "asset_class": "equity",
        "source": "live_opportunities",
        "setup": "range_break_retest",
        "direction": "bullish",
        "entry": 650,
        "stop": 648,
        "target": 654,
        "generated_at": "2026-08-19T15:00:00Z",
        "evidence": {"candidate_id": "spy-one"},
    }

    assert _plan_id(base) == _plan_id(dict(base))
    assert _plan_id(base) != _plan_id({**base, "generated_at": "2026-08-19T16:00:00Z"})


def test_grade_calibration_attaches_only_forward_qualified_probability() -> None:
    row = {"setup": "break_retest", "grade": "A", "actionability": "shadow_ready", "blockers": []}
    calibration = {
        "provider": "grade_probability_service",
        "generated_at": "2026-08-19T13:00:00Z",
        "method": "expanding_date_window_isotonic_with_moving_block_bootstrap",
        "buckets": [{
            "bucket_id": "break_retest|trend|A",
            "setup_family": "break_retest",
            "regime": "trend",
            "grade": "A",
            "probability": {
                "value": 0.68,
                "lower_bound": 0.57,
                "sample_size": 120,
                "independent_dates": 45,
                "status": "local_forward_validated",
                "brier_skill_vs_expanding_base_rate": 0.08,
            },
        }],
    }

    attached = _apply_grade_calibration(row, calibration, regime="trend")

    assert attached["probability"]["value"] == 68.0
    assert attached["probability"]["ranking_eligible"] is True
    assert attached["probability_source"]["can_submit_orders"] is False


def test_display_calibration_cannot_rank_candidate() -> None:
    row = {"setup": "break_retest", "grade": "B", "actionability": "shadow_ready", "blockers": []}
    calibration = {"buckets": [{
        "setup_family": "break_retest",
        "regime": "all",
        "grade": "B",
        "probability": {
            "value": 0.61,
            "lower_bound": 0.48,
            "sample_size": 45,
            "independent_dates": 20,
            "status": "display_calibrated",
            "brier_skill_vs_expanding_base_rate": 0.03,
        },
    }]}

    attached = _apply_grade_calibration(row, calibration, regime="range")

    assert attached["probability"]["ranking_eligible"] is False
    assert "status_not_forward_calibrated" in attached["probability"]["qualification_failures"]


def write_report(report_dir: Path, filename: str, payload: dict) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


def test_cockpit_promotes_only_clear_paper_consumable_signal(tmp_path: Path) -> None:
    write_report(
        tmp_path,
        "trade-signal-generator.json",
        {
            "generated_at": "2026-08-19T14:59:30Z",
            "signals": [
                {
                    "symbol": "SPY",
                    "setup": "break_retest",
                    "direction": "bullish",
                    "paper_consumable": True,
                    "blockers": [],
                    "entry": 600.0,
                    "stop": 598.0,
                    "reward_risk": 2.0,
                    "targets": [{"price": 604.0}],
                },
                {
                    "symbol": "QQQ",
                    "setup": "opening_drive",
                    "paper_consumable": True,
                    "blockers": ["quote_stale"],
                },
            ],
        },
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)

    assert cockpit["headline"]["best_setup"]["symbol"] == "SPY"
    assert cockpit["authority"]["paper_signal_count"] == 1
    assert cockpit["authority"]["can_submit_orders"] is False
    qqq = next(row for row in cockpit["candidates"] if row["symbol"] == "QQQ")
    assert qqq["paper_consumable"] is False
    assert qqq["blockers"] == ["quote_stale"]


def test_cockpit_keeps_watchlists_distinct_from_entries(tmp_path: Path) -> None:
    write_report(
        tmp_path,
        "daily-stock-screener.json",
        {
            "generated_at": "2026-08-19T14:55:00Z",
            "rankings": [
                {
                    "symbol": "NVDA",
                    "status": "qualified_long",
                    "direction": "long",
                    "long_eligible": True,
                    "blockers": [],
                    "score": 95,
                }
            ],
        },
    )
    write_report(
        tmp_path,
        "bottom-reversal-investigator.json",
        {
            "generated_at": "2026-08-19T14:55:00Z",
            "candidates": [
                {
                    "symbol": "META",
                    "stage": "capitulation_watch",
                    "paper_consumable": False,
                    "blockers": ["demand_confirmation_not_complete"],
                    "next_session_plan": {"status": "not_armed"},
                }
            ],
        },
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)

    assert cockpit["headline"]["best_setup"] is None
    assert cockpit["headline"]["state"] == "no_eligible_setup"
    nvda = next(row for row in cockpit["candidates"] if row["symbol"] == "NVDA")
    assert nvda["lane"] == "qualified_scan"
    assert nvda["paper_consumable"] is False
    assert "strategy_trigger_not_present" in nvda["blockers"]


def test_source_inventory_reports_fresh_and_missing_inputs(tmp_path: Path) -> None:
    write_report(
        tmp_path,
        "bot-status-snapshot.json",
        {"timestamp": "2026-08-19T14:59:45Z", "provider": "bot_status_snapshot"},
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)
    sources = {row["name"]: row for row in cockpit["sources"]}

    assert sources["bot_status"]["freshness"] == "live"
    assert sources["trade_signals"]["freshness"] == "missing"
    assert cockpit["operations"]["stale_source_count"] > 0
    quarantined = {row["name"]: row for row in cockpit["operations"]["quarantined_sources"]}
    assert quarantined["trade_signals"]["reason"] == "source_missing"
    assert quarantined["trade_signals"]["source_label"] == "trade-signal-generator.json"
    assert quarantined["trade_signals"]["execution_enabled"] is False
    assert quarantined["trade_signals"]["can_submit_orders"] is False


def test_source_older_than_24_hours_is_quarantined_even_during_prior_session_band(tmp_path: Path) -> None:
    write_report(
        tmp_path,
        "bot-status-snapshot.json",
        {"timestamp": "2026-08-18T14:00:00Z", "provider": "bot_status_snapshot"},
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)
    source = next(row for row in cockpit["sources"] if row["name"] == "bot_status")
    quarantined = {row["name"]: row for row in cockpit["operations"]["quarantined_sources"]}

    assert source["freshness"] == "prior_session"
    assert quarantined["bot_status"]["reason"] == "source_older_than_24h"


def test_future_timestamp_is_clock_skewed_and_quarantined(tmp_path: Path) -> None:
    write_report(
        tmp_path,
        "bot-status-snapshot.json",
        {"timestamp": "2026-08-19T16:00:00Z", "provider": "bot_status_snapshot"},
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)
    source = next(row for row in cockpit["sources"] if row["name"] == "bot_status")
    quarantined = {row["name"]: row for row in cockpit["operations"]["quarantined_sources"]}

    assert source["freshness"] == "clock_skew"
    assert source["clock_skew_seconds"] == 3600.0
    assert quarantined["bot_status"]["reason"] == "source_timestamp_in_future"


def test_live_candidate_uses_live_source_sla_not_generic_24_hours(tmp_path: Path) -> None:
    write_report(tmp_path, "live-opportunity-engine.json", {
        "generated_at": "2026-08-19T14:30:00Z",
        "candidates": [{
            "candidate_id": "stale-live",
            "symbol": "SPY",
            "asset_class": "equity",
            "setup_family": "range_break_retest",
            "direction": "bullish",
            "decision_score": 89,
            "grade": "A",
            "state": "READY_TO_REVIEW",
            "entry": 650,
            "invalidation": 648,
            "targets": [{"price": 654}],
            "reward_risk_after_friction": 1.9,
            "blockers": [],
        }],
    })

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)
    candidate = next(row for row in cockpit["candidates"] if row["symbol"] == "SPY")

    assert candidate["actionability"] == "research_only"
    assert "source_exceeds_live_sla" in candidate["blockers"]
    assert candidate["probability"]["ranking_eligible"] is False


def test_cockpit_surfaces_streaming_opportunities_with_feed_provenance(tmp_path: Path) -> None:
    write_report(
        tmp_path,
        "live-opportunity-engine.json",
        {
            "generated_at": "2026-08-19T14:59:58Z",
            "mode": "read_only_streaming_research",
            "decision_state": "READY_TO_REVIEW",
            "feed": {
                "provider": "alpaca",
                "feed": "iex",
                "transport": "websocket",
                "entitlement": "configured_not_verified",
            },
            "market_structure_patterns": [{"id": "range_break_retest", "complexity": "simple", "role": "setup"}],
            "market_structure_watchlist": [{
                "symbol": "NVDA",
                "decision": "READY_TO_REVIEW",
                "grade": "A",
                "score": 89,
                "best_setup": {"pattern_id": "range_break_retest"},
                "worst_setup": {"pattern_id": "late_chase_exhaustion"},
                "execution_enabled": False,
                "can_submit_orders": False,
            }],
            "candidates": [
                {
                    "candidate_id": "2026-08-19:NVDA:opening_range_break_retest",
                    "symbol": "NVDA",
                    "asset_class": "equity",
                    "setup_family": "opening_range_break_retest",
                    "direction": "bullish",
                    "decision_score": 88.0,
                    "grade": "A",
                    "state": "READY_TO_REVIEW",
                    "entry": 181.2,
                    "invalidation": 179.8,
                    "targets": [{"name": "target_2r", "price": 184.0}],
                    "reward_risk_after_friction": 1.91,
                    "source_labels": ["alpaca_iex_stream", "completed_5m_bars"],
                    "blockers": [],
                    "freshness": "live",
                    "execution_enabled": False,
                    "can_submit_orders": False,
                }
            ],
            "execution_enabled": False,
            "can_submit_orders": False,
        },
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)

    source = next(row for row in cockpit["sources"] if row["name"] == "live_opportunities")
    candidate = next(row for row in cockpit["candidates"] if row["source"] == "live_opportunities")
    assert source["freshness"] == "live"
    assert cockpit["live_opportunities"]["feed"]["feed"] == "iex"
    assert cockpit["live_opportunities"]["decision_state"] == "READY_TO_REVIEW"
    assert cockpit["live_opportunities"]["market_structure_watchlist"][0]["best_setup"]["pattern_id"] == "range_break_retest"
    assert cockpit["live_opportunities"]["market_structure_patterns"][0]["complexity"] == "simple"
    assert candidate["symbol"] == "NVDA"
    assert candidate["entry"] == 181.2
    assert candidate["stop"] == 179.8
    assert candidate["target"] == 184.0
    assert candidate["paper_consumable"] is False
    assert candidate["execution_enabled"] is False
    assert candidate["can_submit_orders"] is False


def test_cockpit_surfaces_cisd_promotion_status_as_read_only_discovery_evidence(tmp_path: Path) -> None:
    write_report(tmp_path, "cisd-promotion-status.json", {
        "last_updated_utc": "2026-08-19T14:59:58Z",
        "pattern_id": "ict_cisd_universal_model",
        "n_outcomes": 47,
        "n_unique_dates": 18,
        "wilson_lower_bound_95": 0.478,
        "brier_skill": 0.208,
        "eligible_for_validated_promotion": False,
        "execution_enabled": False,
        "can_submit_orders": False,
    })

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)

    status = cockpit["discovery"]["cisd_promotion_status"]
    source = next(row for row in cockpit["sources"] if row["name"] == "cisd_promotion")
    assert status["n_outcomes"] == 47
    assert status["eligible_for_validated_promotion"] is False
    assert source["freshness"] == "live"


def test_cockpit_surfaces_v2_research_governance_fail_closed(tmp_path: Path) -> None:
    write_report(tmp_path, "promotion_rules.json", {
        "schema_version": 2,
        "rule_version": "2026-08-23-v2",
        "multiple_testing": {"method": "benjamini_hochberg", "alpha": 0.05},
        "regime_coverage": {"required_regimes": ["trend", "chop", "high_vol", "low_vol"], "minimum_independent_dates_per_regime": 8},
        "latency": {"maximum_p90_fraction_of_expected_window": 0.2},
        "revalidation": {"maximum_age_days": 30},
        "data_integrity": {"require_backfill_and_regrade_after_source_repair": True},
        "universe": {"require_version": True},
    })
    (tmp_path / "promotion_decisions.jsonl").write_text(json.dumps({
        "candidate_id": "candidate-a",
        "decision": "hold",
        "failed_rules": [],
        "unavailable_rules": [{"rule_id": "PROMO_LATENCY_WINDOW_V2", "reason": "missing"}],
        "execution_enabled": False,
        "can_submit_orders": False,
    }) + "\n", encoding="utf-8")

    governance = build_cockpit(report_dir=tmp_path, now=NOW)["research_governance"]

    assert governance["promotion_rule_version"] == "2026-08-23-v2"
    assert governance["governance_status"] == "held_missing_evidence"
    assert governance["unavailable_rule_ids"] == ["PROMO_LATENCY_WINDOW_V2"]
    assert governance["controls"]["minimum_dates_per_regime"] == 8
    assert governance["controls"]["universe_version_required"] is True
    assert governance["execution_enabled"] is False
    assert governance["can_submit_orders"] is False


def test_cockpit_surfaces_pattern_evidence_and_fail_closed_daily_review_gate(tmp_path: Path) -> None:
    write_report(tmp_path, "pattern-grader-grades.json", {
        "generated_at": "2026-08-19T14:59:58Z",
        "provider": "pattern_grader_report",
        "summary": {"distinct_lifecycle_count": 7, "a_grade_count": 2, "qualified_probability_count": 0},
        "scan_reconciliation": {
            "eligible_symbol_count": 10,
            "evaluated_symbol_count": 10,
            "data_blocked_symbol_count": 1,
            "emitted_detection_count": 7,
            "abstained_symbol_count": 3,
            "producer_failure_count": 0,
            "denominator_reconciled": True,
        },
        "latest_detections": [],
        "execution_enabled": False,
        "can_submit_orders": False,
    })
    write_report(tmp_path, "daily-aplus-review.json", {
        "timestamp": "2026-08-19T14:59:30Z",
        "provider": "daily_aplus_review",
        "review_status": "attention_required",
        "summary": {
            "system_reviewed_setup_count": 2,
            "source_coverage_pct": 93.8,
            "overall_review_coverage_pct": 93.8,
            "outcome_followup_count": 2,
        },
        "source_inventory": [{"source": "pattern_grader", "status": "missing"}],
        "execution_enabled": False,
        "can_submit_orders": False,
    })

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)

    assert cockpit["discovery"]["pattern_grader"]["summary"]["a_grade_count"] == 2
    assert cockpit["daily_review_gate"]["status"] == "attention_required"
    assert cockpit["daily_review_gate"]["overall_review_coverage_pct"] == 93.8
    assert cockpit["daily_review_gate"]["failed_sources"] == ["pattern_grader"]
    assert cockpit["daily_review_gate"]["execution_enabled"] is False
    assert cockpit["daily_review_gate"]["can_submit_orders"] is False


def test_cockpit_surfaces_operational_readiness_and_execution_quality(tmp_path: Path) -> None:
    write_report(tmp_path, "manual-execution-quality.json", {
        "generated_at": "2026-08-19T14:59:58Z",
        "status": "followup_required",
        "summary": {"observation_count": 3, "missing_followup_count": 1},
        "execution_enabled": False,
        "can_submit_orders": False,
    })
    write_report(tmp_path, "broker-fill-observer.json", {
        "generated_at": "2026-08-19T14:59:58Z",
        "status": "ok",
        "summary": {"fill_count": 2, "matched_count": 1, "ambiguous_count": 1, "unmatched_count": 0},
        "execution_enabled": False,
        "can_submit_orders": False,
    })

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)

    assert cockpit["schema_version"] == 11
    assert cockpit["system_readiness"]["build"]["percent"] == 100.0
    assert cockpit["system_readiness"]["runtime"]["status"] == "attention_required"
    quality = cockpit["execution_quality"]
    assert quality["status"] == "followup_required"
    assert quality["manual_observations"] == 3
    assert quality["manual_followups"] == 1
    assert quality["broker_fills"] == 2
    assert quality["broker_linkage_issues"] == 1
    assert quality["execution_enabled"] is False
    assert quality["can_submit_orders"] is False


def test_schema_v6_exposes_provenance_gated_retro_journal_social_catalysts_and_options(
    tmp_path: Path,
) -> None:
    reports = {
        "daily-eod-summary.json": {
            "timestamp": "2026-08-19T14:59:30Z",
            "provider": "daily_eod_summary",
            "mode": "read_only",
            "verdict": "stand_aside",
        },
        "daily-outcome-review.json": {
            "timestamp": "2026-08-19T14:59:30Z",
            "provider": "daily_outcome_reviewer",
            "mode": "read_only",
            "review_score": 80,
        },
        "daily-aplus-review.json": {
            "timestamp": "2026-08-19T14:59:30Z",
            "provider": "daily_aplus_review",
            "mode": "read_only",
            "review_status": "complete",
            "summary": {"distinct_setup_count": 2, "system_review_coverage_pct": 100.0},
        },
        "closed-trade-postmortem.json": {
            "timestamp": "2026-08-19T14:59:30Z",
            "provider": "closed_trade_postmortem",
            "mode": "read_only",
            "postmortems": [],
        },
        "flip-decision-missed-banger-review.json": {
            "generated_at": "2026-08-19T14:59:30Z",
            "provider": "flip_decision_missed_banger_review",
            "mode": "read_only_research",
            "evaluations": [],
        },
        "rejected-trade-intelligence.json": {
            "timestamp": "2026-08-19T14:59:30Z",
            "provider": "rejected_trade_intelligence",
            "mode": "read_only",
            "recent_reviews": [],
        },
        "trade-lesson-ledger.json": {
            "generated_at": "2026-08-19T14:59:30Z",
            "provider": "trade_lesson_ledger",
            "mode": "read_only",
            "lessons": [],
        },
        "needs-review-queue.json": {
            "timestamp": "2026-08-19T14:59:30Z",
            "provider": "needs_review_queue",
            "mode": "read_only",
            "items": [],
        },
        "verified-trader-evidence.json": {
            "generated_at": "2026-08-19T14:59:30Z",
            "provider": "verified_trader_evidence",
            "mode": "shadow_only",
            "profiles": [],
        },
        "public-social-intake.json": {
            "timestamp": "2026-08-19T14:59:30Z",
            "provider": "public_social_intake_scanner",
            "mode": "context_only",
            "observation_count": 0,
        },
        "social-trending-symbols.json": {
            "timestamp": "2026-08-19T14:59:30Z",
            "provider": "social_trending_symbols_scanner",
            "mode": "context_only",
            "symbols": [],
        },
        "market-catalyst-calendar.json": {
            "generated_at": "2026-08-19T14:59:30Z",
            "provider": "market_catalyst_calendar",
            "mode": "read_only",
            "today": {"date": "2026-08-19", "events": [{"name": "FOMC minutes"}]},
            "upcoming": [
                {"date": "2026-08-20", "events": [{"name": "Jobless claims"}]},
                {"date": "2026-08-21", "events": [{"name": "Outside slice"}]},
            ],
        },
        "options-surface-intelligence.json": {
            "generated_at": "2026-08-19T14:59:30Z",
            "provider": "options_surface_intelligence",
            "mode": "read_only_shadow_research",
            "results": [{"symbol": "SPY", "status": "ok"}],
        },
        "options-liquidation-heatmap.json": {
            "generated_at": "2026-08-19T14:59:30Z",
            "provider": "options_liquidation_heatmap",
            "mode": "read_only_shadow_research",
            "results": [{"symbol": "SPY", "status": "ok"}],
        },
        "options-vol-premium.json": {
            "generated_at": "2026-08-19T14:59:30Z",
            "provider": "options_vol_premium_report",
            "mode": "forward_only_shadow_research",
            "rows": [],
        },
        "options-feed-qualification.json": {
            "generated_at": "2026-08-19T14:59:59Z",
            "provider": "options_feed_qualification",
            "mode": "read_only_evidence_qualification",
            "status": "manual_execution_reference_available",
            "summary": {"price_discovery_qualified": 1, "manual_execution_qualified": 1},
            "records": [],
            "execution_enabled": False,
            "can_submit_orders": False,
        },
    }
    for filename, payload in reports.items():
        write_report(tmp_path, filename, payload)

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)

    assert cockpit["schema_version"] == 11
    for group_name in ("retro", "journal", "social"):
        group = cockpit["evidence"][group_name]
        assert group["execution_enabled"] is False
        assert group["can_submit_orders"] is False

    daily_eod = cockpit["evidence"]["retro"]["daily_eod"]
    assert daily_eod["source"] == "daily_eod"
    assert daily_eod["freshness"] == "live"
    assert daily_eod["data"]["verdict"] == "stand_aside"
    assert daily_eod["execution_enabled"] is False
    assert daily_eod["can_submit_orders"] is False
    aplus = cockpit["evidence"]["retro"]["aplus_review"]
    assert aplus["data"]["summary"]["system_review_coverage_pct"] == 100.0
    assert aplus["execution_enabled"] is False
    assert aplus["can_submit_orders"] is False

    catalysts = cockpit["evidence"]["catalysts_today"]
    assert [row["date"] for row in catalysts["days"]] == ["2026-08-19", "2026-08-20"]
    assert catalysts["source"] == "catalysts"
    assert catalysts["execution_enabled"] is False
    assert catalysts["can_submit_orders"] is False

    options = cockpit["options_context"]
    assert options["status"] == "context_available"
    assert options["completeness"] == "complete"
    assert options["surface"]["source"] == "options_surface"
    assert options["heatmap"]["source"] == "options_heatmap"
    assert options["vol_premium"]["source"] == "vol_premium"
    assert options["feed_qualification"]["source"] == "options_feed_qualification"
    assert options["manual_execution_reference_available"] is True
    assert options["price_discovery_qualified_count"] == 1
    assert options["execution_enabled"] is False
    assert options["can_submit_orders"] is False

    sources = {row["name"]: row for row in cockpit["sources"]}
    for name in (
        "daily_eod",
        "daily_outcome",
        "aplus_review",
        "closed_postmortem",
        "missed_banger",
        "rejected_intel",
        "lesson_ledger",
        "needs_review",
        "verified_trader",
        "public_intake",
        "trending_symbols",
        "options_heatmap",
    ):
        assert sources[name]["available"] is True
        assert sources[name]["execution_enabled"] is False
        assert sources[name]["can_submit_orders"] is False


def test_load_source_is_whitelisted(tmp_path: Path) -> None:
    write_report(tmp_path, "market-force-score.json", {"classification": "bullish_lean"})

    assert load_source("market_force", report_dir=tmp_path)["classification"] == "bullish_lean"
    with pytest.raises(KeyError):
        load_source("../agent/.env", report_dir=tmp_path)


def test_trade_board_scores_factors_without_inventing_probability_or_contract(tmp_path: Path) -> None:
    write_report(
        tmp_path,
        "daily-stock-screener.json",
        {
            "generated_at": "2026-08-19T14:55:00Z",
            "rankings": [{
                "symbol": "NVDA",
                "status": "qualified_long",
                "direction": "long",
                "long_eligible": True,
                "blockers": [],
                "score": 92,
                "price": 180,
                "avg_dollar_volume_20d": 2_000_000_000,
                "relative_strength_vs_spy_20d_pct": 4.5,
            }],
        },
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)
    plan = cockpit["trade_board"]["stocks"][0]

    assert cockpit["schema_version"] == 11
    assert plan["grade"] in {"A+", "A", "A-", "B+", "B", "B-", "C", "D"}
    assert plan["probability"]["value"] is None
    assert plan["trade_plan"]["contract"] is None
    assert "strategy_trigger_not_present" in plan["blockers"]
    assert "live_option_contract_not_confirmed" not in plan["blockers"]
    assert cockpit["trade_board"]["score_definition"].endswith("not probability of profit.")


def test_probability_first_ranking_uses_only_qualified_forward_calibration(tmp_path: Path) -> None:
    def live_row(symbol: str, score: float, probability: dict) -> dict:
        return {
            "candidate_id": f"2026-08-21:{symbol}:range_break_retest",
            "symbol": symbol,
            "asset_class": "equity",
            "setup_family": "range_break_retest",
            "direction": "bullish",
            "reason": "confirmed structure",
            "decision_score": score,
            "grade": "A",
            "state": "READY_TO_REVIEW",
            "freshness": "live",
            "entry": 100.0,
            "invalidation": 99.0,
            "targets": [{"name": "target_2r", "price": 102.0}],
            "reward_risk_after_friction": 2.0,
            "rvol_time_of_day": 2.0,
            "source_labels": ["completed_5m_bars", "pattern_grade_v1"],
            "blockers": [],
            "factor_scores": {"liquidity": 90, "relative_strength": 85},
            "probability": probability,
            "execution_enabled": False,
            "can_submit_orders": False,
        }

    write_report(
        tmp_path,
        "live-opportunity-engine.json",
        {
                "generated_at": "2026-08-19T15:00:00Z",
            "candidates": [
                live_row("QUALITY", 96, {
                    "value": 82,
                    "status": "calibrated_holdout",
                    "sample_size": 35,
                    "independent_dates": 12,
                    "lower_bound": 66,
                    "brier_skill_vs_expanding_base_rate": 0.08,
                }),
                live_row("PROB", 88, {
                    "value": 68,
                    "status": "calibrated_holdout",
                    "sample_size": 180,
                    "independent_dates": 42,
                    "lower_bound": 61,
                    "brier_skill_vs_expanding_base_rate": 0.05,
                }),
            ],
        },
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)

    assert cockpit["ranking_policy"]["mode"] == "conditional_probability_first"
    assert cockpit["ranking_policy"]["qualified_candidate_count"] == 1
    assert cockpit["headline"]["best_setup"]["symbol"] == "PROB"
    assert cockpit["headline"]["best_setup"]["probability"]["value"] == 68.0
    assert cockpit["headline"]["best_setup"]["probability"]["ranking_eligible"] is True
    quality = next(row for row in cockpit["candidates"] if row["symbol"] == "QUALITY")
    assert quality["probability"]["ranking_eligible"] is False
    assert "fewer_than_100_samples" in quality["probability"]["qualification_failures"]


def test_mes_board_labels_holdout_rate_as_reference_not_forecast(tmp_path: Path) -> None:
    write_report(
        tmp_path,
        "mes_reopen_vix_holdout.json",
        {
            "rule": {"vix_cap": 18, "prior_move_floor": -0.01},
            "test_2025_2026": {"trades": 171, "win_rate": 0.5906, "sharpe_annual": 1.751, "profit_factor": 1.3171},
            "practice_promotion_eligible": False,
        },
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)
    plan = cockpit["trade_board"]["futures"][0]

    assert plan["symbol"] == "MES"
    assert plan["probability"]["value"] == 59.1
    assert plan["probability"]["status"] == "historical_reference_only"
    assert plan["paper_consumable"] is False


def test_decision_desk_separates_armed_from_confirmed_but_late(tmp_path: Path) -> None:
    write_report(
        tmp_path,
        "intraday-opportunity-radar.json",
        {
            "ranked_candidates": [
                {
                    "symbol": "EARLY",
                    "state": "precision_watch",
                    "score": 86,
                    "setup": "opening_range_breakout",
                    "direction": "bullish",
                    "price": 99.9,
                    "hard_gates": {"liquidity": True, "geometry": True},
                    "factor_scores": {"liquidity": 90, "magnitude": 82, "structure": 88},
                    "price_action_confirmation": {
                        "state": "waiting",
                        "bar_completed_at": "2026-08-19T14:55:00Z",
                    },
                    "trade_levels": {"confirmation_trigger": 100, "invalidation": 99, "target_2r": 102},
                    "blockers": ["strategy_confirmation_and_revalidation_required"],
                },
                {
                    "symbol": "LATE",
                    "state": "precision_watch",
                    "score": 91,
                    "setup": "opening_range_breakout",
                    "direction": "bullish",
                    "price": 101.2,
                    "hard_gates": {"liquidity": True, "geometry": True},
                    "factor_scores": {"liquidity": 92, "magnitude": 90, "structure": 92},
                    "price_action_confirmation": {"state": "bullish_confirmed"},
                    "trade_levels": {"confirmation_trigger": 100, "invalidation": 99, "target_2r": 102},
                    "blockers": ["strategy_confirmation_and_revalidation_required"],
                },
            ],
        },
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)
    rows = {row["symbol"]: row for row in cockpit["candidates"]}

    assert rows["EARLY"]["actionability"] == "wait"
    assert rows["EARLY"]["lifecycle"] == "armed"
    assert rows["LATE"]["actionability"] == "late_no_chase"
    assert rows["LATE"]["move_consumed_pct"] == 60.0
    assert rows["LATE"]["decision_score"] < rows["LATE"]["setup_score"]
    assert cockpit["decision_desk"]["counts"]["wait"] == 1
    assert cockpit["decision_desk"]["counts"]["late_no_chase"] == 1


def test_decision_desk_uses_one_dominant_plan_per_symbol(tmp_path: Path) -> None:
    write_report(
        tmp_path,
        "intraday-opportunity-radar.json",
        {
            "ranked_candidates": [
                {
                    "symbol": "WMT",
                    "state": "precision_watch",
                    "score": 86,
                    "setup": "opening_drive",
                    "direction": "bullish",
                    "price": 103.8,
                    "hard_gates": {"liquidity": True, "geometry": True},
                    "price_action_confirmation": {
                        "state": "waiting",
                        "bar_completed_at": "2026-08-19T14:59:00Z",
                    },
                    "trade_levels": {"confirmation_trigger": 104, "invalidation": 103, "target_2r": 106},
                    "blockers": ["strategy_confirmation_and_revalidation_required"],
                },
                {
                    "symbol": "WMT",
                    "state": "precision_watch",
                    "score": 70,
                    "setup": "late_breakout",
                    "direction": "bullish",
                    "price": 103.8,
                    "hard_gates": {"liquidity": True, "geometry": True},
                    "price_action_confirmation": {"state": "bullish_confirmed"},
                    "trade_levels": {"confirmation_trigger": 102, "invalidation": 101, "target_2r": 104},
                    "blockers": ["strategy_confirmation_and_revalidation_required"],
                },
            ],
        },
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)
    desk_rows = (
        cockpit["decision_desk"]["best_now"]
        + cockpit["decision_desk"]["next_up"]
        + cockpit["decision_desk"]["no_chase"]
        + cockpit["decision_desk"]["invalid"]
    )

    assert [row["symbol"] for row in desk_rows].count("WMT") == 1


def test_command_card_simplifies_armed_plan_without_inventing_zone(tmp_path: Path) -> None:
    write_report(
        tmp_path,
        "intraday-opportunity-radar.json",
        {
            "ranked_candidates": [
                {
                    "symbol": "SPY",
                    "state": "precision_watch",
                    "score": 88,
                    "setup": "orb_break_retest_volume",
                    "direction": "bullish",
                    "price": 771.8,
                    "hard_gates": {"liquidity": True, "geometry": True},
                    "factor_scores": {"liquidity": 94, "magnitude": 84, "structure": 91},
                    "price_action_confirmation": {
                        "state": "waiting",
                        "bar_completed_at": "2026-08-19T14:59:00Z",
                    },
                    "trade_levels": {
                        "confirmation_trigger": 772.0,
                        "invalidation": 770.9,
                        "target_2r": 774.2,
                    },
                    "blockers": ["strategy_confirmation_and_revalidation_required"],
                }
            ],
        },
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)
    command = cockpit["command_card"]

    assert command["state"] == "WAIT"
    assert command["symbol"] == "SPY"
    assert command["trigger"] == 772.0
    assert command["invalidation"] == 770.9
    assert command["target"] == 774.2
    assert command["no_trade_zone"]["status"] == "not_supplied"
    assert "none was inferred" in command["no_trade_zone"]["instruction"]
    assert command["evidence_fresh"] is True
    assert command["execution_enabled"] is False
    assert command["can_submit_orders"] is False


def test_command_card_carries_only_source_defined_no_trade_zone(tmp_path: Path) -> None:
    write_report(
        tmp_path,
        "intraday-opportunity-radar.json",
        {
            "ranked_candidates": [
                {
                    "symbol": "QQQ",
                    "state": "precision_watch",
                    "score": 83,
                    "setup": "break_retest",
                    "direction": "bearish",
                    "price": 700.5,
                    "hard_gates": {"liquidity": True, "geometry": True},
                    "price_action_confirmation": {"state": "waiting"},
                    "trade_levels": {
                        "confirmation_trigger": 700.0,
                        "invalidation": 702.0,
                        "target_2r": 696.0,
                        "no_trade_zone": {"low": 700.0, "high": 703.0},
                    },
                    "blockers": ["strategy_confirmation_and_revalidation_required"],
                }
            ],
        },
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)

    assert cockpit["command_card"]["no_trade_zone"] == {
        "status": "available",
        "low": 700.0,
        "high": 703.0,
        "instruction": "Stand aside while price remains between 700 and 703.",
    }


def test_command_card_stands_aside_when_completed_bar_is_stale(tmp_path: Path) -> None:
    write_report(
        tmp_path,
        "intraday-opportunity-radar.json",
        {
            "ranked_candidates": [
                {
                    "symbol": "ETHA",
                    "state": "precision_watch",
                    "score": 82,
                    "setup": "opening_range_breakout",
                    "direction": "bullish",
                    "price": 17.55,
                    "hard_gates": {"liquidity": True, "geometry": True},
                    "price_action_confirmation": {
                        "state": "waiting",
                        "bar_completed_at": "2026-08-19T13:00:00Z",
                    },
                    "trade_levels": {
                        "confirmation_trigger": 17.57,
                        "invalidation": 17.52,
                        "target_2r": 17.67,
                    },
                    "blockers": ["strategy_confirmation_and_revalidation_required"],
                }
            ],
        },
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)
    command = cockpit["command_card"]

    assert command["state"] == "STAND_ASIDE"
    assert command["evidence_fresh"] is False
    assert command["evidence_age_seconds"] == 7200.0
    assert "stale or unavailable" in command["next_action"]


def test_dealer_gamma_regime_stays_unavailable_without_qualified_feed(tmp_path: Path) -> None:
    write_report(
        tmp_path,
        "market-force-score.json",
        {
            "forces": [
                {
                    "name": "levels_gex",
                    "status": "unavailable",
                    "evidence": {
                        "negative_gamma": 12,
                        "positive_gamma": 2,
                        "reason": "no provenance-qualified 0dte scans",
                    },
                }
            ]
        },
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)
    dealer = cockpit["dealer_regime"]

    assert dealer["status"] == "unavailable"
    assert dealer["quadrant"] is None
    assert dealer["spot_vs_flip"] == "unavailable"
    assert dealer["execution_authority"] is False


def test_reconciliation_diff_forces_stand_aside_and_exposes_weekly_failures(tmp_path: Path) -> None:
    write_report(
        tmp_path,
        "failure-taxonomy.json",
        {
            "records": [
                {"date": "2026-08-18T15:00:00Z", "category": "BAD_ENTRY"},
                {"date": "2026-08-19T14:00:00Z", "category": "BAD_ENTRY"},
                {"date": "2026-08-19T14:30:00Z", "category": "STALE_DATA"},
            ]
        },
    )
    write_report(
        tmp_path,
        "broker-reconciliation.json",
        {
            "run_at": "2026-08-19T14:59:00Z",
            "status": "diff",
            "diff_count": 1,
            "issues": ["reconciliation:position_quantity_mismatch:SPYOPT"],
        },
    )
    (tmp_path / "reconciliation_events.jsonl").write_text(
        json.dumps({"run_at": "2026-08-19T14:59:00Z", "status": "diff", "diff_count": 1}) + "\n",
        encoding="utf-8",
    )

    cockpit = build_cockpit(report_dir=tmp_path, now=NOW)

    assert cockpit["schema_version"] == 11
    assert cockpit["command_card"]["state"] == "STAND_ASIDE"
    assert cockpit["command_card"]["color"] == "RED"
    assert cockpit["operations"]["failure_taxonomy_week"] == {"BAD_ENTRY": 2, "STALE_DATA": 1}
    assert cockpit["operations"]["reconciliation_status"]["status"] == "diff"
    assert cockpit["operations"]["reconciliation_status"]["diff_count_24h"] == 1
    assert "reconciliation:position_quantity_mismatch:SPYOPT" in cockpit["operations"]["risk_blockers"]
    assert cockpit["authority"]["can_submit_orders"] is False
