from __future__ import annotations

from scripts.detection_scorecard import build_pattern_coverage, build_rolling, build_scorecard
from scripts.move_universe_ground_truth import build_ground_truth
from scripts.universe_coverage_delta import build_coverage_delta


def _snapshot(stamp: str, ranked: list[tuple[str, str]]) -> dict:
    return {
        "date": "2026-08-21",
        "generated_at": stamp,
        "all_discovered_symbols": [symbol for symbol, _ in ranked] + ["LATE"],
        "ranked_candidates": [
            {"symbol": symbol, "direction": direction, "avg_dollar_volume_20d": 100_000_000}
            for symbol, direction in ranked
        ],
        "market_movers": [{"symbol": symbol, "percent_change": 2.0} for symbol, _ in ranked],
    }


def test_ground_truth_filters_liquidity_and_freezes_manual_only_moves() -> None:
    radar = {
        "date": "2026-08-21",
        "market_movers": [
            {"symbol": "WIN", "percent_change": 8.0, "price": 20.0},
            {"symbol": "THIN", "percent_change": 20.0, "price": 3.0},
        ],
        "ranked_candidates": [],
        "filtered_candidates": [],
    }
    report = build_ground_truth(
        radar,
        [_snapshot("2026-08-21T14:00:00Z", [("WIN", "bullish")])],
        liquidity_by_symbol={"WIN": 100_000_000, "THIN": 5_000_000},
    )

    assert [row["symbol"] for row in report["moves"]] == ["WIN"]
    assert report["moves"][0]["move_start_at"] == "2026-08-21T14:00:00Z"
    assert report["excluded"][0]["exclusion_reasons"] == ["average_dollar_volume_below_minimum"]
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_detection_scorecard_partitions_discovery_ranking_and_latency() -> None:
    ground = {
        "date": "2026-08-21",
        "moves": [
            {"move_id": "1", "date": "2026-08-21", "symbol": "WIN", "direction": "bullish", "move_pct": 8, "move_start_at": "2026-08-21T14:00:00Z"},
            {"move_id": "2", "date": "2026-08-21", "symbol": "LATE", "direction": "bearish", "move_pct": -6, "move_start_at": "2026-08-21T14:00:00Z"},
            {"move_id": "3", "date": "2026-08-21", "symbol": "MISS", "direction": "bullish", "move_pct": 5, "move_start_at": "2026-08-21T14:00:00Z"},
        ],
    }
    history = [
        _snapshot("2026-08-21T13:55:00Z", [("WIN", "bullish")]),
        _snapshot("2026-08-21T14:30:00Z", [("WIN", "bullish"), ("LATE", "bearish")]),
    ]
    report = build_scorecard(ground, history, k=1, regime="trend")
    partitions = {row["symbol"]: row["partition"] for row in report["moves"]}

    assert report["metrics"]["recall_at_k"] == 0.3333
    assert report["metrics"]["precision_at_k"] == 1.0
    assert partitions == {"WIN": "confirmation_miss", "LATE": "ranking_miss", "MISS": "discovery_miss"}
    assert report["per_regime"]["trend"] == report["metrics"]
    assert report["execution_enabled"] is False

    rolling = build_rolling([report])
    assert rolling["metrics"]["recall_at_10"] == 0.3333
    assert rolling["metrics"]["actionable_recall_at_10"] == 0.3333
    assert rolling["metrics"]["discovery_recall_at_10"] == 0.3333
    assert rolling["summary"]["stage_counts"]["market_moves"] == 3
    assert rolling["summary"]["staged_sessions"] == 1
    assert rolling["latest_session"] == {
        "date": "2026-08-21",
        "stage_counts": report["summary"]["stage_counts"],
        "market_coverage": report["market_coverage"],
        "ground_truth_count": 3,
        "market_move_window_count": 3,
    }
    assert len(rolling["top_missed_moves"]) == 3


def test_detection_scorecard_uses_actionable_ranking_without_losing_discovery_metrics() -> None:
    ground = {
        "date": "2026-08-21",
        "moves": [
            {"move_id": "1", "date": "2026-08-21", "symbol": "SAFE", "direction": "bullish", "move_pct": 6, "move_start_at": "2026-08-21T14:00:00Z"},
            {"move_id": "2", "date": "2026-08-21", "symbol": "CHASE", "direction": "bullish", "move_pct": 12, "move_start_at": "2026-08-21T14:00:00Z"},
        ],
    }
    history = [{
        "date": "2026-08-21",
        "generated_at": "2026-08-21T13:55:00Z",
        "all_discovered_symbols": ["SAFE", "CHASE"],
        "ranked_candidates": [
            {"symbol": "CHASE", "direction": "bullish", "state": "filtered"},
            {"symbol": "SAFE", "direction": "bullish", "state": "precision_watch"},
        ],
        "actionable_ranked_candidates": [
            {"symbol": "SAFE", "direction": "bullish", "state": "precision_watch", "ranking_score": 91},
        ],
    }]

    report = build_scorecard(ground, history, k=1, regime="trend")
    rows = {row["symbol"]: row for row in report["moves"]}

    assert report["metrics"]["ranking_source"] == "actionable_ranked_candidates"
    assert report["metrics"]["recall_at_k"] == 0.5
    assert report["metrics"]["precision_at_k"] == 1.0
    assert report["metrics"]["discovery_recall_at_k"] == 0.5
    assert report["metrics"]["discovery_precision_at_k"] == 1.0
    assert rows["SAFE"]["partition"] == "correct_entry"
    assert rows["CHASE"]["partition"] == "ranking_miss"
    assert rows["CHASE"]["first_discovery_rank"] == 1
    assert rows["CHASE"]["first_actionable_rank"] is None


def test_benchmark_ground_truth_uses_benchmark_lane_not_penny_stock_rank() -> None:
    report = build_scorecard(
        {
            "date": "2026-08-21",
            "moves": [{
                "move_id": "QQQ:move",
                "symbol": "QQQ",
                "timeframe": "5m",
                "direction": "bearish",
                "move_start_at": "2026-08-21T14:00:00Z",
                "horizon_end_ts": "2026-08-21T15:00:00Z",
            }],
        },
        [{
            "date": "2026-08-21",
            "generated_at": "2026-08-21T13:55:00Z",
            "all_discovered_symbols": ["PENNY", "QQQ"],
            "ranked_candidates": [
                {"symbol": "PENNY", "direction": "bullish", "ranking_score": 99},
                {"symbol": "QQQ", "direction": "bearish", "ranking_score": 70},
            ],
            "actionable_ranked_candidates": [{"symbol": "PENNY", "direction": "bullish"}],
            "benchmark_lane": {
                "symbols": ["SPY", "QQQ", "IWM"],
                "ranked_candidates": [{
                    "symbol": "QQQ",
                    "direction": "bearish",
                    "lane_rank": 1,
                    "confirmation_stage": "completed_5m_confirmed",
                }],
                "actionable_ranked_candidates": [{
                    "symbol": "QQQ",
                    "direction": "bearish",
                    "lane_rank": 1,
                    "confirmation_stage": "completed_5m_confirmed",
                }],
            },
        }],
    )

    move = report["moves"][0]
    assert move["ranking_lane"] == "benchmark"
    assert move["first_discovery_rank"] == 1
    assert move["first_actionable_rank"] == 1
    assert move["radar_linkage"]["rank"] == 1
    assert move["radar_linkage"]["execution_rank"] == 1
    assert move["stages"]["execution_qualified"] is True


def test_stale_prior_snapshot_is_a_coverage_miss_not_a_discovery() -> None:
    report = build_scorecard(
        {
            "date": "2026-08-21",
            "moves": [{
                "move_id": "QQQ:late",
                "symbol": "QQQ",
                "direction": "bullish",
                "move_start_at": "2026-08-21T15:45:00Z",
            }],
        },
        [{
            "date": "2026-08-21",
            "generated_at": "2026-08-21T14:10:00Z",
            "all_discovered_symbols": ["QQQ"],
            "ranked_candidates": [{"symbol": "QQQ", "direction": "bullish"}],
        }],
    )

    link = report["move_windows"][0]["radar_linkage"]
    assert link["status"] == "stale_prior_snapshot"
    assert link["snapshot_lead_minutes"] == 95.0
    assert link["stale_rank"] == 1
    assert link["rank"] is None
    assert link["stages"]["discovered"] is False
    assert report["metrics"]["recall_at_k"] == 0.0
    assert report["metrics"]["discovery_recall_at_k"] == 0.0


def test_rank_metrics_use_distinct_move_windows_not_duplicate_labels() -> None:
    report = build_scorecard(
        {
            "date": "2026-08-21",
            "moves": [
                {"move_id": "QQQ:5m", "symbol": "QQQ", "timeframe": "5m", "direction": "bearish", "move_start_at": "2026-08-21T14:00:00Z", "horizon_end_ts": "2026-08-21T15:00:00Z"},
                {"move_id": "QQQ:15m", "symbol": "QQQ", "timeframe": "15m", "direction": "bearish", "move_start_at": "2026-08-21T14:00:00Z", "horizon_end_ts": "2026-08-21T15:30:00Z"},
            ],
        },
        [{
            "date": "2026-08-21",
            "generated_at": "2026-08-21T13:55:00Z",
            "all_discovered_symbols": ["QQQ"],
            "ranked_candidates": [{"symbol": "QQQ", "direction": "bearish"}],
        }],
    )

    assert report["metrics"]["ground_truth_count"] == 1
    assert report["metrics"]["ground_truth_label_count"] == 2
    assert report["metrics"]["recall_at_k"] == 1.0
    assert report["metrics"]["precision_at_k"] == 1.0


def test_scorecard_links_nearest_prior_snapshot_and_clusters_overlapping_labels() -> None:
    ground = {
        "date": "2026-08-21",
        "metrics_qualified": False,
        "pair_status": [
            {"instrument": "QQQ", "timeframe": "5m", "qualified": True},
            {"instrument": "NQ", "timeframe": "5m", "qualified": False, "reason": "bars_unavailable_or_not_entitled"},
        ],
        "moves": [
            {
                "move_id": "QQQ:one",
                "symbol": "QQQ",
                "timeframe": "5m",
                "direction": "bearish",
                "move_start_at": "2026-08-21T14:00:00Z",
                "horizon_end_ts": "2026-08-21T15:00:00Z",
                "metrics_qualified": True,
                "peak_favorable_short": 3.0,
                "peak_adverse_short": 0.4,
                "achievable_r_short": 5.0,
                "realized_r_short": 2.0,
            },
            {
                "move_id": "QQQ:two",
                "symbol": "QQQ",
                "timeframe": "5m",
                "direction": "bearish",
                "move_start_at": "2026-08-21T14:05:00Z",
                "horizon_end_ts": "2026-08-21T15:05:00Z",
                "metrics_qualified": True,
                "peak_favorable_short": 4.0,
                "peak_adverse_short": 0.2,
                "achievable_r_short": 7.5,
                "realized_r_short": 3.0,
            },
            {
                "move_id": "QQQ:three",
                "symbol": "QQQ",
                "timeframe": "5m",
                "direction": "bullish",
                "move_start_at": "2026-08-21T14:30:00Z",
                "horizon_end_ts": "2026-08-21T15:30:00Z",
                "metrics_qualified": True,
                "peak_favorable_long": 2.5,
                "peak_adverse_long": 0.1,
                "achievable_r_long": 4.0,
                "realized_r_long": 1.5,
            },
        ],
    }
    history = [
        {
            "date": "2026-08-21",
            "generated_at": "2026-08-21T13:55:00Z",
            "all_discovered_symbols": ["QQQ"],
            "ranked_candidates": [
                {"symbol": "OTHER", "direction": "bullish"},
                {
                    "symbol": "QQQ",
                    "direction": "bearish",
                    "price_action_confirmation": {"state": "bearish_confirmed"},
                },
            ],
            "actionable_ranked_candidates": [{"symbol": "QQQ", "direction": "bearish"}],
        },
        {
            "date": "2026-08-21",
            "generated_at": "2026-08-21T14:25:00Z",
            "all_discovered_symbols": ["QQQ"],
            "ranked_candidates": [
                {
                    "symbol": "QQQ",
                    "direction": "bullish",
                    "state": "precision_watch",
                    "confirmation_stage": "completed_5m_confirmed",
                    "blockers": ["strategy_confirmation_and_revalidation_required"],
                }
            ],
            "actionable_ranked_candidates": [{"symbol": "QQQ", "direction": "bullish"}],
        },
    ]

    report = build_scorecard(ground, history, k=10)

    assert report["summary"]["stage_counts"] == {
        "market_moves": 2,
        "discovered": 2,
        "setup_confirmed": 2,
        "execution_qualified": 2,
    }
    assert len(report["moves"]) == 3  # legacy per-label denominator remains available
    assert len(report["move_windows"]) == 2
    bearish = next(row for row in report["move_windows"] if row["direction"] == "bearish")
    assert bearish["constituent_move_ids"] == ["QQQ:one", "QQQ:two"]
    assert bearish["radar_linkage"]["radar_snapshot_at"] == "2026-08-21T13:55:00Z"
    assert bearish["outcome_linkage"]["mfe"] == 4.0
    assert bearish["outcome_linkage"]["mae"] == 0.4
    assert bearish["outcome_linkage"]["max_achievable_r"] == 7.5
    assert bearish["outcome_linkage"]["direction_correct"] is True
    assert bearish["outcome_linkage"]["rank"] == 2
    assert bearish["outcome_linkage"]["latency_minutes"] == -5.0
    assert bearish["outcome_linkage"]["fill_assumed"] is False
    assert report["market_coverage"]["status"] == "partial"
    assert report["market_coverage"]["unavailable_instruments"] == ["NQ"]
    assert report["market_coverage"]["no_move_interpretation_allowed"] is False
    assert report["metrics"]["ground_truth_count"] == 2
    assert report["metrics"]["ground_truth_label_count"] == 3
    assert report["metrics"]["market_move_window_count"] == 2


def test_move_windows_deduplicate_one_economic_move_across_timeframes() -> None:
    ground = {
        "date": "2026-08-21",
        "moves": [
            {
                "move_id": "QQQ:5m",
                "symbol": "QQQ",
                "timeframe": "5m",
                "direction": "bearish",
                "move_start_at": "2026-08-21T14:00:00Z",
                "horizon_end_ts": "2026-08-21T15:00:00Z",
                "peak_favorable_short": 3.0,
                "peak_adverse_short": 0.4,
                "achievable_r_short": 5.0,
            },
            {
                "move_id": "QQQ:15m",
                "symbol": "QQQ",
                "timeframe": "15m",
                "direction": "bearish",
                "move_start_at": "2026-08-21T14:00:00Z",
                "horizon_end_ts": "2026-08-21T15:30:00Z",
                "peak_favorable_short": 4.0,
                "peak_adverse_short": 0.2,
                "achievable_r_short": 7.5,
            },
        ],
    }
    history = [{
        "date": "2026-08-21",
        "generated_at": "2026-08-21T13:55:00Z",
        "all_discovered_symbols": ["QQQ"],
        "ranked_candidates": [{"symbol": "QQQ", "direction": "bearish"}],
    }]

    report = build_scorecard(ground, history)

    assert report["summary"]["stage_counts"]["market_moves"] == 1
    assert report["metrics"]["market_move_window_count"] == 1
    assert report["move_windows"][0]["timeframes"] == ["15m", "5m"]
    assert report["move_windows"][0]["constituent_move_ids"] == ["QQQ:5m", "QQQ:15m"]


def test_explicit_awaiting_confirmation_cannot_be_promoted_by_legacy_watch_state() -> None:
    report = build_scorecard(
        {
            "date": "2026-08-21",
            "moves": [{
                "move_id": "QQQ:waiting",
                "symbol": "QQQ",
                "timeframe": "5m",
                "direction": "bullish",
                "move_start_at": "2026-08-21T14:00:00Z",
            }],
        },
        [{
            "date": "2026-08-21",
            "generated_at": "2026-08-21T13:55:00Z",
            "all_discovered_symbols": ["QQQ"],
            "ranked_candidates": [{
                "symbol": "QQQ",
                "direction": "bullish",
                "state": "precision_watch",
                "setup_confirmed": True,
                "confirmation_stage": "awaiting_completed_5m_confirmation",
                "blockers": ["strategy_confirmation_and_revalidation_required"],
            }],
            "actionable_ranked_candidates": [{"symbol": "QQQ", "direction": "bullish"}],
        }],
    )

    stages = report["move_windows"][0]["stages"]
    assert stages == {
        "market_move": True,
        "discovered": True,
        "setup_confirmed": False,
        "execution_qualified": False,
    }


def test_unavailable_coverage_is_not_reported_as_no_market_move() -> None:
    report = build_scorecard(
        {
            "date": "2026-08-21",
            "metrics_qualified": False,
            "ground_truth_status": "partial_fail_closed",
            "pair_status": [
                {"instrument": "NQ", "timeframe": "5m", "qualified": False, "reason": "bars_unavailable_or_not_entitled"}
            ],
            "moves": [],
        },
        [],
    )

    assert report["summary"]["stage_counts"]["market_moves"] == 0
    assert report["market_coverage"]["status"] == "unavailable"
    assert report["market_coverage"]["no_move_interpretation_allowed"] is False
    assert "unknown, not evidence" in report["market_coverage"]["message"]
    assert any("must not be interpreted as no move" in warning for warning in report["warnings"])


def test_universe_delta_assigns_a_root_cause_to_every_truth_move() -> None:
    ground = {"date": "2026-08-21", "moves": [{"move_id": "1", "symbol": "WIN", "move_pct": 8}, {"move_id": "2", "symbol": "MISS", "move_pct": 6}]}
    report = build_coverage_delta(ground, {"all_discovered_symbols": ["WIN"]})

    assert report["summary"]["covered"] == 1
    assert {row["symbol"]: row["root_cause"] for row in report["rows"]} == {"WIN": "covered", "MISS": "discovery_source_gap"}
    assert report["execution_enabled"] is False


def test_pattern_scorecard_measures_family_precision_recall_and_coverage_delta() -> None:
    ground = {
        "date": "2026-08-21",
        "metrics_qualified": True,
        "pattern_annotation_qualified": True,
        "moves": [
            {"symbol": "AAA", "pattern_ids": ["ict_cisd_universal_model"]},
            {"symbol": "BBB", "pattern_ids": ["ict_cisd_universal_model"]},
        ],
    }
    grader = [
        {"date": "2026-08-21", "symbol": "AAA", "pattern_id": "ict_cisd_universal_model", "probability": 0.8, "outcome": True},
        {"date": "2026-08-21", "symbol": "CCC", "pattern_id": "ict_cisd_universal_model", "probability": 0.6, "outcome": False},
    ]

    coverage = build_pattern_coverage(ground, grader)
    family = coverage["per_family"][0]

    assert coverage["totals"] == {
        "ground_truth_labeled": 2,
        "grader_detected": 2,
        "true_positives": 1,
        "coverage_delta": 0.0,
    }
    assert family["family"] == "liquidity_delivery"
    assert family["precision"] == 0.5
    assert family["recall"] == 0.5
    assert coverage["cisd_hypothesis"]["n_outcomes"] == 2
    assert coverage["cisd_hypothesis"]["n_dates"] == 1
    assert coverage["cisd_hypothesis"]["brier"] == 0.2
    assert coverage["pattern_metrics_qualified"] is True
    assert coverage["execution_enabled"] is False
    assert coverage["can_submit_orders"] is False


def test_placeholder_coverage_is_labeled_unqualified() -> None:
    coverage = build_pattern_coverage(
        {"date": "2026-08-21", "metrics_qualified": False, "moves": []},
        [{"date": "2026-08-21", "symbol": "AAA", "pattern_id": "double_bottom"}],
    )

    assert coverage["status"] == "unqualified_move_denominator"
    assert coverage["metrics_qualified"] is False
    assert coverage["totals"]["coverage_delta"] is None


def test_pattern_grader_native_schema_counts_resolved_cisd_without_inventing_probability() -> None:
    coverage = build_pattern_coverage(
        {
            "date": "2026-08-21",
            "metrics_qualified": True,
            "pattern_annotation_qualified": True,
            "moves": [{"symbol": "MES", "pattern_ids": ["ict_cisd_universal_model"]}],
        },
        [{
            "ts_utc": "2026-08-21T14:32:15Z",
            "instrument": "MES",
            "pattern_id": "ict_cisd_universal_model",
            "family": "liquidity_delivery",
            "final_score": 88.0,
            "outcome_eod": {"realized_r": 1.42, "hit_t1": True, "stopped": False},
            "outcome_resolved_ts": "2026-08-21T20:35:00Z",
        }],
    )

    assert coverage["totals"]["true_positives"] == 1
    assert coverage["cisd_hypothesis"]["n_outcomes"] == 1
    assert coverage["cisd_hypothesis"]["brier"] is None
    assert coverage["cisd_hypothesis"]["scored_outcomes"] == 0


def test_pattern_coverage_keeps_same_day_trigger_events_distinct_and_joins_companion_outcomes() -> None:
    ground = {
        "date": "2026-08-21",
        "metrics_qualified": True,
        "pattern_annotation_qualified": True,
        "moves": [
            {"symbol": "SPY", "pattern_ids": ["ict_cisd_universal_model"], "timeframe": "5m", "trigger_bar_ts": "2026-08-21T14:00:00Z", "direction": "bullish"},
            {"symbol": "SPY", "pattern_ids": ["ict_cisd_universal_model"], "timeframe": "5m", "trigger_bar_ts": "2026-08-21T16:00:00Z", "direction": "bearish"},
        ],
    }
    grader = [
        {"detection_id": "one", "date": "2026-08-21", "symbol": "SPY", "pattern_id": "ict_cisd_universal_model", "trigger_timeframe": "5m", "trigger_bar_ts": "2026-08-21T14:00:00Z", "direction": "bullish"},
        {"detection_id": "two", "date": "2026-08-21", "symbol": "SPY", "pattern_id": "ict_cisd_universal_model", "trigger_timeframe": "5m", "trigger_bar_ts": "2026-08-21T16:00:00Z", "direction": "bearish"},
    ]
    outcomes = [
        {"detection_id": "one", "pattern_id": "ict_cisd_universal_model", "outcome_60m": {"realized_r": 2.0, "won": True}},
        {"detection_id": "two", "pattern_id": "ict_cisd_universal_model", "outcome_60m": {"realized_r": -1.0, "won": False}},
    ]

    coverage = build_pattern_coverage(ground, grader, outcome_rows=outcomes)

    assert coverage["totals"]["ground_truth_labeled"] == 2
    assert coverage["totals"]["grader_detected"] == 2
    assert coverage["totals"]["true_positives"] == 2
    assert coverage["totals"]["coverage_delta"] == 0.0
    assert coverage["cisd_hypothesis"]["n_outcomes"] == 2


def test_frozen_price_move_denominator_qualifies_opportunity_recall_not_pattern_family_recall() -> None:
    ground = {
        "date": "2026-08-21",
        "metrics_qualified": True,
        "pattern_annotation_qualified": False,
        "moves": [
            {
                "instrument": "SPY",
                "timeframe": "5m",
                "trigger_bar_ts": "2026-08-21T14:00:00Z",
                "direction": "bullish",
                "label": 1,
            },
            {
                "instrument": "QQQ",
                "timeframe": "5m",
                "trigger_bar_ts": "2026-08-21T15:00:00Z",
                "direction": "bearish",
                "label": -1,
            },
        ],
    }
    grader = [
        {
            "date": "2026-08-21",
            "symbol": "SPY",
            "pattern_id": "double_bottom",
            "trigger_timeframe": "5m",
            "trigger_bar_ts": "2026-08-21T14:00:00Z",
            "direction": "bullish",
        }
    ]

    coverage = build_pattern_coverage(ground, grader)

    assert coverage["status"] == "opportunity_measured_pattern_annotation_missing"
    assert coverage["metrics_qualified"] is True
    assert coverage["pattern_metrics_qualified"] is False
    assert coverage["opportunity_coverage"] == {
        "metrics_qualified": True,
        "ground_truth_moves": 2,
        "detected_events": 1,
        "true_positives": 1,
        "false_positives": 0,
        "false_negatives": 1,
        "precision": 1.0,
        "recall": 0.5,
        "coverage_delta": -0.5,
    }
    family = coverage["per_family"][0]
    assert family["precision"] is None
    assert family["recall"] is None


def test_family_outcome_quality_is_separate_from_independent_pattern_recall() -> None:
    coverage = build_pattern_coverage(
        {
            "date": "2026-08-21",
            "metrics_qualified": True,
            "pattern_annotation_qualified": False,
            "moves": [],
        },
        [
            {"detection_id": "a", "date": "2026-08-21", "symbol": "SPY", "pattern_id": "double_bottom"},
            {"detection_id": "b", "date": "2026-08-21", "symbol": "QQQ", "pattern_id": "double_bottom"},
        ],
        outcome_rows=[
            {"detection_id": "a", "outcome_r": 2.0, "won": True},
            {"detection_id": "b", "outcome_r": -1.0, "won": False},
        ],
    )

    quality = coverage["per_family"][0]["outcome_quality"]
    assert quality == {
        "resolved_outcomes": 2,
        "wins": 1,
        "observed_win_rate": 0.5,
        "average_r": 0.5,
    }
