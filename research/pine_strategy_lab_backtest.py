"""
Pine Strategy Lab — equity backtester.

Runs a manually-translated Python strategy against real OHLCV data
and produces BacktestMetrics ready to paste into the manifest.

Usage (see scripts/pine_backtest_runner.py for the CLI).
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from research.pine_strategy_lab import BacktestMetrics

# Match slippage/commission constants from strategies/backtest.py
_DEFAULT_SLIPPAGE_PCT = 0.05   # 5 bps per fill
_DEFAULT_COMMISSION_PCT = 0.01  # 1 bp per fill (equity; options uses per-contract)

StrategyFn = Callable[[pd.DataFrame], pd.Series]
"""Takes OHLCV DataFrame (columns: open,high,low,close,volume).
Returns Series of integer signals aligned to df.index: 1=long, 0=flat, -1=short.
Signal is applied on the *next* bar to prevent lookahead."""


@dataclass(frozen=True)
class BacktestConfig:
    symbol: str
    start: str            # "YYYY-MM-DD"
    end: str              # "YYYY-MM-DD"
    slippage_pct: float = _DEFAULT_SLIPPAGE_PCT
    commission_pct: float = _DEFAULT_COMMISSION_PCT
    oos_split: float = 0.20   # fraction of data held out for OOS
    wf_folds: int = 5


def fetch_ohlcv(symbol: str, start: str, end: str) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError("yfinance required: uv add yfinance") from exc
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(symbol, start=start, end=end, progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No price data for {symbol} {start}:{end}")
    df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]].copy()


def _equity_curve(
    ohlcv: pd.DataFrame,
    signals: pd.Series,
    slippage_pct: float,
    commission_pct: float,
) -> pd.Series:
    """Vectorized simulation. Signal shifts 1 bar — no same-bar fills."""
    pos = signals.reindex(ohlcv.index).fillna(0).shift(1).fillna(0)
    bar_ret = ohlcv["close"].pct_change().fillna(0)
    fill_cost = pos.diff().abs() * (slippage_pct + commission_pct) / 100
    strat_ret = pos * bar_ret - fill_cost
    return (1 + strat_ret).cumprod()


def _metrics_from_equity(equity: pd.Series, signals: pd.Series) -> dict:
    total_return = float((equity.iloc[-1] - 1) * 100)
    dd = (equity - equity.cummax()) / equity.cummax()
    max_dd = float(abs(dd.min()) * 100)
    trade_count = int((signals.reindex(equity.index).diff().abs() > 0).sum())
    bar_ret = equity.pct_change().dropna()
    wins = float(bar_ret[bar_ret > 0].sum())
    losses = float(abs(bar_ret[bar_ret < 0].sum()))
    pf = wins / losses if losses > 0 else 99.0
    return {"total_return_pct": total_return, "profit_factor": pf,
            "max_drawdown_pct": max_dd, "trade_count": trade_count}


def _walk_forward_pass_rate(
    strategy_fn: StrategyFn,
    ohlcv: pd.DataFrame,
    slippage_pct: float,
    commission_pct: float,
    oos_split: float,
    folds: int,
) -> float:
    fold_size = len(ohlcv) // folds
    passes = 0
    valid = 0
    for i in range(folds):
        fold = ohlcv.iloc[i * fold_size: (i + 1) * fold_size]
        split = int(len(fold) * (1 - oos_split))
        test = fold.iloc[split:]
        if len(test) < 10:
            continue
        valid += 1
        sig = strategy_fn(test)
        eq = _equity_curve(test, sig, slippage_pct, commission_pct)
        bar_ret = eq.pct_change().dropna()
        w = float(bar_ret[bar_ret > 0].sum())
        l = float(abs(bar_ret[bar_ret < 0].sum()))
        fold_pf = w / l if l > 0 else (0.0 if w == 0 else 99.0)
        if fold_pf > 1.0:
            passes += 1
    return passes / valid if valid > 0 else 0.0


def run_backtest(strategy_fn: StrategyFn, config: BacktestConfig) -> BacktestMetrics:
    """
    Download data, run IS + OOS backtest, walk-forward validate.
    Returns BacktestMetrics for pasting into the manifest.
    """
    ohlcv = fetch_ohlcv(config.symbol, config.start, config.end)
    split = int(len(ohlcv) * (1 - config.oos_split))
    is_data, oos_data = ohlcv.iloc[:split], ohlcv.iloc[split:]

    is_sig = strategy_fn(is_data)
    is_eq = _equity_curve(is_data, is_sig, config.slippage_pct, config.commission_pct)
    is_m = _metrics_from_equity(is_eq, is_sig)

    oos_sig = strategy_fn(oos_data)
    oos_eq = _equity_curve(oos_data, oos_sig, config.slippage_pct, config.commission_pct)
    oos_ret = oos_eq.pct_change().dropna()
    oos_w = float(oos_ret[oos_ret > 0].sum())
    oos_l = float(abs(oos_ret[oos_ret < 0].sum()))
    oos_pf = oos_w / oos_l if oos_l > 0 else 99.0

    wf_rate = _walk_forward_pass_rate(
        strategy_fn, ohlcv,
        config.slippage_pct, config.commission_pct,
        config.oos_split, config.wf_folds,
    )

    return BacktestMetrics(
        total_return_pct=round(is_m["total_return_pct"], 2),
        profit_factor=round(min(is_m["profit_factor"], 99.0), 2),
        max_drawdown_pct=round(is_m["max_drawdown_pct"], 2),
        trade_count=is_m["trade_count"],
        out_of_sample_profit_factor=round(min(oos_pf, 99.0), 3),
        walk_forward_pass_rate=round(wf_rate, 3),
    )
