from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.options_edge_attribution_report import build_report


def _candidate(candidate_id: str, strategy: str, mid: float, executable: float) -> dict:
    return {
        "type": "candidate",
        "candidate_id": candidate_id,
        "strategy": strategy,
        "effective_qty": 1,
        "quoted_mid_credit": mid,
        "executable_entry_credit": executable,
        "volatility_edge": {
            "status": "complete",
            "method_version": "maturity_matched_vol_premium_v1",
            "atm_iv_annualized_pct": 22.0,
            "rv_forecast_annualized_pct": 18.0,
            "net_vol_premium_after_event_pct": 2.5,
        },
    }


def test_attribution_prefers_opra_and_compares_matched_structures() -> None:
    evidence = [{
        "type": "matched_setup",
        "setup_id": "setup-1",
        "recorded_at": "2026-08-11T15:00:00Z",
        "source_strategy": "pin_range_0dte",
        "underlying": "SPY",
        "expressions": [
            {"expression_type": "primary", "strategy": "iron_condor", "candidate_id": "primary", "status": "recorded"},
            {"expression_type": "component_put_spread", "strategy": "put_spread", "candidate_id": "put", "status": "recorded"},
            {"expression_type": "no_trade", "strategy": "no_trade", "candidate_id": None, "status": "benchmark"},
        ],
    }]
    twin = [
        _candidate("primary", "iron_condor", 1.20, 1.00),
        _candidate("put", "put_spread", 0.70, 0.60),
        {
            "type": "mark",
            "candidate_id": "primary",
            "executable_close_debit": 0.30,
            "legs": [
                {"side": "sell", "ratio_qty": 1, "bid": 0.30, "ask": 0.40},
                {"side": "buy", "ratio_qty": 1, "bid": 0.10, "ask": 0.15},
            ],
        },
        {"type": "outcome", "candidate_id": "primary", "pnl_before_fees": 999.0, "quantity": 1},
    ]
    nbbo = {"outcomes": [
        {"status": "resolved", "candidate_id": "primary", "pnl_base": 50.0, "quantity": 1, "reason": "profit_target"},
        {"status": "resolved", "candidate_id": "put", "pnl_base": 70.0, "quantity": 1, "reason": "profit_target"},
    ]}

    report = build_report(evidence, twin, nbbo)

    expressions = report["setups"][0]["expressions"]
    primary = next(row for row in expressions if row["expression_type"] == "primary")
    assert primary["outcome_source"] == "licensed_opra_curriculum"
    assert primary["net_pnl_dollars"] == 50.0
    assert primary["entry_execution_edge"]["friction_dollars"] == 20.0
    assert primary["exit_execution_edge"]["friction_dollars"] == 7.5
    assert report["setups"][0]["structure_edge"]["best_alternative_minus_primary_dollars"] == 20.0
    assert report["aggregate_net_pnl_dollars"] == 120.0
    assert report["outcome_source_counts"] == {"licensed_opra_curriculum": 2}
    assert report["promotion_authority"] == "blocked"
    assert report["execution_enabled"] is False


def test_unresolved_setup_stays_unattributed() -> None:
    evidence = [{
        "type": "matched_setup",
        "setup_id": "setup-2",
        "expressions": [
            {"expression_type": "primary", "strategy": "put_spread", "candidate_id": "open", "status": "recorded"},
        ],
    }]
    report = build_report(evidence, [_candidate("open", "put_spread", 1.0, 0.9)], {})

    expression = report["setups"][0]["expressions"][0]
    assert expression["status"] == "unresolved"
    assert expression["net_pnl_dollars"] is None
    assert report["resolved_setup_count"] == 0
    assert report["average_net_pnl_dollars"] is None
    assert report["can_submit_orders"] is False


def test_liquidity_sweep_cohorts_attribute_primary_outcomes_without_promotion() -> None:
    evidence = [{
        "type": "matched_setup",
        "setup_id": "sweep-1",
        "regime_context": {
            "liquidity_sweep": {
                "status": "available",
                "events": [{"direction": "bullish", "level": "PDL"}],
            }
        },
        "expressions": [
            {"expression_type": "primary", "strategy": "put_spread", "candidate_id": "sweep-primary"},
        ],
    }]
    twin = [
        _candidate("sweep-primary", "put_spread", 0.8, 0.7),
        {"type": "outcome", "candidate_id": "sweep-primary", "pnl_before_fees": 25.0, "quantity": 1},
    ]

    report = build_report(evidence, twin, {})

    cohort = report["setups"][0]["liquidity_sweep_cohort"]
    aggregate = report["liquidity_sweep_attribution"]
    assert cohort["bucket"] == "bullish_proxy"
    assert cohort["execution_authority"] is False
    assert aggregate["cohorts"]["bullish_proxy"]["average_primary_pnl_dollars"] == 25.0
    assert aggregate["promotion_authority"] == "blocked"
