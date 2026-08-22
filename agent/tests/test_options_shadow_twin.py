from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.options_confluence import (
    build_confluence_analysis,
    candidate_dimensions,
    dte_bucket,
    entry_time_bucket,
    latest_iv_rank_context,
)
from scripts.options_shadow_twin import (
    build_report,
    executable_close_debit,
    executable_entry_credit,
    iron_fly_structure_metrics,
    mark_open_candidates,
    midpoint_close_debit,
    read_records,
    record_candidate,
    record_decision,
    wilson_interval,
    _close_cost_quality,
    _deflated_sharpe,
    _drawdown_stats,
    _loss_asymmetry_stats,
)


def _meta() -> dict:
    return {
        "strategy": "put_spread",
        "underlying": "SPY",
        "expiry": "2026-08-21",
        "qty": 1,
        "net_credit": 1.10,
        "max_risk_per_contract": 390.0,
        "profit_close_pct": 0.5,
        "stop_loss_pct": -1.0,
        "candidate_confidence": {"score": 8},
        "leg_market_snapshots": [
            {
                "symbol": "SPY260821P00600000",
                "expiry": "2026-08-21",
                "strike": 600,
                "right": "P",
                "delta": -0.25,
                "bid": 2.00,
                "ask": 2.10,
                "mid": 2.05,
            },
            {
                "symbol": "SPY260821P00595000",
                "expiry": "2026-08-21",
                "strike": 595,
                "right": "P",
                "delta": -0.18,
                "bid": 0.90,
                "ask": 1.00,
                "mid": 0.95,
            },
        ],
    }


def _payload() -> list[dict]:
    return [
        {"symbol": "SPY260821P00600000", "side": "sell", "ratio_qty": "1"},
        {"symbol": "SPY260821P00595000", "side": "buy", "ratio_qty": "1"},
    ]


def test_call_spread_candidate_is_supported(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    meta = _meta()
    meta["strategy"] = "call_spread"

    candidate_id = record_candidate(meta, _payload(), path=path)

    assert candidate_id
    assert read_records(path)[0]["strategy"] == "call_spread"


def test_iron_fly_candidate_derives_posted_structure_risk_without_execution(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    expiry = "2026-08-11"
    snapshots = [
        {"symbol": "SPX260811P07750000", "expiry": expiry, "strike": 7750, "right": "P", "bid": 10.00, "ask": 10.20},
        {"symbol": "SPX260811C07750000", "expiry": expiry, "strike": 7750, "right": "C", "bid": 9.75, "ask": 9.95},
        {"symbol": "SPX260811P07735000", "expiry": expiry, "strike": 7735, "right": "P", "bid": 5.80, "ask": 6.00},
        {"symbol": "SPX260811C07765000", "expiry": expiry, "strike": 7765, "right": "C", "bid": 5.80, "ask": 6.00},
    ]
    payload = [
        {"symbol": snapshots[0]["symbol"], "side": "sell"},
        {"symbol": snapshots[1]["symbol"], "side": "sell"},
        {"symbol": snapshots[2]["symbol"], "side": "buy"},
        {"symbol": snapshots[3]["symbol"], "side": "buy"},
    ]
    meta = {
        "strategy": "iron_fly",
        "underlying": "SPX",
        "expiry": expiry,
        "qty": 1,
        "leg_market_snapshots": snapshots,
        "strategy_context": {
            "hypothesis": "late_day_pin_decay",
            "gex_authority": "unqualified_proxy",
        },
    }

    candidate_id = record_candidate(meta, payload, path=path)

    assert candidate_id
    row = read_records(path)[0]
    metrics = row["structure_metrics"]
    assert metrics == iron_fly_structure_metrics(row["legs"])
    assert metrics["executable_entry_credit"] == pytest.approx(7.75)
    assert metrics["max_profit_per_contract"] == pytest.approx(775.0)
    assert metrics["max_risk_per_contract"] == pytest.approx(725.0)
    assert metrics["lower_breakeven_at_expiry"] == pytest.approx(7742.25)
    assert metrics["upper_breakeven_at_expiry"] == pytest.approx(7757.75)
    assert row["strategy_context"]["gex_authority"] == "unqualified_proxy"
    assert row["execution_enabled"] is False
    assert row["can_submit_orders"] is False


def test_iron_fly_rejects_mismatched_body_or_asymmetric_wings() -> None:
    legs = [
        {"side": "sell", "right": "P", "strike": 100, "expiry": "2026-08-11", "bid": 2.0, "ask": 2.1},
        {"side": "sell", "right": "C", "strike": 101, "expiry": "2026-08-11", "bid": 2.0, "ask": 2.1},
        {"side": "buy", "right": "P", "strike": 95, "expiry": "2026-08-11", "bid": 0.4, "ask": 0.5},
        {"side": "buy", "right": "C", "strike": 106, "expiry": "2026-08-11", "bid": 0.4, "ask": 0.5},
    ]
    assert iron_fly_structure_metrics(legs) is None


def test_executable_credit_and_close_debit_use_adverse_sides() -> None:
    legs = [
        {"side": "sell", "ratio_qty": 1, "bid": 2.0, "ask": 2.1},
        {"side": "buy", "ratio_qty": 1, "bid": 0.9, "ask": 1.0},
    ]
    assert executable_entry_credit(legs) == pytest.approx(1.0)
    assert executable_close_debit(legs) == pytest.approx(1.2)


def test_incomplete_or_crossed_quotes_are_quarantined() -> None:
    missing = [{"side": "sell", "ratio_qty": 1, "bid": None, "ask": 2.1}]
    crossed = [{"side": "sell", "ratio_qty": 1, "bid": 2.2, "ask": 2.1}]
    assert executable_entry_credit(missing) is None
    assert executable_close_debit(crossed) is None


def test_candidate_is_append_only_and_deduped_within_five_minutes(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    now = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)
    first = record_candidate(_meta(), _payload(), path=path, now=now)
    second = record_candidate(_meta(), _payload(), path=path, now=now + timedelta(minutes=4))
    third = record_candidate(_meta(), _payload(), path=path, now=now + timedelta(minutes=6))
    rows = read_records(path)
    assert first == second
    assert third != first
    assert [row["type"] for row in rows] == ["candidate", "candidate"]
    assert rows[0]["executable_entry_credit"] == pytest.approx(1.0)


def test_candidate_preserves_frozen_volatility_edge_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    meta = _meta()
    meta["volatility_edge"] = {
        "method_version": "maturity_matched_vol_premium_v1",
        "atm_iv_annualized_pct": 24.0,
        "rv_forecast_annualized_pct": 18.0,
        "net_vol_premium_ex_event_pct": 5.5,
        "gate_changed": False,
    }

    record_candidate(meta, _payload(), path=path)

    stored = read_records(path)[0]["volatility_edge"]
    assert stored["method_version"] == "maturity_matched_vol_premium_v1"
    assert stored["atm_iv_annualized_pct"] == 24.0
    assert stored["gate_changed"] is False


def test_report_quantifies_midpoint_to_executable_entry_friction(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    now = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)
    record_candidate(_meta(), _payload(), path=path, now=now)

    built = build_report(read_records(path), now=now + timedelta(minutes=1))
    quality = built["execution_cost_quality"]

    assert quality["status"] == "watch_execution_friction"
    assert quality["paired_coverage"] == pytest.approx(1.0)
    assert quality["avg_entry_edge_loss_credit"] == pytest.approx(0.1)
    assert quality["avg_entry_edge_loss_pct_of_mid"] == pytest.approx(0.0909)
    assert quality["benchmark"] == "arrival_mid_credit_vs_sell_bid_buy_ask_executable_entry_credit"
    assert quality["authority"] == "shadow_governance_only"


def test_mark_resolves_target_with_conservative_group_debit(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    now = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)
    candidate_id = record_candidate(_meta(), _payload(), path=path, now=now)
    record_decision(candidate_id, "blocked_strict_caution", path=path, now=now)
    quotes = {
        "SPY260821P00600000": {"bid": 0.60, "ask": 0.70},
        "SPY260821P00595000": {"bid": 0.30, "ask": 0.40},
    }

    def factory(_candidate_id: str, _underlying: str):
        def fetch(symbol: str) -> dict:
            return {
                "quote": {**quotes[symbol], "quote_timestamp": "2026-07-25T15:30:00Z"},
                "provenance": {"status": "ok"},
            }

        return fetch

    stats = mark_open_candidates(
        path=path,
        quote_fetcher_factory=factory,
        now=now + timedelta(hours=1),
    )
    rows = read_records(path)
    outcome = next(row for row in rows if row["type"] == "outcome")
    assert stats["resolved"] == 1
    assert outcome["reason"] == "profit_target_50pct_credit"
    assert outcome["closing_debit"] == pytest.approx(0.4)
    assert outcome["pnl_before_fees"] == pytest.approx(60.0)


def test_mark_uses_candidate_stop_loss_policy(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    now = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)
    meta = _meta()
    meta["stop_loss_pct"] = -2.0
    record_candidate(meta, _payload(), path=path, now=now)

    def quotes_for(short_ask: float, long_bid: float):
        quotes = {
            "SPY260821P00600000": {"bid": short_ask - 0.10, "ask": short_ask},
            "SPY260821P00595000": {"bid": long_bid, "ask": long_bid + 0.10},
        }

        def factory(_candidate_id: str, _underlying: str):
            return lambda symbol: {
                "quote": {**quotes[symbol], "quote_timestamp": "2026-07-25T16:00:00Z"},
                "provenance": {"status": "ok"},
            }

        return factory

    not_stopped = mark_open_candidates(
        path=path,
        quote_fetcher_factory=quotes_for(3.00, 0.50),
        now=now + timedelta(hours=1),
    )
    stopped = mark_open_candidates(
        path=path,
        quote_fetcher_factory=quotes_for(3.60, 0.50),
        now=now + timedelta(hours=2),
    )

    assert not_stopped["resolved"] == 0
    assert stopped["resolved"] == 1
    outcome = next(row for row in read_records(path) if row["type"] == "outcome")
    assert outcome["reason"] == "stop_200pct_credit"


def test_time_exit_only_policy_does_not_invent_credit_stop(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    now = datetime(2026, 7, 25, 15, 0, tzinfo=timezone.utc)
    meta = _meta()
    meta["stop_policy"] = "none_time_exit_only"
    meta["evaluation_end_at"] = (now + timedelta(hours=2)).isoformat()
    record_candidate(meta, _payload(), path=path, now=now)

    def factory(_candidate_id: str, _underlying: str):
        return lambda symbol: {
            "quote": {
                "bid": 3.9 if symbol.endswith("600000") else 0.4,
                "ask": 4.0 if symbol.endswith("600000") else 0.5,
                "quote_timestamp": "2026-07-25T16:00:00Z",
            },
            "provenance": {"status": "ok"},
        }

    before_time_exit = mark_open_candidates(
        path=path,
        quote_fetcher_factory=factory,
        now=now + timedelta(hours=1),
    )
    at_time_exit = mark_open_candidates(
        path=path,
        quote_fetcher_factory=factory,
        now=now + timedelta(hours=2),
    )

    assert before_time_exit["resolved"] == 0
    assert at_time_exit["resolved"] == 1
    outcome = next(row for row in read_records(path) if row["type"] == "outcome")
    assert outcome["reason"] == "expiration_hard_close"


def test_wilson_interval_does_not_report_false_certainty() -> None:
    lower, upper = wilson_interval(3, 3)
    assert lower is not None and lower < 0.5
    assert upper == pytest.approx(1.0)


def test_negative_expectancy_hard_caps_confidence_at_three() -> None:
    records: list[dict] = []
    start = datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)
    for index in range(30):
        candidate_id = f"candidate-{index}"
        records.extend(
            [
                {
                    "type": "candidate",
                    "candidate_id": candidate_id,
                    "created_at": (start + timedelta(days=index)).isoformat(),
                    "entry_quote_complete": True,
                    "candidate_confidence": {"score": 9 if index % 2 == 0 else 1},
                },
                {
                    "type": "mark",
                    "candidate_id": candidate_id,
                    "quote_complete": True,
                },
                {
                    "type": "outcome",
                    "candidate_id": candidate_id,
                    "pnl_before_fees": 10.0 if index % 3 == 0 else -20.0,
                    "win": index % 3 == 0,
                },
            ]
        )
    report = build_report(records, now=start + timedelta(days=40))
    assert report["performance"]["expectancy_before_fees"] < 0
    assert report["earned_confidence"]["evidence_cap"] == 3.0
    assert report["earned_confidence"]["score"] <= 3.0
    assert report["promotion_eligible"] is False


def test_loss_asymmetry_exposes_high_win_rate_below_payoff_hurdle() -> None:
    result = _loss_asymmetry_stats([10.0] * 11 + [-100.0] * 5)

    assert result["observed_win_rate"] == pytest.approx(0.6875)
    assert result["required_win_rate_to_break_even"] == pytest.approx(0.9091)
    assert result["win_rate_margin_over_break_even"] < 0
    assert result["status"] == "win_rate_below_payoff_hurdle"


def test_records_are_valid_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    record_candidate(_meta(), _payload(), path=path)
    for line in path.read_text(encoding="utf-8").splitlines():
        assert isinstance(json.loads(line), dict)


def test_candidate_separates_setup_score_from_probability_and_versions_policy(tmp_path: Path) -> None:
    path = tmp_path / "shadow.jsonl"
    meta = _meta()
    meta["candidate_confidence"] = {"score": 8, "probability": 0.64}
    record_candidate(meta, _payload(), path=path)
    row = read_records(path)[0]
    assert row["setup_score"] == 8
    assert row["raw_probability"] == pytest.approx(0.64)
    assert row["calibration_cohort"].startswith("options-policy-")
    assert row["outcome_definition"] == "profit_target_before_stop_or_expiry_executable_quotes"


def test_options_calibration_never_converts_setup_score_to_probability() -> None:
    records = [
        {"type": "candidate", "candidate_id": "score-only", "created_at": "2026-01-01T15:00:00Z", "candidate_confidence": {"score": 9}},
        {"type": "outcome", "candidate_id": "score-only", "pnl_before_fees": 10.0, "win": True},
        {"type": "candidate", "candidate_id": "probability", "created_at": "2026-01-02T15:00:00Z", "raw_probability": 0.7, "candidate_confidence": {"score": 5}},
        {"type": "outcome", "candidate_id": "probability", "pnl_before_fees": -5.0, "win": False},
    ]
    report = build_report(records)
    assert report["calibration"]["count"] == 1
    assert report["calibration"]["legacy_setup_score_diagnostic"]["sample_count"] == 2
    assert report["calibration"]["probability_source_policy"] == "explicit_frozen_raw_probability_only"


def test_decision_funnel_counts_missing_and_submission_failures() -> None:
    records = [
        {"type": "candidate", "candidate_id": "blocked", "strategy": "put_spread"},
        {"type": "candidate", "candidate_id": "failed", "strategy": "put_spread"},
        {"type": "candidate", "candidate_id": "missing", "strategy": "call_spread"},
        {"type": "decision", "candidate_id": "blocked", "decision": "blocked_execution_guard"},
        {"type": "decision", "candidate_id": "failed", "decision": "submission_failed"},
    ]
    funnel = build_report(records)["decision_funnel"]
    assert funnel["decision_coverage"] == pytest.approx(2 / 3, abs=0.0001)
    assert funnel["blocked_count"] == 1
    assert funnel["no_fill_or_submission_failure_count"] == 1
    assert funnel["missing_decision_count"] == 1


# --- Round-trip TCA: close cost quality ---

def test_midpoint_close_debit_uses_average_of_bid_ask() -> None:
    legs = [
        {"side": "sell", "ratio_qty": 1, "bid": 1.00, "ask": 1.20},
        {"side": "buy", "ratio_qty": 1, "bid": 0.40, "ask": 0.60},
    ]
    # sell mid = 1.10, buy mid = 0.50 → close debit = 1.10 - 0.50 = 0.60
    assert midpoint_close_debit(legs) == pytest.approx(0.60)


def test_midpoint_close_debit_is_less_than_executable_close_debit() -> None:
    legs = [
        {"side": "sell", "ratio_qty": 1, "bid": 2.00, "ask": 2.20},
        {"side": "buy", "ratio_qty": 1, "bid": 0.80, "ask": 1.00},
    ]
    mid = midpoint_close_debit(legs)
    executable = executable_close_debit(legs)
    assert mid is not None and executable is not None
    assert mid < executable


def test_close_cost_quality_measures_exit_friction() -> None:
    mark_rows = [
        {
            "executable_close_debit": 0.70,
            "legs": [
                {"side": "sell", "ratio_qty": 1, "bid": 0.50, "ask": 0.70},
                {"side": "buy", "ratio_qty": 1, "bid": 0.10, "ask": 0.30},
            ],
        }
    ]
    result = _close_cost_quality(mark_rows)
    # mid sell=0.60, mid buy=0.20 → mid_close=0.40; executable=0.70; friction=0.30
    assert result["paired_count"] == 1
    assert result["avg_close_friction_credit"] == pytest.approx(0.30)
    assert result["avg_close_friction_pct_of_mid"] == pytest.approx(0.75)
    assert result["authority"] == "shadow_governance_only"


def test_close_cost_quality_empty_marks_returns_no_quotes_status() -> None:
    assert _close_cost_quality([])["status"] == "no_complete_close_quotes"


# --- Deflated Sharpe Ratio ---

def test_deflated_sharpe_insufficient_n() -> None:
    result = _deflated_sharpe([10.0, -5.0, 8.0])
    assert result["status"] == "insufficient_n"
    assert result["dsr"] is None


def test_deflated_sharpe_positive_edge_gives_dsr_above_half() -> None:
    pnls = [15.0] * 20 + [-5.0] * 5  # clearly positive expectancy
    result = _deflated_sharpe(pnls)
    assert result["dsr"] is not None and result["dsr"] > 0.5
    assert result["sr_per_trade"] is not None and result["sr_per_trade"] > 0


def test_deflated_sharpe_negative_edge_gives_dsr_below_half() -> None:
    pnls = [-15.0] * 20 + [5.0] * 5
    result = _deflated_sharpe(pnls)
    assert result["dsr"] is not None and result["dsr"] < 0.5


def test_deflated_sharpe_in_report_when_outcomes_present(tmp_path: Path) -> None:
    records: list[dict] = []
    start = datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc)
    for i in range(10):
        cid = f"c-{i}"
        records += [
            {"type": "candidate", "candidate_id": cid, "created_at": (start + timedelta(days=i)).isoformat(),
             "entry_quote_complete": True, "candidate_confidence": {}},
            {"type": "mark", "candidate_id": cid, "quote_complete": True},
            {"type": "outcome", "candidate_id": cid, "pnl_before_fees": 20.0 if i % 2 == 0 else -5.0, "win": i % 2 == 0},
        ]
    report = build_report(records, now=start + timedelta(days=15))
    dsr = report["deflated_sharpe"]
    assert "dsr" in dsr
    assert "sr_per_trade" in dsr


# --- Drawdown stats ---

def test_drawdown_stats_counts_max_consecutive_losses() -> None:
    pnls = [10.0, -5.0, -5.0, -5.0, 10.0, -5.0]
    result = _drawdown_stats(pnls)
    assert result["max_consecutive_losses"] == 3
    assert result["current_consecutive_losses"] == 1


def test_drawdown_stats_max_drawdown_measures_peak_to_trough() -> None:
    pnls = [10.0, 10.0, -8.0, -8.0, 20.0]
    result = _drawdown_stats(pnls)
    # peak=20, trough=12 → drawdown=8
    assert result["max_drawdown_before_fees"] == pytest.approx(16.0)


def test_drawdown_stats_empty_pnls_returns_zero_losses() -> None:
    result = _drawdown_stats([])
    assert result["max_consecutive_losses"] == 0
    assert result["max_drawdown_before_fees"] is None


def test_report_includes_drawdown_field(tmp_path: Path) -> None:
    records: list[dict] = []
    start = datetime(2026, 2, 1, 15, 0, tzinfo=timezone.utc)
    for i in range(5):
        cid = f"d-{i}"
        records += [
            {"type": "candidate", "candidate_id": cid, "created_at": (start + timedelta(days=i)).isoformat(),
             "entry_quote_complete": True, "candidate_confidence": {}},
            {"type": "mark", "candidate_id": cid, "quote_complete": True},
            {"type": "outcome", "candidate_id": cid, "pnl_before_fees": 10.0 if i % 2 == 0 else -5.0, "win": i % 2 == 0},
        ]
    report = build_report(records, now=start + timedelta(days=10))
    assert "max_consecutive_losses" in report["drawdown"]
    assert "max_drawdown_before_fees" in report["drawdown"]


def test_timeframe_buckets_have_explicit_gamma_horizons() -> None:
    assert dte_bucket(0) == "0dte"
    assert dte_bucket(6) == "5-7dte"
    assert dte_bucket(25) == "21-30dte"
    assert dte_bucket(35) == "31-45dte"
    assert dte_bucket(None) == "unknown"


def test_entry_time_bucket_uses_eastern_time() -> None:
    assert entry_time_bucket("2026-08-10T13:45:00Z") == "09:30-10:00"
    assert entry_time_bucket("2026-08-10T16:30:00Z") == "11:30-14:00"
    assert entry_time_bucket(None) == "unknown"


def test_candidate_confluence_keeps_vrp_and_ivr_separate() -> None:
    candidate = {
        "strategy": "put_spread",
        "created_at": "2026-08-10T13:45:00Z",
        "expiry": "2026-09-11",
        "iv_rank_at_entry": 62.0,
        "vix_term_ratio": 0.90,
        "quoted_mid_credit": 1.00,
        "executable_entry_credit": 0.90,
        "volatility_edge": {
            "status": "complete_ex_event",
            "net_vol_premium_ex_event_pct": 3.5,
            "event_data_complete": True,
            "macro_events_within_horizon": [],
        },
        "shadow_consensus": {"decision": {"market_direction": "bullish"}},
    }

    dimensions = candidate_dimensions(candidate)

    assert dimensions == {
        "strategy": "put_spread",
        "dte_bucket": "31-45dte",
        "entry_time_et": "09:30-10:00",
        "ivr_band": "50_to_74_99",
        "maturity_matched_vrp_band": "2_to_4_99pct",
        "vix_term_structure": "contango",
        "event_context": "clear_horizon",
        "trend_alignment": "aligned",
        "entry_friction": "watch_5_to_15pct",
    }


def test_confluence_analysis_never_promotes_small_profitable_cohort() -> None:
    candidates = {
        "one": {
            "strategy": "put_spread",
            "created_at": "2026-08-10T13:45:00Z",
            "expiry": "2026-09-11",
            "iv_rank_at_entry": 62.0,
            "vix_term_ratio": 0.90,
            "quoted_mid_credit": 1.0,
            "executable_entry_credit": 0.9,
            "volatility_edge": {
                "status": "complete_ex_event",
                "net_vol_premium_ex_event_pct": 3.5,
                "event_data_complete": True,
                "macro_events_within_horizon": [],
            },
        }
    }
    outcomes = {"one": {"pnl_before_fees": 100.0, "win": True}}

    analysis = build_confluence_analysis(candidates, outcomes)
    cohort = analysis["exact_confluence_cohorts"][0]

    assert analysis["execution_enabled"] is False
    assert analysis["can_submit_orders"] is False
    assert cohort["win_rate"] == 1.0
    assert cohort["statistical_review_ready"] is False
    assert cohort["promotion_eligible"] is False
    assert "fewer_than_30_resolved_outcomes" in cohort["promotion_blockers"]


def test_options_twin_report_exposes_read_only_confluence() -> None:
    report = build_report([])

    assert report["timeframe_confluence"]["authority"] == "read_only_attribution_no_execution"
    assert report["timeframe_confluence"]["execution_enabled"] is False
    assert report["timeframe_confluence"]["can_submit_orders"] is False


def test_latest_iv_rank_context_does_not_promote_accumulating_history(tmp_path: Path) -> None:
    path = tmp_path / "iv.jsonl"
    path.write_text(
        json.dumps({
            "date": "2026-08-10",
            "scans": [{
                "symbol": "SPY",
                "ivr_status": "accumulating",
                "ivr": None,
                "ivp": None,
                "history_days": 6,
                "atm_iv_method": "nearest_expiry_7_45d_mean_atm_call_put_v2",
            }],
        }) + "\n",
        encoding="utf-8",
    )

    context = latest_iv_rank_context("SPY", as_of=datetime(2026, 8, 10).date(), log_path=path)

    assert context["available"] is False
    assert context["status"] == "accumulating"
    assert context["ivr"] is None
    assert context["history_days"] == 6
