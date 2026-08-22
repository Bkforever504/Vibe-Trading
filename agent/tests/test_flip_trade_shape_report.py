from __future__ import annotations

import json
from pathlib import Path

from scripts import flip_trade_shape_report as report


def test_trade_shape_report_uses_filled_returns_and_executable_path(tmp_path: Path) -> None:
    state = tmp_path / "trades.json"
    state.write_text(
        json.dumps(
            [
                {
                    "status": "closed",
                    "symbol": "QQQ",
                    "entry_date": "2026-08-10",
                    "entry_price": 1.0,
                    "entry_price_source": "broker_fill",
                    "exit_price": 1.2,
                    "exit_price_source": "broker_filled_avg_price",
                    "best_pnl_pct": 40.0,
                    "worst_pnl_pct": -5.0,
                    "first_executable_mark_confirmation": "green",
                    "exit_reason": "PROFIT PROTECT (bid-based)",
                    "last_trade_shape": {
                        "state": "winner_giveback",
                        "mid_to_executable_friction_pct_of_entry": 5.0,
                    },
                },
                {
                    "status": "closed",
                    "symbol": "SPY",
                    "entry_date": "2026-08-11",
                    "entry_price": 2.0,
                    "entry_fill_confirmed": True,
                    "exit_price": 1.5,
                    "exit_price_source": "broker_filled_avg_price",
                    "best_pnl_pct": 0.0,
                    "worst_pnl_pct": -25.0,
                    "first_executable_mark_confirmation": "not_green",
                    "exit_reason": "STOP LOSS (bid-based)",
                    "last_trade_shape": {
                        "state": "loser_never_confirmed",
                        "mid_to_executable_friction_pct_of_entry": 10.0,
                    },
                },
                {"status": "open", "entry_price": 1.0},
            ]
        ),
        encoding="utf-8",
    )

    built = report.build_report(state)

    assert built["execution_enabled"] is False
    assert built["can_change_exit_policy"] is False
    assert built["overall"]["completed_count"] == 2
    assert built["overall"]["win_rate"] == 0.5
    assert built["overall"]["average_realized_return_pct"] == -2.5
    assert built["overall"]["average_capture_ratio_of_positive_mfe"] == 0.5
    assert built["overall"]["average_last_mark_mid_to_bid_friction_pct_of_entry"] == 7.5
    assert built["by_first_executable_mark"]["green"]["average_realized_return_pct"] == 20.0
    assert built["by_first_executable_mark"]["not_green"]["average_realized_return_pct"] == -25.0
    assert built["overall"]["review_ready"] is False


def test_trade_shape_report_does_not_impute_missing_exit_prices(tmp_path: Path) -> None:
    state = tmp_path / "trades.json"
    state.write_text(
        json.dumps([{"status": "closed", "entry_price": 1.0, "exit_price": None}]),
        encoding="utf-8",
    )

    built = report.build_report(state)

    assert built["overall"]["completed_count"] == 0
    assert built["overall"]["average_realized_return_pct"] is None


def test_trade_shape_report_excludes_legacy_quote_exits_from_review(tmp_path: Path) -> None:
    state = tmp_path / "trades.json"
    state.write_text(
        json.dumps(
            [
                {
                    "status": "closed",
                    "entry_price": 1.0,
                    "exit_price": 1.8,
                    "exit_price_source": "quote_mid_at_order_submission",
                    "entry_date": "2026-08-10",
                }
            ]
        ),
        encoding="utf-8",
    )

    built = report.build_report(state)

    assert built["overall"]["completed_count"] == 0
    assert built["legacy_or_unverified_closed"]["completed_count"] == 1
    assert built["legacy_or_unverified_closed"]["excluded_from_review"] is True
