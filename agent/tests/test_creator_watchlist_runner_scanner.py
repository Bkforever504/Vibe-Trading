from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import creator_watchlist_runner_scanner as scanner


def test_creator_watchlist_runner_scanner_scores_called_tickers_against_shadow_runs(tmp_path: Path) -> None:
    observations_path = tmp_path / "creator-watchlist-observations.json"
    shadow_path = tmp_path / "flip-shadow-pnl-evaluator.json"
    asymmetry_path = tmp_path / "cheap-asymmetry-scanner.json"

    observations_path.write_text(
        json.dumps(
            [
                {
                    "source": "x_manual_creator_watchlist",
                    "platform": "x",
                    "creator": "Aristotle Investments",
                    "observed_at": "2026-07-05T18:00:00Z",
                    "keyword": "$RDDT",
                    "caption": "$HIMS & $RDDT were on my watchlist for Monday.",
                    "symbols": ["HIMS", "RDDT"],
                    "mode": "context_only",
                    "execution_enabled": False,
                },
                {
                    "source": "x_manual_creator_watchlist",
                    "platform": "x",
                    "creator": "Prophitcy",
                    "observed_at": "2026-07-06T15:37:00Z",
                    "keyword": "$AAPL",
                    "caption": "Nobody signaled $AAPL calls except for me.",
                    "mode": "context_only",
                    "execution_enabled": False,
                },
            ]
        ),
        encoding="utf-8",
    )
    shadow_path.write_text(
        json.dumps(
            {
                "date": "2026-07-06",
                "by_symbol": {
                    "RDDT": {
                        "sample_count": 2,
                        "completed_count": 2,
                        "winner_count": 2,
                        "win_rate": 1.0,
                        "best_return_pct": 85.57,
                        "total_hypothetical_pnl": 12750.0,
                    },
                    "AAPL": {
                        "sample_count": 3,
                        "completed_count": 3,
                        "winner_count": 2,
                        "win_rate": 0.667,
                        "best_return_pct": 538.71,
                        "total_hypothetical_pnl": 885.0,
                    },
                },
                "top_trades": [
                    {
                        "symbol": "RDDT",
                        "right": "CALL",
                        "option_symbol": "RDDT260717C00230000",
                        "entry_price": 1.7,
                        "return_pct": 85.57,
                        "simulated_exit_return_pct": 85.57,
                    },
                    {
                        "symbol": "AAPL",
                        "right": "CALL",
                        "option_symbol": "AAPL260706C00312500",
                        "entry_price": 0.31,
                        "return_pct": 538.71,
                        "simulated_exit_return_pct": 129.03,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    asymmetry_path.write_text(
        json.dumps(
            {
                "date": "2026-07-06",
                "top_candidates": [
                    {
                        "symbol": "AAPL",
                        "option_symbol": "AAPL260706C00312500",
                        "cost_at_open": 31.0,
                        "best_return_pct": 538.71,
                        "simulated_return_pct": 129.03,
                        "goal_match": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = scanner.build_report(
        day="2026-07-06",
        observations_path=observations_path,
        shadow_path=shadow_path,
        asymmetry_path=asymmetry_path,
    )

    assert report["execution_enabled"] is False
    assert report["mode"] == "read_only"
    assert report["summary"]["runner_count"] == 2
    assert report["summary"]["promotion_ready_count"] == 0
    by_symbol = {item["symbol"]: item for item in report["watchlist_results"]}
    assert by_symbol["RDDT"]["runner_detected"] is True
    assert by_symbol["RDDT"]["best_return_pct"] == 85.57
    assert by_symbol["RDDT"]["called_before_or_same_day"] is True
    assert by_symbol["AAPL"]["cheap_asymmetry_detected"] is True
    assert by_symbol["AAPL"]["best_return_pct"] == 538.71
    assert by_symbol["HIMS"]["runner_detected"] is False
    assert by_symbol["HIMS"]["verdict"] == "needs_shadow_evidence"
