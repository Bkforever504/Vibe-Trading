"""
Standalone momentum-rotation backtester for the Pine Strategy Lab pipeline.

Strategy: rank a universe of ETFs by N-month trailing return every M trading
days (monthly by default). Hold the top-ranked asset. If the top asset has
negative momentum, rotate to cash instead.

Returns BacktestMetrics using the same schema as pine_strategy_lab_backtest.py
so evaluate_candidate() and the existing gate system apply unchanged.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import pandas as pd

from research.pine_strategy_lab import BacktestMetrics

Position = tuple[str, ...] | None


@dataclass(frozen=True)
class MomentumConfig:
    symbols: list[str]
    start: str
    end: str
    lookback_months: int = 12
    rebalance_days: int = 21
    top_n: int = 1
    slippage_pct: float = 0.05
    commission_pct: float = 0.01
    oos_split: float = 0.20
    wf_folds: int = 5
    purge_bars: int = 5


def fetch_universe(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    """Download close prices for all symbols, return date-aligned wide DataFrame."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError("yfinance required: uv add yfinance") from exc

    frames: dict[str, pd.Series] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for sym in symbols:
            df = yf.download(sym, start=start, end=end, progress=False, auto_adjust=True)
            if df.empty:
                raise ValueError(f"No price data for {sym} {start}:{end}")
            df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
            frames[sym] = df["close"]

    universe = pd.DataFrame(frames).dropna()
    return universe


def _momentum_signal(
    universe: pd.DataFrame,
    lookback_days: int,
    rebalance_days: int = 21,
    top_n: int = 1,
) -> pd.Series:
    """
    Monthly-rebalanced momentum signal.

    Returns a Series of selected asset tuples or None (cash) at each bar.
    Signal is determined on the rebalance bar and held forward until the next
    rebalance. None during the warmup period (first lookback_days bars).
    """
    signal: list[object] = [None] * len(universe)
    momentum = universe.pct_change(lookback_days)
    current_hold: Position = None
    last_rebalance = -rebalance_days  # trigger rebalance on first eligible bar

    for i in range(lookback_days, len(universe)):
        if i - last_rebalance >= rebalance_days:
            m = momentum.iloc[i].dropna()
            if m.empty:
                current_hold = None
            else:
                ranked = m.sort_values(ascending=False)
                positive = ranked[ranked > 0]
                current_hold = tuple(positive.index[:max(1, top_n)]) if not positive.empty else None
            last_rebalance = i
        signal[i] = current_hold

    return pd.Series(signal, index=universe.index, dtype=object)


def _normalize_position(raw: object) -> Position:
    if raw is None:
        return None
    if isinstance(raw, float) and pd.isna(raw):
        return None
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, tuple):
        position = tuple(str(item) for item in raw if item is not None)
        return position or None
    if isinstance(raw, list):
        position = tuple(str(item) for item in raw if item is not None)
        return position or None
    return None


def _momentum_equity_curve(
    universe: pd.DataFrame,
    signal: pd.Series,
    slippage_pct: float,
    commission_pct: float,
) -> pd.Series:
    """
    Equity curve for momentum rotation. Signal shifts 1 bar — fills at next open.
    Each asset-switch rebalance pays slippage + commission.
    """
    pos = signal.shift(1).map(_normalize_position)
    returns = universe.pct_change().fillna(0)

    portfolio_ret = pd.Series(0.0, index=universe.index)
    for dt, position in pos.items():
        if not position:
            continue
        weight = 1.0 / len(position)
        portfolio_ret.loc[dt] = sum(
            float(returns.loc[dt, asset]) * weight
            for asset in position
            if asset in returns.columns
        )

    encoded = pos.fillna("__cash__")
    rebalance = (encoded != encoded.shift(1, fill_value="__start__")).astype(float)
    rebalance.iloc[0] = 0.0
    fill_cost = rebalance * (slippage_pct + commission_pct) / 100

    return (1 + portfolio_ret - fill_cost).cumprod()


def _completed_trade_returns(equity: pd.Series, signal: pd.Series) -> list[float]:
    """Return for each uninterrupted holding period (one asset from entry to exit)."""
    pos = signal.shift(1).map(_normalize_position)
    trade_returns: list[float] = []
    entry_equity: float | None = None
    current_asset: Position = None

    for i in range(len(pos)):
        asset = pos.iloc[i]
        eq = float(equity.iloc[i])

        if current_asset is None and asset is not None:
            current_asset = asset
            entry_equity = eq
        elif current_asset is not None and asset != current_asset:
            if entry_equity and entry_equity > 0:
                trade_returns.append(eq / entry_equity - 1)
            if asset is not None:
                current_asset = asset
                entry_equity = eq
            else:
                current_asset = None
                entry_equity = None

    if current_asset is not None and entry_equity and entry_equity > 0:
        trade_returns.append(float(equity.iloc[-1]) / entry_equity - 1)

    return trade_returns


def _sharpe_ratio(daily_returns: pd.Series) -> float:
    if len(daily_returns) < 2 or daily_returns.std() == 0:
        return 0.0
    return float((daily_returns.mean() / daily_returns.std()) * (252 ** 0.5))


def _profit_factor(trade_returns: list[float]) -> float:
    wins = [r for r in trade_returns if r > 0]
    losses = [r for r in trade_returns if r < 0]
    gross_win = float(sum(wins))
    gross_loss = float(abs(sum(losses)))
    if gross_loss > 0:
        return gross_win / gross_loss
    return 99.0 if gross_win > 0 else 0.0


def _max_consecutive_losses(trade_returns: list[float]) -> int:
    longest, current = 0, 0
    for r in trade_returns:
        if r < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _metrics_from_equity(equity: pd.Series, signal: pd.Series) -> dict:
    total_return = float((equity.iloc[-1] - 1) * 100)
    dd = (equity - equity.cummax()) / equity.cummax()
    max_dd = float(abs(dd.min()) * 100)
    trade_returns = _completed_trade_returns(equity, signal)
    wins = [r for r in trade_returns if r > 0]
    losses = [r for r in trade_returns if r < 0]
    avg_win = float(sum(wins) / len(wins) * 100) if wins else 0.0
    avg_loss = float(sum(losses) / len(losses) * 100) if losses else 0.0
    expectancy = float(sum(trade_returns) / len(trade_returns) * 100) if trade_returns else 0.0
    win_rate = float(len(wins) / len(trade_returns) * 100) if trade_returns else 0.0
    calmar = total_return / max_dd if max_dd > 0 else 0.0
    bar_ret = equity.pct_change().fillna(0)
    pos = signal.shift(1).map(_normalize_position)
    time_in_market = float(pos.map(lambda item: item is not None).mean() * 100)
    return {
        "total_return_pct": total_return,
        "profit_factor": _profit_factor(trade_returns),
        "max_drawdown_pct": max_dd,
        "trade_count": len(trade_returns),
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "expectancy_pct": expectancy,
        "max_consecutive_losses": _max_consecutive_losses(trade_returns),
        "time_in_market_pct": time_in_market,
        "sharpe_ratio": _sharpe_ratio(bar_ret),
        "win_rate_pct": win_rate,
        "calmar_ratio": calmar,
    }


def _wf_pass_rate(
    universe: pd.DataFrame,
    lookback_days: int,
    rebalance_days: int,
    top_n: int,
    slippage_pct: float,
    commission_pct: float,
    oos_split: float,
    folds: int,
    purge_bars: int,
) -> float:
    fold_size = len(universe) // folds
    passes, valid = 0, 0
    for i in range(folds):
        fold = universe.iloc[i * fold_size: (i + 1) * fold_size]
        is_end = int(len(fold) * (1 - oos_split))
        oos_start = min(is_end + purge_bars, len(fold))
        oos = fold.iloc[oos_start:]
        if len(oos) < 10:
            continue
        valid += 1
        full_sig = _momentum_signal(fold, lookback_days, rebalance_days, top_n)
        oos_sig = full_sig.reindex(oos.index)
        oos_eq = _momentum_equity_curve(oos, oos_sig, slippage_pct, commission_pct)
        fold_pf = _profit_factor(_completed_trade_returns(oos_eq, oos_sig))
        if fold_pf > 1.0:
            passes += 1
    return passes / valid if valid > 0 else 0.0


def run_momentum_backtest(
    config: MomentumConfig,
    universe: pd.DataFrame | None = None,
) -> BacktestMetrics:
    """
    Full momentum rotation backtest: IS metrics + OOS profit factor + walk-forward.
    Pass a pre-fetched universe DataFrame to avoid repeated downloads across configs.
    """
    if universe is None:
        universe = fetch_universe(config.symbols, config.start, config.end)

    lookback_days = config.lookback_months * 21
    split = int(len(universe) * (1 - config.oos_split))
    is_data = universe.iloc[:split]
    oos_data = universe.iloc[split:]

    is_sig = _momentum_signal(is_data, lookback_days, config.rebalance_days, config.top_n)
    is_eq = _momentum_equity_curve(is_data, is_sig, config.slippage_pct, config.commission_pct)
    is_m = _metrics_from_equity(is_eq, is_sig)

    # OOS signal uses full dataset for lookback warmup; equity evaluated on OOS slice only.
    full_sig = _momentum_signal(universe, lookback_days, config.rebalance_days, config.top_n)
    oos_sig = full_sig.reindex(oos_data.index)
    oos_eq = _momentum_equity_curve(oos_data, oos_sig, config.slippage_pct, config.commission_pct)
    oos_pf = _profit_factor(_completed_trade_returns(oos_eq, oos_sig))

    wf_rate = _wf_pass_rate(
        universe, lookback_days, config.rebalance_days, config.top_n,
        config.slippage_pct, config.commission_pct,
        config.oos_split, config.wf_folds, config.purge_bars,
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
