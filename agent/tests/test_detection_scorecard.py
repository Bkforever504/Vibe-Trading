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
        _snapshot("2026-08-21T14:05:00Z", [("WIN", "bullish")]),
        _snapshot("2026-08-21T14:30:00Z", [("WIN", "bullish"), ("LATE", "bearish")]),
    ]
    report = build_scorecard(ground, history, k=1, regime="trend")
    partitions = {row["symbol"]: row["partition"] for row in report["moves"]}

    assert report["metrics"]["recall_at_k"] == 0.3333
    assert report["metrics"]["precision_at_k"] == 1.0
    assert partitions == {"WIN": "correct_entry", "LATE": "ranking_miss", "MISS": "discovery_miss"}
    assert report["per_regime"]["trend"] == report["metrics"]
    assert report["execution_enabled"] is False

    rolling = build_rolling([report])
    assert rolling["metrics"]["recall_at_10"] == 0.3333
    assert len(rolling["top_missed_moves"]) == 2


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
    assert coverage["execution_enabled"] is False
    assert coverage["can_submit_orders"] is False


def test_placeholder_coverage_is_labeled_unqualified() -> None:
    coverage = build_pattern_coverage(
        {"date": "2026-08-21", "metrics_qualified": False, "moves": []},
        [{"date": "2026-08-21", "symbol": "AAA", "pattern_id": "double_bottom"}],
    )

    assert coverage["status"] == "placeholder_pending_kenny_signoff"
    assert coverage["metrics_qualified"] is False
    assert coverage["totals"]["coverage_delta"] is None


def test_pattern_grader_native_schema_counts_resolved_cisd_without_inventing_probability() -> None:
    coverage = build_pattern_coverage(
        {
            "date": "2026-08-21",
            "metrics_qualified": True,
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
