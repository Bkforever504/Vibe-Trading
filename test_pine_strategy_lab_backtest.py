"""Tests for pine_strategy_lab_backtest. No network — yfinance is mocked."""
from __future__ import annotations

from unittest.mock import patch
import numpy as np
import pandas as pd
import pytest

from research.pine_strategy_lab import BacktestMetrics, evaluate_candidate, PineStrategyIdea, parse_pine_strategy
from research.pine_strategy_lab_backtest import (
    BacktestConfig,
    _equity_curve,
    _metrics_from_equity,
    _walk_forward_pass_rate,
    run_backtest,
)

_N = 300
_DATES = pd.date_range("2022-01-03", periods=_N, freq="B")


def _make_ohlcv(trend: float = 0.0003) -> pd.DataFrame:
    np.random.seed(42)
    close = 400 * np.cumprod(1 + np.random.normal(trend, 0.01, _N))
    df = pd.DataFrame({
        "open":   close * 0.999,
        "high":   close * 1.005,
        "low":    close * 0.995,
        "close":  close,
        "volume": np.random.randint(1_000_000, 5_000_000, _N).astype(float),
    }, index=_DATES)
    return df


def _always_long(ohlcv: pd.DataFrame) -> pd.Series:
    return pd.Series(1, index=ohlcv.index, dtype=int)


def _always_flat(ohlcv: pd.DataFrame) -> pd.Series:
    return pd.Series(0, index=ohlcv.index, dtype=int)


# ── equity curve ───────────────────────────────────────────────────────────────

def test_equity_curve_flat_stays_at_one():
    ohlcv = _make_ohlcv()
    signals = _always_flat(ohlcv)
    eq = _equity_curve(ohlcv, signals, 0.05, 0.01)
    assert abs(eq.iloc[-1] - 1.0) < 0.01


def test_equity_curve_long_trending_market_grows():
    ohlcv = _make_ohlcv(trend=0.001)
    signals = _always_long(ohlcv)
    eq = _equity_curve(ohlcv, signals, 0.05, 0.01)
    assert eq.iloc[-1] > 1.0


def test_equity_curve_no_lookahead_signal_shifted():
    ohlcv = _make_ohlcv()
    # Signal flips at bar 5. After shift, position at bar 5 is still 0
    # (bar 4's signal). With zero costs, equity at bar 5 == equity at bar 4.
    signals = pd.Series(0, index=ohlcv.index, dtype=int)
    signals.iloc[5:] = 1
    eq = _equity_curve(ohlcv, signals, 0.0, 0.0)
    assert eq.iloc[5] == pytest.approx(eq.iloc[4], rel=1e-6)


# ── metrics ────────────────────────────────────────────────────────────────────

def test_metrics_trade_count_nonzero_for_active_strategy():
    ohlcv = _make_ohlcv()
    signals = pd.Series([1, 0] * (_N // 2), index=ohlcv.index, dtype=int)
    eq = _equity_curve(ohlcv, signals, 0.05, 0.01)
    m = _metrics_from_equity(eq, signals)
    assert m["trade_count"] > 0


def test_metrics_max_dd_nonnegative():
    ohlcv = _make_ohlcv(trend=-0.001)
    signals = _always_long(ohlcv)
    eq = _equity_curve(ohlcv, signals, 0.05, 0.01)
    m = _metrics_from_equity(eq, signals)
    assert m["max_drawdown_pct"] >= 0


# ── walk-forward ───────────────────────────────────────────────────────────────

def test_walk_forward_flat_strategy_low_pass_rate():
    ohlcv = _make_ohlcv(trend=0.0)
    rate = _walk_forward_pass_rate(_always_flat, ohlcv, 0.05, 0.01, 0.20, 5)
    assert rate == 0.0


# ── run_backtest with mocked yfinance ─────────────────────────────────────────

def test_run_backtest_returns_backtest_metrics():
    ohlcv = _make_ohlcv(trend=0.0004)
    with patch("research.pine_strategy_lab_backtest.fetch_ohlcv", return_value=ohlcv):
        config = BacktestConfig(symbol="SPY", start="2022-01-01", end="2024-01-01")
        result = run_backtest(_always_long, config)
    assert isinstance(result, BacktestMetrics)
    assert result.trade_count >= 0
    assert result.max_drawdown_pct >= 0
    assert 0.0 <= result.walk_forward_pass_rate <= 1.0


def test_run_backtest_result_passable_to_evaluate_candidate():
    ohlcv = _make_ohlcv(trend=0.0005)
    with patch("research.pine_strategy_lab_backtest.fetch_ohlcv", return_value=ohlcv):
        config = BacktestConfig(symbol="IWM", start="2022-01-01", end="2024-01-01")
        metrics = run_backtest(_always_long, config)
    idea = PineStrategyIdea(name="TestStrategy", license="MIT")
    result = evaluate_candidate(idea, metrics)
    assert result.status in {"paper_candidate", "rejected"}
    assert 0.0 <= result.confidence_score <= 10.0


# ── license regex fixes ────────────────────────────────────────────────────────

def test_parse_pine_at_license_annotation():
    source = "//@version=5\n// @license MIT\nstrategy('Test')\nvwap = ta.vwap(hlc3)\n"
    idea = parse_pine_strategy(source)
    assert idea.is_open_source is True
    assert idea.license.lower() == "mit"


def test_parse_pine_mozilla_full_text():
    source = "//@version=5\n// This source is subject to the Mozilla Public License 2.0\nstrategy('Test')\n"
    idea = parse_pine_strategy(source)
    assert idea.is_open_source is True


def test_parse_pine_gpl_short_sentence():
    source = "//@version=4\n// Script may be freely distributed under the terms of the GPL-3.0 license.\nstudy('Test')\n"
    idea = parse_pine_strategy(source)
    assert idea.license == "gpl-3.0"
    assert idea.is_open_source is True


def test_parse_pine_unknown_license_rejected():
    source = "//@version=5\nstrategy('NoLicense')\nrsi = ta.rsi(close, 14)\n"
    idea = parse_pine_strategy(source)
    assert idea.is_open_source is False
    assert idea.license == "unknown"
