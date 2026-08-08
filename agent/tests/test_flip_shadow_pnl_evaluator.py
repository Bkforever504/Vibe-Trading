from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import flip_shadow_pnl_evaluator as evaluator


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    last_index: dict[tuple[str, str], int] = {}
    first_index: dict[tuple[str, str], int] = {}
    for index, row in enumerate(rows):
        key = (str(row.get("date") or ""), str(row.get("option_symbol") or ""))
        first_index.setdefault(key, index)
        last_index[key] = index
    for index, row in enumerate(rows):
        key = (str(row.get("date") or ""), str(row.get("option_symbol") or ""))
        row.setdefault("schema_version", 2)
        row.setdefault("data_quality", "current_session_lifecycle")
        if index == first_index[key]:
            row.setdefault("event_type", "shadow_entry")
        elif index == last_index[key]:
            row.setdefault("event_type", "shadow_exit")
        else:
            row.setdefault("event_type", "shadow_mark")
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_explicit_lifecycle_exit_reason_replaces_last_observation_fallback() -> None:
    base = {
        "schema_version": 3,
        "date": "2026-07-14",
        "symbol": "SPY",
        "right": "CALL",
        "strategy": "0dte",
        "option_symbol": "SPY260714C00750000",
        "lifecycle_id": "episode-1",
        "contracts": 1,
    }
    evaluated = evaluator.evaluate_group([
        {**base, "scanned_at": "2026-07-14T17:30:00Z", "event_type": "shadow_entry", "entry_price_est": 1.0},
        {**base, "scanned_at": "2026-07-14T17:45:00Z", "event_type": "shadow_exit", "entry_price_est": 0.9, "mark_reason": "hard_close"},
    ])

    assert evaluated["logged_exit_reason"] == "hard_close"
    assert evaluated["simulated_exit_reason"] == "hard_close"


def test_executable_bid_ask_evidence_overrides_profitable_midpoint() -> None:
    base = {
        "schema_version": 3,
        "date": "2026-07-14",
        "symbol": "SPY",
        "right": "CALL",
        "strategy": "0dte",
        "option_symbol": "SPY260714C00750000",
        "lifecycle_id": "episode-spread",
        "contracts": 1,
    }
    evaluated = evaluator.evaluate_group([
        {
            **base,
            "scanned_at": "2026-07-14T17:30:00Z",
            "event_type": "shadow_entry",
            "entry_price_est": 1.0,
            "selection_bid": 0.95,
            "selection_ask": 1.05,
        },
        {
            **base,
            "scanned_at": "2026-07-14T17:45:00Z",
            "event_type": "shadow_exit",
            "entry_price_est": 1.05,
            "selection_bid": 1.0,
            "selection_ask": 1.1,
            "mark_reason": "hard_close",
        },
    ])

    assert evaluated["simulated_exit_return_pct"] == 5.0
    assert evaluated["cost_adjusted_exit_return_pct"] == -4.76
    assert evaluated["evidence_exit_return_pct"] == -4.76
    assert evaluated["evidence_price_basis"] == "entry_ask_exit_bid"
    assert evaluated["status"] == "loser"


def test_first_post_entry_directional_conflict_is_shadow_exit_counterfactual() -> None:
    base = {
        "schema_version": 3, "data_quality": "current_session_lifecycle",
        "date": "2026-07-16", "symbol": "SPY", "right": "CALL", "strategy": "0dte",
        "option_symbol": "SPY260716C00750000", "lifecycle_id": "conflict-1", "contracts": 1,
        "execution_mode": "shadow_only", "selection_ask": 1.05,
    }
    evaluated = evaluator.evaluate_group([
        {**base, "scanned_at": "2026-07-16T15:00:00Z", "event_type": "shadow_entry",
         "entry_price_est": 1.0, "selection_bid": 0.95,
         "market_force_snapshot_status": "current", "market_force_classification": "bullish_confirmation"},
        {**base, "scanned_at": "2026-07-16T15:15:00Z", "event_type": "shadow_mark",
         "entry_price_est": 0.9, "selection_bid": 0.88,
         "market_force_snapshot_status": "current", "market_force_classification": "bullish_confirmation"},
        {**base, "scanned_at": "2026-07-16T15:30:00Z", "event_type": "shadow_mark",
         "entry_price_est": 0.82, "selection_bid": 0.80,
         "market_force_snapshot_status": "current", "market_force_classification": "bearish_confirmation",
         "market_force_timestamp": "2026-07-16T15:29:00Z"},
        {**base, "scanned_at": "2026-07-16T15:45:00Z", "event_type": "shadow_exit",
         "entry_price_est": 0.70, "selection_bid": 0.68, "mark_reason": "stop_30_hit",
         "market_force_snapshot_status": "current", "market_force_classification": "bearish_confirmation"},
    ])

    assert evaluated["directional_conflict_observed"] is True
    assert evaluated["directional_conflict_classification"] == "bearish_confirmation"
    assert evaluated["directional_conflict_seen_at"] == "2026-07-16T15:30:00Z"
    assert evaluated["directional_conflict_exit_return_pct"] == -23.81
    assert evaluated["directional_conflict_vs_baseline_return_delta_pct"] > 0
    assert evaluated["directional_conflict_min_observations_for_review"] == 10


def test_directional_conflict_research_requires_ten_completed_observations(tmp_path: Path) -> None:
    log_path = tmp_path / "conflicts.jsonl"
    rows = []
    for episode in range(10):
        lifecycle = f"conflict-{episode}"
        base = {
            "schema_version": 3, "data_quality": "current_session_lifecycle",
            "date": "2026-07-16", "symbol": "SPY", "right": "PUT", "strategy": "0dte",
            "option_symbol": f"SPY260716P0075{episode:03d}", "lifecycle_id": lifecycle,
            "contracts": 1, "execution_mode": "shadow_only",
        }
        rows.extend([
            {**base, "scanned_at": f"2026-07-16T15:{episode:02d}:00Z", "event_type": "shadow_entry",
             "entry_price_est": 1.0, "market_force_snapshot_status": "current",
             "market_force_classification": "bearish_confirmation"},
            {**base, "scanned_at": f"2026-07-16T16:{episode:02d}:00Z", "event_type": "shadow_exit",
             "entry_price_est": 0.8, "mark_reason": "hard_close", "market_force_snapshot_status": "current",
             "market_force_classification": "bullish_confirmation"},
        ])
    _write_jsonl(log_path, rows)

    research = evaluator.build_report(log_path=log_path)["directional_conflict_exit_research"]

    assert research["observation_count"] == 10
    assert research["minimum_observations_for_review"] == 10
    assert research["promotion_review_ready"] is True


def test_build_report_scores_shadow_candidate_returns(tmp_path: Path) -> None:
    log_path = tmp_path / "flip_shadow_candidates_log.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "provider": "flip_shadow_candidates",
                "date": "2026-07-02",
                "scanned_at": "2026-07-02T14:45:04Z",
                "symbol": "TSLA",
                "right": "PUT",
                "option_symbol": "TSLA260702P00397500",
                "entry_price_est": 0.19,
                "spread_cents": 15,
                "contracts": 5,
                "execution_mode": "shadow_only",
            },
            {
                "provider": "flip_shadow_candidates",
                "date": "2026-07-02",
                "scanned_at": "2026-07-02T15:15:03Z",
                "symbol": "TSLA",
                "right": "PUT",
                "option_symbol": "TSLA260702P00397500",
                "entry_price_est": 3.25,
                "spread_cents": 13,
                "contracts": 5,
                "execution_mode": "shadow_only",
            },
            {
                "provider": "flip_shadow_candidates",
                "date": "2026-07-02",
                "scanned_at": "2026-07-02T15:30:04Z",
                "symbol": "IWM",
                "right": "PUT",
                "option_symbol": "IWM260702P00297000",
                "entry_price_est": 0.34,
                "spread_cents": 1,
                "contracts": 5,
                "execution_mode": "shadow_only",
            },
            {
                "provider": "flip_shadow_candidates",
                "date": "2026-07-02",
                "scanned_at": "2026-07-02T16:45:03Z",
                "symbol": "IWM",
                "right": "PUT",
                "option_symbol": "IWM260702P00297000",
                "entry_price_est": 0.42,
                "spread_cents": 3,
                "contracts": 5,
                "execution_mode": "shadow_only",
            },
        ],
    )

    report = evaluator.build_report(log_path=log_path, day="2026-07-02")

    assert report["execution_enabled"] is False
    assert report["sample_count"] == 2
    tsla = report["top_trades"][0]
    assert tsla["symbol"] == "TSLA"
    assert tsla["right"] == "PUT"
    assert tsla["entry_price"] == 0.19
    assert tsla["best_price"] == 3.25
    assert tsla["return_pct"] == 1610.53
    assert tsla["hypothetical_pnl"] == 1530.0
    assert tsla["simulated_exit_reason"] == "target_75_hit"
    assert tsla["simulated_exit_return_pct"] == 1610.53
    assert tsla["giveback_pct"] == 0.0
    assert tsla["capture_efficiency"] == 1.0
    assert report["by_symbol"]["TSLA"]["sample_count"] == 1
    assert report["by_symbol"]["TSLA"]["win_rate"] == 1.0
    assert report["by_symbol"]["TSLA"]["expectancy_return_pct"] == 1610.53


def test_research_strategies_do_not_inflate_primary_symbol_promotion(tmp_path: Path) -> None:
    log_path = tmp_path / "flip_shadow_candidates_log.jsonl"
    common = {
        "schema_version": 3,
        "data_quality": "current_session_lifecycle",
        "execution_mode": "shadow_only",
        "date": "2026-07-16",
        "symbol": "SPY",
        "right": "CALL",
        "contracts": 1,
    }
    rows = [
        {**common, "lifecycle_id": "primary", "strategy": "0dte", "option_symbol": "SPY-PRIMARY",
         "event_type": "shadow_entry", "scanned_at": "2026-07-16T15:00:00Z", "entry_price_est": 1.0,
         "selection_ask": 1.0, "selection_bid": 1.0},
        {**common, "lifecycle_id": "primary", "strategy": "0dte", "option_symbol": "SPY-PRIMARY",
         "event_type": "shadow_exit", "scanned_at": "2026-07-16T16:00:00Z", "entry_price_est": 0.7,
         "selection_ask": 0.7, "selection_bid": 0.7},
        {**common, "lifecycle_id": "research", "strategy": "orb_15m_retest", "option_symbol": "SPY-RESEARCH",
         "event_type": "shadow_entry", "scanned_at": "2026-07-16T15:30:00Z", "entry_price_est": 1.0,
         "selection_ask": 1.0, "selection_bid": 1.0},
        {**common, "lifecycle_id": "research", "strategy": "orb_15m_retest", "option_symbol": "SPY-RESEARCH",
         "event_type": "shadow_exit", "scanned_at": "2026-07-16T16:30:00Z", "entry_price_est": 2.0,
         "selection_ask": 2.0, "selection_bid": 2.0},
    ]
    _write_jsonl(log_path, rows)

    report = evaluator.build_report(log_path=log_path)

    assert report["sample_count"] == 1
    assert report["completed_count"] == 1
    assert report["research_sample_count"] == 1
    assert report["research_completed_count"] == 1
    assert report["by_symbol"]["SPY"]["expectancy_return_pct"] == -30.0
    assert report["top_trades"][0]["strategy"] == "0dte"
    assert report["research_top_trades"][0]["strategy"] == "orb_15m_retest"
    challenger = report["research_strategy_challengers"][0]
    assert challenger["required_completed_count"] == 50
    assert challenger["promotion_review_ready"] is False
    assert challenger["automatic_live_promotion"] is False


def test_build_report_marks_single_observations_as_open_or_insufficient(tmp_path: Path) -> None:
    log_path = tmp_path / "flip_shadow_candidates_log.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "date": "2026-07-02",
                "scanned_at": "2026-07-02T17:00:00Z",
                "symbol": "NVDA",
                "right": "PUT",
                "option_symbol": "NVDA260702P00192500",
                "entry_price_est": 0.36,
                "contracts": 5,
            }
        ],
    )

    report = evaluator.build_report(log_path=log_path, day="2026-07-02")

    assert report["sample_count"] == 1
    assert report["top_trades"][0]["status"] == "insufficient_followup"
    assert report["top_trades"][0]["return_pct"] == 0.0


def test_build_report_simulates_ratcheted_profit_capture(tmp_path: Path) -> None:
    log_path = tmp_path / "flip_shadow_candidates_log.jsonl"
    _write_jsonl(
        log_path,
        [
            {
                "date": "2026-07-06",
                "scanned_at": "2026-07-06T15:00:00Z",
                "symbol": "SPY",
                "right": "CALL",
                "option_symbol": "SPY260706C00750000",
                "entry_price_est": 1.00,
                "contracts": 5,
                "execution_mode": "shadow_only",
            },
            {
                "date": "2026-07-06",
                "scanned_at": "2026-07-06T15:05:00Z",
                "symbol": "SPY",
                "right": "CALL",
                "option_symbol": "SPY260706C00750000",
                "entry_price_est": 1.66,
                "contracts": 5,
                "execution_mode": "shadow_only",
            },
            {
                "date": "2026-07-06",
                "scanned_at": "2026-07-06T15:10:00Z",
                "symbol": "SPY",
                "right": "CALL",
                "option_symbol": "SPY260706C00750000",
                "entry_price_est": 1.50,
                "contracts": 5,
                "execution_mode": "shadow_only",
            },
        ],
    )

    report = evaluator.build_report(log_path=log_path, day="2026-07-06")

    trade = report["top_trades"][0]
    assert trade["return_pct"] == 66.0
    assert trade["simulated_exit_return_pct"] == 50.0
    assert trade["simulated_exit_reason"] == "ratchet_lock_56.0"
    assert trade["giveback_pct"] == 16.0
    assert trade["capture_efficiency"] == 0.758
    assert report["avg_giveback_pct"] == 16.0


def test_build_report_stops_shadow_loser_and_requires_positive_expectancy_for_promotion(tmp_path: Path) -> None:
    log_path = tmp_path / "flip_shadow_candidates_log.jsonl"
    rows = []
    for day in range(1, 31):
        date = f"2026-07-{day:02d}"
        option = f"SPY2607{day:02d}C00750000"
        rows.extend(
            [
                {
                    "date": date,
                    "scanned_at": f"{date}T15:00:00Z",
                    "symbol": "SPY",
                    "right": "CALL",
                    "option_symbol": option,
                    "entry_price_est": 1.00,
                    "contracts": 1,
                    "execution_mode": "shadow_only",
                },
                {
                    "date": date,
                    "scanned_at": f"{date}T15:05:00Z",
                    "symbol": "SPY",
                    "right": "CALL",
                    "option_symbol": option,
                    "entry_price_est": 0.70 if day % 3 == 0 else 1.20,
                    "contracts": 1,
                    "execution_mode": "shadow_only",
                },
            ]
        )
    _write_jsonl(log_path, rows)

    report = evaluator.build_report(log_path=log_path)

    spy = report["by_symbol"]["SPY"]
    assert spy["completed_count"] == 30
    assert spy["loser_count"] == 10
    assert spy["win_rate"] == 0.667
    assert spy["avg_win_return_pct"] == 20.0
    assert spy["avg_loss_return_pct"] == 30.0
    assert spy["expectancy_return_pct"] == 3.33
    assert spy["out_of_sample_count"] == 6
    assert spy["out_of_sample_expectancy_return_pct"] == 3.33
    assert spy["out_of_sample_positive"] is True
    assert spy["promotion_eligible"] is True


def test_build_report_blocks_positive_history_with_negative_holdout(tmp_path: Path) -> None:
    log_path = tmp_path / "flip_shadow_candidates_log.jsonl"
    rows = []
    for day in range(1, 31):
        trade_date = f"2026-09-{day:02d}"
        option = f"SPY2609{day:02d}C00750000"
        rows.extend([
            {"date": trade_date, "scanned_at": f"{trade_date}T15:00:00Z", "symbol": "SPY", "right": "CALL", "option_symbol": option, "entry_price_est": 1.0},
            {"date": trade_date, "scanned_at": f"{trade_date}T15:05:00Z", "symbol": "SPY", "right": "CALL", "option_symbol": option, "entry_price_est": 1.5 if day <= 24 else 0.7},
        ])
    _write_jsonl(log_path, rows)

    spy = evaluator.build_report(log_path=log_path)["by_symbol"]["SPY"]

    assert spy["expectancy_return_pct"] > 0
    assert spy["out_of_sample_expectancy_return_pct"] == -30.0
    assert spy["out_of_sample_positive"] is False
    assert spy["promotion_eligible"] is False


def test_build_report_blocks_high_win_rate_negative_expectancy_symbol(tmp_path: Path) -> None:
    log_path = tmp_path / "flip_shadow_candidates_log.jsonl"
    rows = []
    for day in range(1, 31):
        date = f"2026-08-{day:02d}"
        option = f"QQQ2608{day:02d}C00600000"
        rows.extend(
            [
                {
                    "date": date,
                    "scanned_at": f"{date}T15:00:00Z",
                    "symbol": "QQQ",
                    "right": "CALL",
                    "option_symbol": option,
                    "entry_price_est": 1.00,
                    "contracts": 1,
                    "execution_mode": "shadow_only",
                },
                {
                    "date": date,
                    "scanned_at": f"{date}T15:05:00Z",
                    "symbol": "QQQ",
                    "right": "CALL",
                    "option_symbol": option,
                    "entry_price_est": 1.10 if day <= 20 else 0.60,
                    "contracts": 1,
                    "execution_mode": "shadow_only",
                },
            ]
        )
    _write_jsonl(log_path, rows)

    report = evaluator.build_report(log_path=log_path)

    qqq = report["by_symbol"]["QQQ"]
    assert qqq["win_rate"] == 0.667
    assert qqq["avg_win_return_pct"] == 10.0
    assert qqq["avg_loss_return_pct"] == 40.0
    assert qqq["expectancy_return_pct"] == -6.67
    assert qqq["promotion_eligible"] is False


def test_accelerated_schema_requires_volume_days_and_large_holdout(tmp_path: Path) -> None:
    log_path = tmp_path / "accelerated.jsonl"
    rows = []
    for day in range(1, 11):
        trade_date = f"2026-10-{day:02d}"
        for episode in range(10):
            lifecycle_id = f"{trade_date}|SPY|CALL|0dte|{episode}"
            option = f"SPY2610{day:02d}C00750000"
            rows.extend([
                {
                    "schema_version": 3,
                    "data_quality": "current_session_lifecycle",
                    "date": trade_date,
                    "scanned_at": f"{trade_date}T15:{episode:02d}:00Z",
                    "symbol": "SPY",
                    "right": "CALL",
                    "strategy": "0dte",
                    "option_symbol": option,
                    "lifecycle_id": lifecycle_id,
                        "episode_bucket_et": f"10:{episode:02d}",
                        "entry_price_est": 1.0,
                        "selection_bid": 0.99,
                        "selection_ask": 1.01,
                        "event_type": "shadow_entry",
                    "execution_mode": "shadow_only",
                },
                {
                    "schema_version": 3,
                    "data_quality": "current_session_lifecycle",
                    "date": trade_date,
                    "scanned_at": f"{trade_date}T16:{episode:02d}:00Z",
                    "symbol": "SPY",
                    "right": "CALL",
                    "strategy": "0dte",
                    "option_symbol": option,
                    "lifecycle_id": lifecycle_id,
                        "episode_bucket_et": f"10:{episode:02d}",
                        "entry_price_est": 1.2,
                        "selection_bid": 1.19,
                        "selection_ask": 1.21,
                        "event_type": "shadow_exit",
                    "execution_mode": "shadow_only",
                },
            ])
    _write_jsonl(log_path, rows)

    report = evaluator.build_report(log_path=log_path)
    spy = report["by_symbol"]["SPY"]

    assert report["accelerated_completed_count"] == 100
    assert spy["evidence_path"] == "accelerated_clustered_forward"
    assert spy["required_completed_count"] == 100
    assert spy["required_trading_day_count"] == 10
    assert spy["required_out_of_sample_count"] == 30
    assert spy["out_of_sample_count"] == 30
    assert spy["executable_quote_coverage_rate"] == 1.0
    assert spy["promotion_eligible"] is True
