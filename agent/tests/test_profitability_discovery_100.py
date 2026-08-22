from __future__ import annotations

from research.profitability_discovery_100 import (
    BONFERRONI_ALPHA,
    EFFECTIVE_ATTEMPTS,
    build_registry,
    build_ledger_import,
    metrics,
)


def test_registry_contains_exactly_100_unique_trials() -> None:
    registry = build_registry()
    ids = [row["trial_id"] for row in registry["trials"]]
    assert registry["trial_count"] == 100
    assert len(ids) == len(set(ids)) == 100
    assert len({row["family"] for row in registry["trials"]}) == 10
    assert registry["execution_enabled"] is False
    assert registry["can_submit_orders"] is False


def test_multiple_testing_denominator_counts_all_new_attempts() -> None:
    assert EFFECTIVE_ATTEMPTS == 515
    assert BONFERRONI_ALPHA == 0.05 / 515


def test_metrics_charge_two_sided_cost_and_start_drawdown_at_zero() -> None:
    result = metrics([2.0, -1.0])
    assert result["trades"] == 2
    assert result["total_pnl"] == -4.96
    assert result["max_drawdown"] == 9.98


def test_ledger_export_keeps_all_failed_trials() -> None:
    registry = build_registry()
    trials = []
    for trial in registry["trials"]:
        trials.append({
            **trial,
            "development": {"trades": 10, "expectancy": -1, "profit_factor": 0.9, "max_drawdown": 20, "t_stat": -1, "p_value": 0.8},
            "development_2x_cost": {"expectancy": -2},
            "discovery_survivor": False,
        })
    report = {"trials": trials, "registry_sha256": registry["registry_sha256"]}
    raw = __import__("pandas").DataFrame({
        "timestamp": __import__("pandas").date_range("2026-01-01", periods=200, freq="D")
    })
    records = build_ledger_import(report, raw)
    assert len(records) == 100
    assert all(row["metrics"]["development_survivor"] is False for row in records)
