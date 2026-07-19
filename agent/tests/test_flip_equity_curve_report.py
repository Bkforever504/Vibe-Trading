from __future__ import annotations

import json
from pathlib import Path

from scripts import flip_equity_curve_report as report


def _write(path: Path, trades: list[dict]) -> None:
    path.write_text(json.dumps(trades), encoding="utf-8")


def _closed(
    trade_id: str,
    order_id: str,
    entry_date: str,
    exit_date: str,
    pnl: float,
    *,
    strategy: str = "bull_trend",
    exit_reason: str = "PROFIT TARGET",
) -> dict:
    return {
        "id": trade_id,
        "alpaca_order_id": order_id,
        "status": "closed",
        "symbol": "SPY",
        "strategy": strategy,
        "right": "CALL",
        "contracts": 5,
        "entry_date": entry_date,
        "exit_date": exit_date,
        "entry_price": 1.0,
        "exit_price": 1.5,
        "pnl": pnl,
        "exit_reason": exit_reason,
    }


# ---------------------------------------------------------------------------
# Safety guards
# ---------------------------------------------------------------------------

def test_report_never_enables_execution(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [_closed("t1", "o1", "2026-06-29", "2026-06-29", 500.0)])
    result = report.build_report(trades)
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False


# ---------------------------------------------------------------------------
# Pre-hardening exclusion
# ---------------------------------------------------------------------------

def test_pre_hardening_trade_excluded_from_curve(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [
        _closed("pre", "o-pre", "2026-06-23", "2026-06-23", -11557.5),
        _closed("post", "o-post", "2026-06-29", "2026-06-29", 535.0),
    ])
    result = report.build_report(trades)
    s = result["summary"]
    assert s["pre_hardening_excluded"] == 1
    assert s["post_hardening_trades"] == 1
    assert s["net_pnl"] == 535.0
    assert len(result["equity_curve"]) == 1


# ---------------------------------------------------------------------------
# Open trades ignored
# ---------------------------------------------------------------------------

def test_open_trades_excluded(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [
        {"id": "open1", "status": "open", "symbol": "SPY", "entry_date": "2026-07-01"},
        _closed("c1", "o1", "2026-06-29", "2026-06-29", 200.0),
    ])
    result = report.build_report(trades)
    assert result["summary"]["post_hardening_trades"] == 1


# ---------------------------------------------------------------------------
# Equity curve and max drawdown
# ---------------------------------------------------------------------------

def test_equity_curve_cumulative_pnl(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [
        _closed("t1", "o1", "2026-06-29", "2026-06-29", 100.0),
        _closed("t2", "o2", "2026-06-30", "2026-06-30", 200.0),
        _closed("t3", "o3", "2026-07-01", "2026-07-01", -50.0),
    ])
    result = report.build_report(trades)
    curve = result["equity_curve"]
    assert curve[0]["cumulative_pnl"] == 100.0
    assert curve[1]["cumulative_pnl"] == 300.0
    assert curve[2]["cumulative_pnl"] == 250.0


def test_max_drawdown_peak_to_trough(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [
        _closed("t1", "o1", "2026-06-29", "2026-06-29", 100.0),
        _closed("t2", "o2", "2026-06-30", "2026-06-30", 200.0),
        _closed("t3", "o3", "2026-07-01", "2026-07-01", -80.0),
        _closed("t4", "o4", "2026-07-02", "2026-07-02", -70.0),
    ])
    result = report.build_report(trades)
    s = result["summary"]
    # Peak=300, trough=300-80-70=150, drawdown=-150
    assert s["max_drawdown_dollars"] == -150.0
    assert s["max_drawdown_pct"] == round(-150.0 / 300.0 * 100, 2)
    assert s["max_drawdown_peak_trade_num"] == 2
    assert s["max_drawdown_trough_trade_num"] == 4
    assert s["max_drawdown_peak_date"] == "2026-06-30"
    assert s["max_drawdown_trough_date"] == "2026-07-02"


def test_no_drawdown_when_all_winners(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [
        _closed("t1", "o1", "2026-06-29", "2026-06-29", 100.0),
        _closed("t2", "o2", "2026-06-30", "2026-06-30", 200.0),
    ])
    result = report.build_report(trades)
    s = result["summary"]
    assert s["max_drawdown_dollars"] == 0.0
    assert s["max_drawdown_pct"] == 0.0
    assert s["max_drawdown_peak_date"] is None
    assert s["max_drawdown_trough_date"] is None
    assert s["current_drawdown_dollars"] == 0.0


def test_current_drawdown_when_in_drawdown(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [
        _closed("t1", "o1", "2026-06-29", "2026-06-29", 500.0),
        _closed("t2", "o2", "2026-06-30", "2026-06-30", -100.0),
    ])
    result = report.build_report(trades)
    s = result["summary"]
    assert s["current_drawdown_dollars"] == -100.0
    assert s["peak_cumulative_pnl"] == 500.0


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

def test_win_rate_profit_factor_expectancy(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [
        _closed("t1", "o1", "2026-06-29", "2026-06-29", 200.0),
        _closed("t2", "o2", "2026-06-30", "2026-06-30", 300.0),
        _closed("t3", "o3", "2026-07-01", "2026-07-01", -100.0),
        _closed("t4", "o4", "2026-07-02", "2026-07-02", -50.0),
    ])
    result = report.build_report(trades)
    s = result["summary"]
    assert s["wins"] == 2
    assert s["losses"] == 2
    assert s["win_rate"] == 0.5
    assert s["gross_profit"] == 500.0
    assert s["gross_loss"] == 150.0
    assert s["profit_factor"] == round(500.0 / 150.0, 4)
    assert s["expectancy_per_trade"] == round(350.0 / 4, 2)
    assert s["net_pnl"] == 350.0


def test_empty_file_returns_zero_summary(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [])
    result = report.build_report(trades)
    s = result["summary"]
    assert s["post_hardening_trades"] == 0
    assert s["net_pnl"] == 0.0
    assert s["win_rate"] is None
    assert s["profit_factor"] is None
    assert s["expectancy_per_trade"] is None
    assert result["equity_curve"] == []


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    result = report.build_report(tmp_path / "nonexistent.json")
    assert result["summary"]["post_hardening_trades"] == 0
    assert result["equity_curve"] == []


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def test_duplicate_closed_trade_deduped_by_order_id(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    # Two records with same alpaca_order_id — second has more fields populated
    t1 = _closed("t1", "order-abc", "2026-06-29", "2026-06-29", 500.0)
    t2 = {**_closed("t1-dup", "order-abc", "2026-06-29", "2026-06-29", 500.0), "contracts": None}
    _write(trades, [t1, t2])
    result = report.build_report(trades)
    # Only one trade should appear in equity curve
    assert result["summary"]["post_hardening_trades"] == 1
    assert len(result["equity_curve"]) == 1


def test_no_order_id_uses_trade_id_as_key(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    t = _closed("trade-xyz", "", "2026-06-29", "2026-06-29", 100.0)
    t["alpaca_order_id"] = None
    _write(trades, [t])
    result = report.build_report(trades)
    assert result["summary"]["post_hardening_trades"] == 1


# ---------------------------------------------------------------------------
# Deterministic sort
# ---------------------------------------------------------------------------

def test_missing_exit_timestamp_preserves_durable_source_order(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [
        _closed("b-trade", "o-b", "2026-06-29", "2026-06-29", 200.0),
        _closed("a-trade", "o-a", "2026-06-29", "2026-06-29", 100.0),
    ])
    result = report.build_report(trades)
    curve = result["equity_curve"]
    # "a-trade" < "b-trade" by id → a first
    assert curve[0]["trade_id"] == "b-trade"
    assert curve[0]["cumulative_pnl"] == 200.0
    assert curve[1]["cumulative_pnl"] == 300.0


def test_same_exit_date_sorted_by_exit_timestamp(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    later = _closed("a-trade", "o-a", "2026-06-29", "2026-06-29", 200.0)
    later["exit_at"] = "2026-06-29T16:00:00Z"
    earlier = _closed("b-trade", "o-b", "2026-06-29", "2026-06-29", 100.0)
    earlier["exit_at"] = "2026-06-29T15:00:00Z"
    _write(trades, [later, earlier])

    curve = report.build_report(trades)["equity_curve"]

    assert curve[0]["trade_id"] == "b-trade"
    assert curve[0]["cumulative_pnl"] == 100.0
    assert curve[1]["cumulative_pnl"] == 300.0


def test_initial_loss_has_no_profit_peak_percentage_denominator(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [_closed("loss", "o-loss", "2026-06-29", "2026-06-29", -100.0)])

    summary = report.build_report(trades)["summary"]

    assert summary["max_drawdown_dollars"] == -100.0
    assert summary["max_drawdown_pct"] is None
    assert summary["account_equity_drawdown_available"] is False


def test_breakeven_is_not_counted_as_loss(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [
        _closed("win", "o-win", "2026-06-29", "2026-06-29", 100.0),
        _closed("flat", "o-flat", "2026-06-30", "2026-06-30", 0.0),
    ])

    summary = report.build_report(trades)["summary"]

    assert summary["wins"] == 1
    assert summary["losses"] == 0
    assert summary["breakevens"] == 1


def test_nonfinite_pnl_is_skipped(tmp_path: Path) -> None:
    trades = tmp_path / "flip-trades.json"
    _write(trades, [_closed("bad", "o-bad", "2026-06-29", "2026-06-29", float("nan"))])

    result = report.build_report(trades)

    assert result["summary"]["post_hardening_trades"] == 0
    assert result["summary"]["skipped_no_pnl_count"] == 1


# ---------------------------------------------------------------------------
# Live data sanity: remains valid as new post-hardening trades accumulate
# ---------------------------------------------------------------------------

def test_live_data_report_remains_sane_as_trades_accumulate() -> None:
    """Validate durable invariants without freezing a growing runtime dataset."""
    trades_path = Path.home() / ".vibe-trading" / "flip-trades.json"
    if not trades_path.exists():
        return  # skip in CI without runtime data
    result = report.build_report(trades_path)
    s = result["summary"]
    assert s["post_hardening_trades"] >= 10
    assert s["pre_hardening_excluded"] == 1
    assert s["wins"] >= 0
    assert 0.0 <= s["win_rate"] <= 1.0
    assert s["max_drawdown_dollars"] <= 0
    assert s["current_drawdown_dollars"] <= 0


# need pytest for approx
import pytest  # noqa: E402
