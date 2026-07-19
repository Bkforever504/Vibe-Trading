from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import edge_trial_ledger as ledger
from strategies import backtest


def _trial(edge: str, *, p_value: float | None = 0.001, trades: int = 40) -> dict:
    metrics = {
        "oos_trade_count": trades,
        "oos_expectancy": 4.5,
        "oos_profit_factor": 1.6,
        "oos_max_drawdown": -8.0,
    }
    if p_value is not None:
        metrics["oos_p_value"] = p_value
    return {
        "edge_id": edge,
        "hypothesis": "The edge improves net expectancy after costs.",
        "variant": "v1",
        "stage": "out_of_sample",
        "parameters": {"lookback": 20},
        "dataset_start": "2024-01-01",
        "dataset_end": "2025-12-31",
        "oos_start": "2025-07-01",
        "oos_end": "2025-12-31",
        "cost_model": "nbbo_half_spread_plus_0.02_slippage",
        "metrics": metrics,
        "source": "unit_test",
        "code_version": "abc123",
    }


def test_record_is_immutable_and_deduplicated(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    first = ledger.record_trial(_trial("edge-a"), path)
    second = ledger.record_trial(_trial("edge-a"), path)

    assert first["recorded"] is True
    assert second == {"recorded": False, "duplicate": True, "trial_id": first["trial_id"]}
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["execution_enabled"] is False
    assert stored["can_submit_orders"] is False


def test_trial_requires_oos_window_costs_and_metrics(tmp_path: Path) -> None:
    bad = _trial("bad")
    del bad["cost_model"]
    del bad["oos_start"]

    with pytest.raises(ValueError) as exc:
        ledger.record_trial(bad, tmp_path / "ledger.jsonl")

    assert "missing_cost_model" in str(exc.value)
    assert "missing_oos_start" in str(exc.value)


def test_report_counts_all_trials_in_multiple_testing_family(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger.record_trial(_trial("strong", p_value=0.001), path)
    ledger.record_trial(_trial("weak", p_value=0.04), path)
    ledger.record_trial(_trial("missing-stat", p_value=None), path)

    report = ledger.build_report(path)
    by_edge = {row["edge_id"]: row for row in report["trials"]}

    assert report["trial_count"] == 3
    assert report["multiple_testing"]["bonferroni_alpha"] == pytest.approx(0.05 / 3)
    assert report["multiple_testing"]["all_attempted_trials_counted"] is True
    assert by_edge["strong"]["promotion_review_eligible"] is True
    assert by_edge["weak"]["bonferroni_pass"] is False
    assert "multiple_testing_threshold_not_met" in by_edge["missing-stat"]["promotion_blockers"]
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_tiny_oos_sample_blocks_even_significant_trial(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger.record_trial(_trial("tiny", p_value=0.00001, trades=5), path)

    report = ledger.build_report(path)
    row = report["trials"][0]

    assert row["bonferroni_pass"] is True
    assert row["promotion_review_eligible"] is False
    assert "fewer_than_30_oos_trades" in row["promotion_blockers"]


def test_options_backtest_builds_in_sample_trial_that_cannot_promote(tmp_path: Path) -> None:
    result = backtest.TradeResult(
        symbol="IWM", strategy="ps", entry_date="2025-01-02", exit_date="2025-01-10",
        entry_credit=0.50, exit_cost=0.20, pnl=30.0, pnl_pct=60.0, days_held=8,
        exit_reason="target", short_strike=200, long_strike=197, dte_at_entry=10,
    )
    trial = backtest.build_edge_trial([result], "IWM", "ps", 252)
    assert trial is not None
    assert trial["stage"] == "in_sample"
    ledger.record_trial(trial, tmp_path / "ledger.jsonl")

    report = ledger.build_report(tmp_path / "ledger.jsonl")
    row = report["trials"][0]

    assert row["promotion_review_eligible"] is False
    assert "out_of_sample_or_forward_stage_required" in row["promotion_blockers"]
