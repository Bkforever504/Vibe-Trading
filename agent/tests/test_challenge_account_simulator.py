from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.challenge_account_simulator import DEFAULT_RISK_PRESETS, build_report, simulate_challenge_account


def test_simulate_challenge_account_replays_trade_returns_with_fixed_risk() -> None:
    trades = [
        {
            "entry_date": "2026-06-29",
            "status": "closed",
            "entry_price": 1.00,
            "exit_price": 1.80,
            "contracts": 5,
            "pnl": 400.0,
        },
        {
            "entry_date": "2026-06-30",
            "status": "closed",
            "entry_price": 2.00,
            "exit_price": 1.00,
            "contracts": 5,
            "pnl": -500.0,
        },
    ]

    result = simulate_challenge_account(trades, start_balance=1000.0, risk_pct=0.10)

    assert result["start_balance"] == 1000.0
    assert result["risk_pct"] == 0.10
    assert result["trade_count"] == 2
    assert result["win_rate"] == 0.5
    assert result["equity_curve"][0]["return_pct"] == 0.8
    assert result["equity_curve"][0]["sim_pnl"] == 80.0
    assert result["equity_curve"][-1]["balance"] == 1026.0
    assert result["max_drawdown_pct"] > 0


def test_build_report_reads_flip_trades_and_is_json_serializable(tmp_path: Path) -> None:
    state = tmp_path / "flip-trades.json"
    state.write_text(
        json.dumps(
            [
                {
                    "id": "t1",
                    "entry_date": "2026-06-29",
                    "status": "closed",
                    "symbol": "SPY",
                    "strategy": "bull_trend",
                    "entry_price": 1.00,
                    "exit_price": 1.80,
                    "contracts": 1,
                    "pnl": 80.0,
                }
            ]
        ),
        encoding="utf-8",
    )

    report = build_report(state, start_balance=500.0, risk_pct=0.05)

    assert report["mode"] == "read_only"
    assert report["execution_enabled"] is False
    assert report["simulation"]["end_balance"] == 508.0
    assert report["simulations"]["aggressive"]["end_balance"] == 520.0
    assert report["simulations"]["conservative"]["risk_pct"] == DEFAULT_RISK_PRESETS["conservative"]
    assert report["simulations"]["flip_challenge"]["risk_pct"] == DEFAULT_RISK_PRESETS["flip_challenge"]
    assert report["simulations"]["stress_test"]["risk_pct"] == DEFAULT_RISK_PRESETS["stress_test"]
    json.dumps(report)


def test_build_report_can_override_risk_presets(tmp_path: Path) -> None:
    state = tmp_path / "flip-trades.json"
    state.write_text("[]", encoding="utf-8")

    report = build_report(state, start_balance=500.0, risk_presets={"custom": 0.15})

    assert list(report["simulations"].keys()) == ["custom"]
    assert report["simulations"]["custom"]["risk_pct"] == 0.15
    assert report["simulation"] == report["simulations"]["custom"]
