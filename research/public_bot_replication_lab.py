#!/usr/bin/env python3
"""Compare public bot mechanisms on one frozen liquid-ETF dataset.

This is a mechanism replication, not a claim that the source projects publish
profitable bots. Signals are delayed one full daily bar and all results are for
underlying ETFs, never options.
"""
from __future__ import annotations

import argparse
import json
import math
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SYMBOLS = ("SPY", "QQQ", "GLD", "XLE", "TLT", "IWM", "XLK", "XLV", "XLF", "XLI")
TEST_START = "2025-01-01"
DEFAULT_OUTPUT = Path.home() / ".vibe-trading" / "reports" / "public-bot-replication-lab.json"


def fetch_ohlc(symbols: tuple[str, ...], start: str, end: str) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    result: dict[str, pd.DataFrame] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for symbol in symbols:
            frame = yf.download(symbol, start=start, end=end, auto_adjust=True, progress=False)
            if frame.empty:
                raise ValueError(f"No price data for {symbol} {start}:{end}")
            frame.columns = [str(col[0] if isinstance(col, tuple) else col).lower() for col in frame.columns]
            result[symbol] = frame[["open", "high", "low", "close", "volume"]].dropna()
    shared = result[symbols[0]].index
    for symbol in symbols[1:]:
        shared = shared.intersection(result[symbol].index)
    return {symbol: frame.reindex(shared).dropna() for symbol, frame in result.items()}


def ema_cross_signal(close: pd.Series, fast: int = 20, slow: int = 60, tolerance: float = 0.001) -> pd.Series:
    fast_ema = close.ewm(span=fast, adjust=False).mean()
    slow_ema = close.ewm(span=slow, adjust=False).mean()
    return (fast_ema > slow_ema * (1.0 + tolerance)).astype(float)


def sma_regime_signal(close: pd.Series, window: int = 200) -> pd.Series:
    return (close > close.rolling(window).mean()).astype(float)


def donchian_signal(frame: pd.DataFrame, entry: int = 55, exit: int = 10) -> pd.Series:
    prior_high = frame["high"].rolling(entry).max().shift(1)
    prior_exit_low = frame["low"].rolling(exit).min().shift(1)
    position = 0.0
    values: list[float] = []
    for close, high_level, low_level in zip(frame["close"], prior_high, prior_exit_low):
        if position == 0.0 and pd.notna(high_level) and close > high_level:
            position = 1.0
        elif position == 1.0 and pd.notna(low_level) and close < low_level:
            position = 0.0
        values.append(position)
    return pd.Series(values, index=frame.index, dtype=float)


def dual_momentum_weights(close: pd.DataFrame, lookback: int = 252, rebalance_days: int = 5, top_n: int = 2) -> pd.DataFrame:
    momentum = close.pct_change(lookback)
    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    current: list[str] = []
    last_rebalance = -rebalance_days
    for index in range(lookback, len(close)):
        if index - last_rebalance >= rebalance_days:
            ranked = momentum.iloc[index].dropna().sort_values(ascending=False)
            current = list(ranked[ranked > 0].index[:top_n])
            last_rebalance = index
        if current:
            weights.iloc[index, weights.columns.get_indexer(current)] = 1.0 / len(current)
    return weights


def _weights_from_signal(signal: pd.Series, columns: list[str], symbol: str) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=signal.index, columns=columns)
    weights[symbol] = signal
    return weights


def _equal_active_weights(signals: pd.DataFrame) -> pd.DataFrame:
    active = signals.sum(axis=1).replace(0.0, np.nan)
    return signals.div(active, axis=0).fillna(0.0)


def portfolio_returns(close: pd.DataFrame, signal_weights: pd.DataFrame, cost_bps: float) -> tuple[pd.Series, dict[str, float]]:
    # A close-t signal first applies to close(t+1)-to-close(t+2), avoiding a
    # same-close fill assumption. This is a conservative one-full-bar delay.
    executable = signal_weights.shift(2).fillna(0.0)
    asset_returns = close.pct_change().fillna(0.0)
    gross = (executable * asset_returns).sum(axis=1)
    turnover = executable.diff().abs().sum(axis=1).fillna(executable.abs().sum(axis=1))
    cost = turnover * cost_bps / 10_000.0
    return gross - cost, {
        "total_turnover": round(float(turnover.sum()), 4),
        "modeled_cost_return_pct": round(float(cost.sum() * 100.0), 4),
    }


def block_bootstrap_total_return(returns: pd.Series, block: int = 20, samples: int = 1000, seed: int = 20260719) -> dict[str, float | int | None]:
    values = returns.dropna().to_numpy(dtype=float)
    if len(values) < block * 2:
        return {"samples": 0, "lower_95_total_return_pct": None, "median_total_return_pct": None, "upper_95_total_return_pct": None}
    rng = np.random.default_rng(seed)
    totals = np.empty(samples)
    starts_max = len(values) - block + 1
    blocks_needed = math.ceil(len(values) / block)
    for sample in range(samples):
        starts = rng.integers(0, starts_max, size=blocks_needed)
        path = np.concatenate([values[start : start + block] for start in starts])[: len(values)]
        totals[sample] = (np.prod(1.0 + path) - 1.0) * 100.0
    low, median, high = np.percentile(totals, [2.5, 50.0, 97.5])
    return {
        "samples": samples,
        "lower_95_total_return_pct": round(float(low), 3),
        "median_total_return_pct": round(float(median), 3),
        "upper_95_total_return_pct": round(float(high), 3),
    }


def metrics(returns: pd.Series) -> dict[str, Any]:
    clean = returns.fillna(0.0)
    equity = (1.0 + clean).cumprod()
    total = float((equity.iloc[-1] - 1.0) * 100.0) if len(equity) else 0.0
    drawdown = equity / equity.cummax() - 1.0
    std = float(clean.std())
    sharpe = float(clean.mean() / std * math.sqrt(252.0)) if std > 0 else 0.0
    years = max(len(clean) / 252.0, 1.0 / 252.0)
    cagr = float((equity.iloc[-1] ** (1.0 / years) - 1.0) * 100.0) if len(equity) and equity.iloc[-1] > 0 else -100.0
    yearly = {str(year): round(float((1.0 + group).prod() - 1.0) * 100.0, 3) for year, group in clean.groupby(clean.index.year)}
    return {
        "total_return_pct": round(total, 3),
        "cagr_pct": round(cagr, 3),
        "sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(float(abs(drawdown.min()) * 100.0), 3),
        "positive_day_rate": round(float((clean > 0).mean()), 4),
        "yearly_return_pct": yearly,
    }


def evaluate_strategy(close: pd.DataFrame, weights: pd.DataFrame, cost_bps: float) -> dict[str, Any]:
    returns, execution = portfolio_returns(close, weights, cost_bps)
    development = returns.loc[returns.index < TEST_START]
    forward = returns.loc[returns.index >= TEST_START]
    return {
        "development_through_2024": metrics(development),
        "forward_2025_plus": {**metrics(forward), "moving_block_bootstrap": block_bootstrap_total_return(forward)},
        "full_period_execution": execution,
    }


def build_report(data: dict[str, pd.DataFrame], cost_bps: float = 6.0) -> dict[str, Any]:
    close = pd.DataFrame({symbol: data[symbol]["close"] for symbol in SYMBOLS}).dropna()
    columns = list(close.columns)
    strategies: dict[str, pd.DataFrame] = {}
    strategies["spy_buy_and_hold_benchmark"] = _weights_from_signal(pd.Series(1.0, index=close.index), columns, "SPY")
    strategies["quantconnect_ema20_60_spy_mechanism"] = _weights_from_signal(ema_cross_signal(close["SPY"]), columns, "SPY")
    strategies["spy_sma200_long_cash"] = _weights_from_signal(sma_regime_signal(close["SPY"]), columns, "SPY")
    turtle_signals = pd.DataFrame({symbol: donchian_signal(data[symbol]).reindex(close.index).fillna(0.0) for symbol in SYMBOLS})
    strategies["diversified_turtle55_10_long_cash_mechanism"] = _equal_active_weights(turtle_signals)
    momentum_weights = dual_momentum_weights(close)
    strategies["frozen_dual_momentum_252_top2"] = momentum_weights
    strategies["micro_account_50pct_dual_momentum_50pct_cash"] = momentum_weights * 0.50

    rows = []
    for name, weights in strategies.items():
        base = evaluate_strategy(close, weights, cost_bps)
        stressed = evaluate_strategy(close, weights, cost_bps * 2.0)
        row = {
            "strategy": name,
            "base_cost_bps_per_unit_turnover": cost_bps,
            **base,
            "double_cost_forward_2025_plus": stressed["forward_2025_plus"],
            "promotion_eligible": False,
        }
        rows.append(row)
    rows.sort(key=lambda row: float(row["forward_2025_plus"]["total_return_pct"]), reverse=True)
    return {
        "provider": "public_bot_replication_lab",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "data_coverage": {"start": str(close.index.min().date()), "end": str(close.index.max().date())},
        "frozen_test_start": TEST_START,
        "strategies": rows,
        "source_notes": [
            "The EMA 20/60 with 0.1% tolerance reproduces the signal mechanism in QuantConnect LEAN's Apache-2.0 FuturesMomentumAlgorithm example, but trades SPY underlying here.",
            "The Donchian 55/10 row reproduces the public Turtle breakout/exit mechanism with equal active-ETF weights; it is not an exact port of ATR sizing, pyramiding, or futures execution.",
            "Freqtrade's official documentation says generated examples are not profitable out of the box, so no sample strategy was promoted as a top bot.",
            "Hummingbot market making requires order-book, maker-fill, fee-tier, adverse-selection, and inventory data unavailable in this ETF dataset.",
            "FinRL is a research framework rather than a frozen profitable policy; selecting an agent after seeing this holdout would contaminate the test.",
        ],
        "warnings": [
            "Adjusted yfinance ETF bars are not venue-level executable data.",
            "All entries are delayed one full daily bar and include turnover costs, but taxes and market impact are omitted.",
            "These are underlying returns. Options require separate contract-level bid/ask replay.",
            "The 2025+ extension is consumed evidence after this run and cannot be called untouched again.",
            "GitHub stars, community trading volume, and framework maturity do not establish strategy profitability.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2026-07-20")
    parser.add_argument("--cost-bps", type=float, default=6.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report(fetch_ohlc(SYMBOLS, args.start, args.end), args.cost_bps)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for row in report["strategies"]:
        forward = row["forward_2025_plus"]
        development = row["development_through_2024"]
        print(f"{row['strategy']}: dev={development['total_return_pct']:.1f}% forward={forward['total_return_pct']:.1f}% DD={forward['max_drawdown_pct']:.1f}% Sharpe={forward['sharpe']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
