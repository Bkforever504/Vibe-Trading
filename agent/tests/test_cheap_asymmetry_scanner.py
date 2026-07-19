from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import cheap_asymmetry_scanner as scanner


def test_build_report_ranks_cheap_contracts_with_explosive_upside(tmp_path: Path) -> None:
    source = tmp_path / "flip-shadow-pnl-evaluator.json"
    source.write_text(
        json.dumps(
            {
                "date": "2026-07-06",
                "top_trades": [
                    {
                        "symbol": "TSLA",
                        "right": "CALL",
                        "option_symbol": "TSLA260706C00420000",
                        "entry_price": 0.19,
                        "best_price": 1.19,
                        "return_pct": 526.32,
                        "simulated_exit_return_pct": 526.32,
                        "capture_efficiency": 1.0,
                        "best_spread_cents": 2,
                        "contracts": 1,
                    },
                    {
                        "symbol": "SPY",
                        "right": "CALL",
                        "option_symbol": "SPY260706C00750000",
                        "entry_price": 0.78,
                        "best_price": 1.66,
                        "return_pct": 112.82,
                        "simulated_exit_return_pct": 50.0,
                        "capture_efficiency": 0.443,
                        "best_spread_cents": 1,
                        "contracts": 5,
                    },
                    {
                        "symbol": "AAPL",
                        "right": "CALL",
                        "option_symbol": "AAPL260706C00312500",
                        "entry_price": 0.31,
                        "best_price": 1.98,
                        "return_pct": 538.71,
                        "simulated_exit_return_pct": 250.0,
                        "capture_efficiency": 0.464,
                        "best_spread_cents": 18,
                        "contracts": 5,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    report = scanner.build_report(source_path=source, day="2026-07-06")

    assert report["execution_enabled"] is False
    assert report["mode"] == "read_only"
    assert report["candidate_count"] == 2
    top = report["top_candidates"][0]
    assert top["symbol"] == "TSLA"
    assert top["option_symbol"] == "TSLA260706C00420000"
    assert top["cost_at_open"] == 19.0
    assert top["best_credit"] == 119.0
    assert top["best_profit"] == 100.0
    assert top["best_return_pct"] == 526.32
    assert top["asymmetry_multiple"] == 6.26
    assert top["goal_match"] is True
    assert "cheap_contract" in top["labels"]
    assert "five_x_runner" in top["labels"]
    assert report["summary"]["goal_match_count"] == 1


def test_build_report_rejects_wide_spread_or_expensive_contracts(tmp_path: Path) -> None:
    source = tmp_path / "flip-shadow-pnl-evaluator.json"
    source.write_text(
        json.dumps(
            {
                "date": "2026-07-06",
                "top_trades": [
                    {
                        "symbol": "NVDA",
                        "right": "CALL",
                        "option_symbol": "NVDA260706C00170000",
                        "entry_price": 1.25,
                        "best_price": 2.00,
                        "return_pct": 60.0,
                        "best_spread_cents": 3,
                        "contracts": 1,
                    },
                    {
                        "symbol": "META",
                        "right": "CALL",
                        "option_symbol": "META260706C00600000",
                        "entry_price": 0.23,
                        "best_price": 0.79,
                        "return_pct": 243.48,
                        "best_spread_cents": 35,
                        "contracts": 1,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    report = scanner.build_report(source_path=source, day="2026-07-06")

    assert report["candidate_count"] == 0
    assert report["rejected_count"] == 2
    reasons = {item["option_symbol"]: item["reject_reasons"] for item in report["rejected"] }
    assert "cost_above_max" in reasons["NVDA260706C00170000"]
    assert "spread_too_wide" in reasons["META260706C00600000"]

