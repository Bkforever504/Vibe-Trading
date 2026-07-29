from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import options_quant_risk_budget as qrb


def _state(path: Path) -> Path:
    trades = []
    for idx in range(8):
        trades.append({
            "status": "closed",
            "underlying": "AAPL",
            "strategy": "put_spread",
            "qty": 1,
            "net_credit": 0.80,
            "max_risk_per_contract": 420,
            "realized_pnl_dollars": 120 if idx < 6 else -40,
        })
    path.write_text(json.dumps({"trades": trades}), encoding="utf-8")
    return path


def test_realized_pnl_estimate_parses_credit_percent() -> None:
    trade = {
        "status": "closed",
        "qty": 2,
        "net_credit": 0.50,
        "closing_reason": "stop loss hit: -150.0% of credit",
    }
    assert qrb.realized_pnl_estimate(trade) == -150.0


def test_build_report_is_read_only_and_scores_groups(tmp_path: Path) -> None:
    report = qrb.build_report(
        state_file=_state(tmp_path / "options-trades.json"),
        garch_report=tmp_path / "missing-garch.json",
        heatmap_report=tmp_path / "missing-heat.json",
        account_equity=100_000,
        mc_paths=200,
    )

    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["summary"]["closed_trade_samples"] == 8
    assert report["groups"]["global"]["sample_size"] == 8
    assert report["groups"]["symbol_strategy:AAPL:put_spread"]["final_risk_cap_fraction"] >= 0


def test_candidate_allocation_sizes_down_from_report(tmp_path: Path) -> None:
    report = qrb.build_report(
        state_file=_state(tmp_path / "options-trades.json"),
        account_equity=50_000,
        max_risk_fraction=0.01,
        mc_paths=200,
    )
    report_path = tmp_path / "risk.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    advice = qrb.candidate_allocation(
        symbol="AAPL",
        strategy="put_spread",
        requested_qty=5,
        max_risk_per_contract=100,
        equity=50_000,
        confidence_score=9,
        report_path=report_path,
    )

    assert advice["allowed"] is True
    assert 1 <= advice["adjusted_qty"] <= 5
    assert advice["selected_group"] == "symbol_strategy:AAPL:put_spread"


def test_candidate_allocation_missing_report_can_fail_open_or_closed(tmp_path: Path) -> None:
    loose = qrb.candidate_allocation(
        symbol="SPY",
        strategy="put_spread",
        requested_qty=2,
        max_risk_per_contract=300,
        equity=100_000,
        report_path=tmp_path / "missing.json",
        require_report=False,
    )
    strict = qrb.candidate_allocation(
        symbol="SPY",
        strategy="put_spread",
        requested_qty=2,
        max_risk_per_contract=300,
        equity=100_000,
        report_path=tmp_path / "missing.json",
        require_report=True,
    )
    assert loose["allowed"] is True
    assert loose["adjusted_qty"] == 2
    assert strict["allowed"] is False
    assert strict["adjusted_qty"] == 0


def test_candidate_allocation_allows_tiny_high_confidence_exploration(tmp_path: Path) -> None:
    report = {
        "parameters": {"max_risk_fraction": 0.01},
        "groups": {
            "global": {
                "key": "global",
                "sample_size": 2,
                "final_risk_cap_fraction": 0.0,
            }
        },
    }
    report_path = tmp_path / "risk.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    advice = qrb.candidate_allocation(
        symbol="PLTR",
        strategy="call_spread",
        requested_qty=3,
        max_risk_per_contract=75,
        equity=100_000,
        confidence_score=9,
        report_path=report_path,
        exploration_risk_fraction=0.001,
    )

    assert advice["allowed"] is True
    assert advice["adjusted_qty"] == 1
    assert advice["reason"] == "quant_risk_exploration_cap"
    assert advice["exploration_cap_used"] is True


def test_candidate_allocation_does_not_explore_proven_bad_strategy(tmp_path: Path) -> None:
    report = {
        "parameters": {"max_risk_fraction": 0.01},
        "groups": {
            "global": {
                "key": "global",
                "sample_size": 20,
                "final_risk_cap_fraction": 0.0,
            },
            "strategy:put_spread": {
                "key": "strategy:put_spread",
                "sample_size": 8,
                "final_risk_cap_fraction": 0.0,
            },
        },
    }
    report_path = tmp_path / "risk.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    advice = qrb.candidate_allocation(
        symbol="SPY",
        strategy="put_spread",
        requested_qty=1,
        max_risk_per_contract=300,
        equity=100_000,
        confidence_score=10,
        report_path=report_path,
        exploration_risk_fraction=0.001,
    )

    assert advice["allowed"] is False
    assert advice["adjusted_qty"] == 0
    assert advice["exploration_cap_used"] is False
    assert advice["exploration_blocked_by_proven_group"] is True
