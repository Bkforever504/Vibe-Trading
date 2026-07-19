from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import position_sizing_sanity_report as sizing


def test_tail_bounds_tighten_from_markov_to_chernoff() -> None:
    returns = [0.8, 0.6, -0.5, 0.7, -0.25, 0.4, 0.3, 0.2]

    bounds = sizing.tail_bounds(returns, tail_loss_threshold=0.5)

    assert bounds["markov_upper_bound"] >= bounds["chebyshev_upper_bound"]
    assert bounds["chebyshev_upper_bound"] >= bounds["chernoff_style_upper_bound"]
    assert 0 <= bounds["empirical_tail_rate"] <= 1


def test_contract_cap_and_risk_pct_are_enforced() -> None:
    result = sizing.evaluate_candidate_sizing(
        account_size=100_000,
        option_price=1.0,
        max_risk_pct=0.02,
        max_contracts=5,
    )

    assert result["raw_contracts"] == 20
    assert result["recommended_contracts"] == 5
    assert result["contract_cap_binding"] is True
    assert result["risk_pct_binding"] is False
    assert result["estimated_notional"] == 500.0


def test_small_account_blocks_unaffordable_contract() -> None:
    result = sizing.evaluate_candidate_sizing(
        account_size=200,
        option_price=5.0,
        max_risk_pct=0.02,
        max_contracts=5,
    )

    assert result["recommended_contracts"] == 0
    assert result["verdict"] == "blocked_unaffordable"


def test_build_report_is_read_only_and_flags_pre_fix_artifact(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    trades.write_text(
        json.dumps([
            {"entry_date": "2026-06-23", "status": "closed", "contracts": 69, "entry_price": 2.5, "pnl": -11557.5},
            {"entry_date": "2026-06-29", "status": "closed", "contracts": 5, "entry_price": 1.0, "pnl": 500.0},
            {"entry_date": "2026-06-30", "status": "closed", "contracts": 5, "entry_price": 1.0, "pnl": 400.0},
        ]),
        encoding="utf-8",
    )

    report = sizing.build_report(trades_path=trades, account_size=5000, option_price=1.0)

    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["configured_limits"]["max_risk_pct"] == 0.02
    assert report["configured_limits"]["max_contracts"] == 5
    assert report["post_config"]["trade_count"] == 2
    assert report["all_time"]["max_contracts_seen"] == 69
    assert report["verdict"] == "risk_controls_pass_observe_only"
    assert "pre_fix_contract_artifact_detected" in report["warnings"]


def test_log_report_writes_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "position-sizing.jsonl"
    report = sizing.build_report(trades_path=tmp_path / "missing.json")

    sizing.append_log(report, log_path=log_path)

    loaded = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert loaded["provider"] == "position_sizing_sanity_report"
