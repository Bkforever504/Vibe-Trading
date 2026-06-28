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
    purge_bars: int = 5       # bars dropped between IS/OOS in each WF fold (prevents leakage)


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


def _sharpe_ratio(daily_returns: pd.Series) -> float:
    """Annualized Sharpe ratio assuming daily bars (252 trading days/year)."""
    if len(daily_returns) < 2 or daily_returns.std() == 0:
        return 0.0
    return float((daily_returns.mean() / daily_returns.std()) * (252 ** 0.5))


def _equity_curve(
    ohlcv: pd.DataFrame,
    signals: pd.Series,
    slippage_pct: float,
    commission_pct: float,
) -> pd.Series:
    """Vectorized simulation. Signal shifts 1 bar — no same-bar fills."""
    pos = signals.reindex(ohlcv.index).fillna(0).shift(1).fillna(0)
    bar_ret = ohlcv["close"].pct_change().fillna(0)
    fill_cost = pos.diff().abs().fillna(0) * (slippage_pct + commission_pct) / 100
    strat_ret = pos * bar_ret - fill_cost
    return (1 + strat_ret).cumprod()


def _metrics_from_equity(equity: pd.Series, signals: pd.Series) -> dict:
    total_return = float((equity.iloc[-1] - 1) * 100)
    dd = (equity - equity.cummax()) / equity.cummax()
    max_dd = float(abs(dd.min()) * 100)
    trade_returns = _completed_trade_returns(equity, signals)
    wins = [r for r in trade_returns if r > 0]
    losses = [r for r in trade_returns if r < 0]
    avg_win = float(sum(wins) / len(wins) * 100) if wins else 0.0
    avg_loss = float(sum(losses) / len(losses) * 100) if losses else 0.0
    expectancy = float(sum(trade_returns) / len(trade_returns) * 100) if trade_returns else 0.0
    pos = _positions_from_signals(signals, equity.index)
    bar_ret = equity.pct_change().fillna(0)
    win_rate = float(len(wins) / len(trade_returns) * 100) if trade_returns else 0.0
    calmar = total_return / max_dd if max_dd > 0 else 0.0
    return {
        "total_return_pct": total_return,
        "profit_factor": _profit_factor(trade_returns),
        "max_drawdown_pct": max_dd,
        "trade_count": len(trade_returns),
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "expectancy_pct": expectancy,
        "max_consecutive_losses": _max_consecutive_losses(trade_returns),
        "time_in_market_pct": float((pos != 0).mean() * 100),
        "sharpe_ratio": _sharpe_ratio(bar_ret),
        "win_rate_pct": win_rate,
        "calmar_ratio": calmar,
    }


def _positions_from_signals(signals: pd.Series, index: pd.Index) -> pd.Series:
    return signals.reindex(index).fillna(0).shift(1).fillna(0)


def _completed_trade_returns(equity: pd.Series, signals: pd.Series) -> list[float]:
    pos = _positions_from_signals(signals, equity.index)
    trade_returns: list[float] = []
    entry_equity: float | None = None
    open_pos = 0.0

    for i, current_pos in enumerate(pos):
        current_pos = float(current_pos)
        prev_equity = float(equity.iloc[i - 1]) if i > 0 else 1.0

        if open_pos == 0 and current_pos != 0:
            entry_equity = prev_equity
            open_pos = current_pos
            continue

        if open_pos != 0 and current_pos != open_pos:
            if entry_equity and entry_equity > 0:
                trade_returns.append(float(equity.iloc[i] / entry_equity - 1))
            entry_equity = prev_equity if current_pos != 0 else None
            open_pos = current_pos

    if open_pos != 0 and entry_equity and entry_equity > 0:
        trade_returns.append(float(equity.iloc[-1] / entry_equity - 1))

    return trade_returns


def _max_consecutive_losses(trade_returns: list[float]) -> int:
    longest = 0
    current = 0
    for ret in trade_returns:
        if ret < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _profit_factor(trade_returns: list[float]) -> float:
    wins = [r for r in trade_returns if r > 0]
    losses = [r for r in trade_returns if r < 0]
    gross_win = float(sum(wins))
    gross_loss = float(abs(sum(losses)))
    if gross_loss > 0:
        return gross_win / gross_loss
    return 99.0 if gross_win > 0 else 0.0


def _walk_forward_pass_rate(
    strategy_fn: StrategyFn,
    ohlcv: pd.DataFrame,
    slippage_pct: float,
    commission_pct: float,
    oos_split: float,
    folds: int,
    purge_bars: int = 5,
) -> float:
    fold_size = len(ohlcv) // folds
    passes = 0
    valid = 0
    for i in range(folds):
        fold = ohlcv.iloc[i * fold_size: (i + 1) * fold_size]
        is_end = int(len(fold) * (1 - oos_split))
        # Purge gap prevents IS boundary bars from leaking into OOS evaluation.
        oos_start = min(is_end + purge_bars, len(fold))
        oos = fold.iloc[oos_start:]
        if len(oos) < 10:
            continue
        valid += 1
        # Pass full fold so indicators (EMA, ATR, etc.) have proper warmup bars.
        full_sig = strategy_fn(fold)
        oos_sig = full_sig.reindex(oos.index)
        oos_eq = _equity_curve(oos, oos_sig, slippage_pct, commission_pct)
        fold_pf = _profit_factor(_completed_trade_returns(oos_eq, oos_sig))
        if fold_pf > 1.0:
            passes += 1
    return passes / valid if valid > 0 else 0.0


def run_backtest(strategy_fn: StrategyFn, config: BacktestConfig) -> BacktestMetrics:
    """
    Download data, run IS + OOS backtest, walk-forward validate.
    Returns BacktestMetrics for pasting into the manifest.
    """
    ohlcv = fetch_ohlcv(config.symbol, config.start, config.end)
    return run_backtest_on_ohlcv(strategy_fn, ohlcv, config)


def run_backtest_on_ohlcv(strategy_fn: StrategyFn, ohlcv: pd.DataFrame, config: BacktestConfig) -> BacktestMetrics:
    """
    Run IS + OOS backtest and walk-forward validation on already-fetched OHLCV data.
    This lets sweep jobs reuse the same market data across many parameter rows.
    """
    split = int(len(ohlcv) * (1 - config.oos_split))
    is_data, oos_data = ohlcv.iloc[:split], ohlcv.iloc[split:]

    is_sig = strategy_fn(is_data)
    is_eq = _equity_curve(is_data, is_sig, config.slippage_pct, config.commission_pct)
    is_m = _metrics_from_equity(is_eq, is_sig)

    oos_sig = strategy_fn(oos_data)
    oos_eq = _equity_curve(oos_data, oos_sig, config.slippage_pct, config.commission_pct)
    oos_pf = _profit_factor(_completed_trade_returns(oos_eq, oos_sig))

    wf_rate = _walk_forward_pass_rate(
        strategy_fn, ohlcv,
        config.slippage_pct, config.commission_pct,
        config.oos_split, config.wf_folds,
        purge_bars=config.purge_bars,
    )

    return BacktestMetrics(
        total_return_pct=round(is_m["total_return_pct"], 2),
        profit_factor=round(min(is_m["profit_factor"], 99.0), 2),
        max_drawdown_pct=round(is_m["max_drawdown_pct"], 2),
        trade_count=is_m["trade_count"],
        out_of_sample_profit_factor=round(min(oos_pf, 99.0), 3),
        walk_forward_pass_rate=round(wf_rate, 3),
        avg_win_pct=round(is_m["avg_win_pct"], 3),
        avg_loss_pct=round(is_m["avg_loss_pct"], 3),
        expectancy_pct=round(is_m["expectancy_pct"], 3),
        max_consecutive_losses=is_m["max_consecutive_losses"],
        time_in_market_pct=round(is_m["time_in_market_pct"], 3),
        sharpe_ratio=round(is_m["sharpe_ratio"], 3),
        win_rate_pct=round(is_m["win_rate_pct"], 3),
        calmar_ratio=round(is_m["calmar_ratio"], 3),
    )
