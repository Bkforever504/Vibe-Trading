from __future__ import annotations

import json
from pathlib import Path

from scripts.opportunity_intelligence_pipeline import (
    _bootstrap_mean,
    append_candidates,
    edge_decay,
    execution_ab,
    execution_reality_gap,
    placebo_test,
    portfolio_dependence,
    portfolio_report,
    strategy_lifecycle,
    uncertainty_weights,
)
from scripts.monthly_algo_evidence_packet import render_packet


def _candidate(lane: str, eligible: bool = True) -> dict:
    return {
        "candidate_id": lane,
        "lane": lane,
        "eligible": eligible,
        "decision": "consider" if eligible else "reject",
        "rejection_reasons": [] if eligible else ["blocked"],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def test_positive_placebo_and_stable_decay() -> None:
    values = [10.0, 12.0, 8.0, 11.0] * 10
    assert placebo_test(values)["status"] == "pass"
    assert edge_decay(values)["status"] == "stable"
    assert _bootstrap_mean(values)["ci90"][0] > 0


def test_decay_suspends_collapsed_recent_edge() -> None:
    result = edge_decay([10.0] * 20 + [-5.0] * 20)
    assert result["status"] == "suspend"
    assert result["research_allocation_allowed"] is False


def test_uncertainty_weights_keep_residual_in_cash() -> None:
    candidates = [_candidate("qqq_mean_reversion"), _candidate("mes_reopen_drift"), _candidate("cash")]
    evidence = {
        "qqq_mean_reversion": {
            "observations": 50,
            "max_drawdown": 100.0,
            "bootstrap": {"ci90": [5.0, 10.0]},
            "decay": {"status": "stable"},
        },
        "mes_reopen_drift": {
            "observations": 50,
            "max_drawdown": 100.0,
            "bootstrap": {"ci90": [-1.0, 10.0]},
            "decay": {"status": "stable"},
        },
    }
    weights = uncertainty_weights(candidates, evidence)
    assert weights["qqq_mean_reversion"] == 0.35
    assert weights["mes_reopen_drift"] == 0.0
    assert weights["cash"] == 0.65


def test_append_candidates_is_idempotent(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    rows = [_candidate("cash")]
    assert append_candidates(ledger, rows) == 1
    assert append_candidates(ledger, rows) == 0
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_execution_ab_uses_quote_interpolation_and_has_no_authority(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    row = {"type": "candidate", "candidate_id": "x", "midpoint_credit": 1.0, "entry_credit": 0.8}
    (data / "options_shadow_twin_log.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    result = execution_ab(tmp_path)
    assert result["samples"] == 1
    assert result["average_entry_credit"]["patient_limit_proxy"] == 0.9
    assert result["selection_authority"].startswith("blocked")


def test_portfolio_report_runs_block_bootstrap() -> None:
    series = {
        "qqq_mean_reversion": [
            {"date": f"2026-01-{day:02d}", "pnl": 5.0 if day % 3 else -2.0}
            for day in range(1, 29)
        ]
    }
    report = portfolio_report(series, {"qqq_mean_reversion": 0.35, "cash": 0.65})
    assert report["synchronized_dates"] == 28
    assert report["moving_block_bootstrap"]["status"] == "ok"


def test_portfolio_dependence_detects_joint_loss_cluster() -> None:
    dates = [f"2026-01-{day:02d}" for day in range(1, 29)]
    left = [5.0 if day % 4 else -10.0 for day in range(1, 29)]
    right = [4.0 if day % 4 else -8.0 for day in range(1, 29)]
    series = {
        "left": [{"date": day, "pnl": pnl} for day, pnl in zip(dates, left)],
        "right": [{"date": day, "pnl": pnl} for day, pnl in zip(dates, right)],
    }
    report = portfolio_dependence(series, {"left": 0.2, "right": 0.2, "cash": 0.6})
    pair = report["pairs"][0]
    assert pair["status"] == "correlated_risk_cluster"
    assert pair["joint_loss_lift_vs_independence"] == 4.0
    assert report["status"] == "concentrated"
    assert report["allocation_authority"].startswith("blocked")


def test_portfolio_dependence_requires_synchronized_overlap() -> None:
    series = {
        "left": [{"date": f"2026-01-{day:02d}", "pnl": 1.0} for day in range(1, 10)],
        "right": [{"date": f"2026-01-{day:02d}", "pnl": -1.0} for day in range(1, 10)],
    }
    report = portfolio_dependence(series, {"cash": 1.0})
    pair = report["pairs"][0]
    assert pair["status"] == "insufficient_overlap"
    assert report["status"] == "cash_only"


def test_portfolio_dependence_does_not_call_one_lane_diversified() -> None:
    series = {"only": [{"date": f"2026-01-{day:02d}", "pnl": 1.0} for day in range(1, 29)]}
    report = portfolio_dependence(series, {"only": 0.35, "cash": 0.65})
    assert report["status"] == "single_active_lane"


def test_execution_reality_gap_suspends_reviews_on_large_observed_drift() -> None:
    trades = [
        {
            "entry_execution_evidence": {
                "fill_vs_signal_ask_pct": 4.0,
                "fill_vs_submit_ask_pct": 3.0,
                "submit_to_fill_seconds": 2.0,
            }
        }
        for _ in range(10)
    ]
    result = execution_reality_gap(trades, modeled_gap_pct=1.0)
    assert result["status"] == "high_execution_drift"
    assert result["intervention"] == "suspend_new_promotion_reviews"
    assert result["execution_authority"].startswith("blocked")


def test_strategy_lifecycle_requires_two_passing_reviews() -> None:
    evidence = {
        "lane": {
            "observations": 40,
            "bootstrap": {"ci90": [1.0, 3.0]},
            "placebo": {"status": "pass"},
            "decay": {"status": "stable"},
        }
    }
    first = strategy_lifecycle(evidence, review_key="2026-08-19")
    assert first["lanes"]["lane"]["state"] == "recovery_observation"
    previous = {"strategy_lifecycle": first}
    rerun = strategy_lifecycle(evidence, previous, review_key="2026-08-19")
    assert rerun["lanes"]["lane"]["stable_review_streak"] == 1
    second = strategy_lifecycle(evidence, previous, review_key="2026-08-20")
    assert second["lanes"]["lane"]["state"] == "review_ready"
    assert second["lanes"]["lane"]["automatic_promotion_allowed"] is False


def test_strategy_lifecycle_migrates_legacy_same_day_review_without_increment() -> None:
    evidence = {
        "lane": {
            "observations": 40,
            "bootstrap": {"ci90": [1.0, 3.0]},
            "placebo": {"status": "pass"},
            "decay": {"status": "stable"},
        }
    }
    previous = {
        "generated_at": "2026-08-19T12:00:00Z",
        "strategy_lifecycle": {
            "lanes": {"lane": {"stable_review_streak": 2}}
        },
    }
    result = strategy_lifecycle(evidence, previous, review_key="2026-08-19")
    assert result["lanes"]["lane"]["stable_review_streak"] == 1
    assert result["lanes"]["lane"]["state"] == "recovery_observation"


def test_strategy_lifecycle_suspends_decayed_lane() -> None:
    evidence = {
        "lane": {
            "observations": 40,
            "bootstrap": {"ci90": [1.0, 3.0]},
            "placebo": {"status": "pass"},
            "decay": {"status": "suspend"},
        }
    }
    result = strategy_lifecycle(evidence)["lanes"]["lane"]
    assert result["state"] == "suspended"
    assert result["paper_review_eligible"] is False


def test_strategy_lifecycle_preserves_qqq_multiple_testing_block() -> None:
    evidence = {
        "qqq_mean_reversion": {
            "observations": 136,
            "bootstrap": {"ci90": [20.0, 70.0]},
            "placebo": {"status": "pass"},
            "decay": {"status": "stable"},
        }
    }
    previous = {
        "strategy_lifecycle": {
            "schema_version": 2,
            "lanes": {
                "qqq_mean_reversion": {
                    "stable_review_streak": 1,
                    "last_review_key": "2026-08-18",
                }
            },
        }
    }
    result = strategy_lifecycle(evidence, previous, review_key="2026-08-19")["lanes"]["qqq_mean_reversion"]
    assert result["stable_review_streak"] == 2
    assert result["state"] == "research_only"
    assert result["paper_review_eligible"] is False
    assert result["permanent_review_block"] == "development_only_failed_experiment_wide_multiple_testing"


def test_monthly_packet_preserves_no_order_authority() -> None:
    packet = render_packet({
        "generated_at": "2026-08-19T12:00:00Z",
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
        "promotion_authority": "blocked",
        "strategy_lifecycle": {"lanes": {}},
        "evidence": {},
        "portfolio_dependence": {"status": "cash_only", "pairs": []},
        "execution_reality_gap": {"status": "insufficient_forward_fills"},
        "configuration_fingerprint": {"combined": "abc"},
        "operational_slo": {"status": "ok"},
    })
    assert "Execution enabled: `False`" in packet
    assert "Can submit orders: `False`" in packet
    assert "Orders submitted: `0`" in packet
