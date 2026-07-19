from __future__ import annotations

import json
from pathlib import Path

from scripts import flip_exit_quality_report as report


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_report_computes_exit_quality_without_execution(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [{
        "id": "t1", "alpaca_order_id": "o1", "status": "closed", "symbol": "SPY",
        "strategy": "bull_trend", "right": "CALL", "entry_at": "2026-07-13T14:30:00Z",
        "exit_at": "2026-07-13T15:15:00Z", "entry_price": 1.0, "exit_price": 1.5,
        "best_pnl_pct": 80.0, "worst_pnl_pct": -12.0, "stop_price": 0.70,
        "exit_reason": "profit protect",
    }])

    result = report.build_report(trades)
    row = result["trades"][0]

    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False
    assert row["hold_minutes"] == 45.0
    assert row["realized_return_pct"] == 50.0
    assert row["capture_efficiency"] == 0.625
    assert row["giveback_pct"] == 30.0
    assert row["mae_vs_stop_distance_pct"] == 18.0


def test_report_marks_legacy_trade_insufficient_instead_of_estimating(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [{
        "id": "legacy", "status": "closed", "symbol": "SPY", "strategy": "0dte",
        "entry_price": 1.0, "exit_price": 1.2,
    }])

    result = report.build_report(trades)

    assert result["complete_count"] == 0
    assert result["insufficient_data_count"] == 1
    assert "entry_at" in result["insufficient_data"][0]["missing_fields"]
    assert "best_pnl_pct" in result["insufficient_data"][0]["missing_fields"]


def test_report_excludes_synthetic_legacy_backfill_from_complete_count(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [{
        "id": "legacy-filled", "alpaca_order_id": "o1", "status": "closed", "symbol": "SPY",
        "strategy": "bull_trend", "right": "CALL", "entry_at": "2026-07-13T13:30:00Z",
        "exit_at": "2026-07-13T17:45:00Z", "entry_price": 1.0, "exit_price": 1.5,
        "best_pnl_pct": 80.0, "worst_pnl_pct": -50.0, "stop_price": 0.50,
        "exit_reason": "PROFIT TARGET +80.0%",
        "_backfilled_fields": ["entry_at", "exit_at", "best_pnl_pct", "worst_pnl_pct"],
        "telemetry_quality": "synthetic_legacy_backfill",
        "path_telemetry_observed": False,
    }])

    result = report.build_report(trades)
    row = result["insufficient_data"][0]

    assert result["complete_count"] == 0
    assert result["insufficient_data_count"] == 1
    assert row["synthetic_fields"] == ["best_pnl_pct", "entry_at", "exit_at", "worst_pnl_pct"]
    assert "reconstructed" in row["reason"]


def test_report_ignores_open_trades(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [{"id": "open", "status": "open", "symbol": "SPY"}])

    result = report.build_report(trades)

    assert result["closed_trade_count"] == 0
    assert result["trades"] == []


def test_losing_exit_after_green_excursion_is_not_winner_capture(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [{
        "id": "loss-after-green", "alpaca_order_id": "o-loss", "status": "closed",
        "symbol": "SPY", "strategy": "0dte", "right": "CALL",
        "entry_at": "2026-07-16T15:00:00Z", "exit_at": "2026-07-16T16:00:00Z",
        "entry_price": 1.0, "exit_price": 0.6217, "best_pnl_pct": 12.61,
        "worst_pnl_pct": -37.83, "stop_price": 0.70, "exit_reason": "STOP LOSS -37.8%",
    }])

    result = report.build_report(trades)
    row = result["trades"][0]

    assert row["exit_quality_classification"] == "stop_loss_after_favorable_excursion"
    assert row["winner_capture_eligible"] is False
    assert row["capture_efficiency"] is None
    assert row["giveback_pct"] is None
    assert row["favorable_excursion_surrendered_pct"] == 50.44
    assert result["by_strategy"]["0dte"]["avg_capture_efficiency"] is None
    assert result["by_strategy"]["0dte"]["loss_after_favorable_excursion_count"] == 1
