#!/usr/bin/env python3
"""Read-only tournament for the five strategy families in the PyQuant post.

Signals are formed from adjusted closes, executed one trading day later, and
charged explicit turnover costs. The module has no broker imports or execution
authority. FX carry is intentionally excluded until point-in-time rates and
forward returns are available.
"""
from __future__ import annotations

import argparse
import json
import math
import warnings
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "pyquant_strategy_family_results.json"
START = "2007-01-01"
COST_PER_TRADED_NOTIONAL = 0.0006

ASSET_CLASSES = ("SPY", "EFA", "VNQ", "GLD", "DBC", "TLT")
SECTORS = ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY")
LOW_VOL_ETFS = ("SPLV", "USMV")
CANONICAL = ("SPY", "QQQ", "GLD", "XLE", "TLT", "IWM", "XLK", "XLV", "XLF", "XLI")
ALL_SYMBOLS = tuple(dict.fromkeys((*ASSET_CLASSES, *SECTORS, *LOW_VOL_ETFS, *CANONICAL)))


def fetch_closes(symbols: tuple[str, ...] = ALL_SYMBOLS, start: str = START) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required for the research download") from exc

    frames: dict[str, pd.Series] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for symbol in symbols:
            frame = yf.download(symbol, start=start, auto_adjust=True, progress=False)
            if frame.empty:
                raise ValueError(f"no data returned for {symbol}")
            frame.columns = [column.lower() if isinstance(column, str) else column[0].lower() for column in frame.columns]
            frames[symbol] = frame["close"].astype(float)
    return pd.DataFrame(frames).sort_index()


def _monthly_rebalance(index: pd.DatetimeIndex) -> pd.Series:
    periods = pd.Series(index.to_period("M"), index=index)
    return periods.ne(periods.shift(-1)).fillna(True)


def _scheduled_rank_weights(
    closes: pd.DataFrame,
    *,
    lookback: int,
    top_n: int,
    rebalance_days: int | None,
    lowest: bool = False,
    eligibility: pd.DataFrame | None = None,
) -> pd.DataFrame:
    score = closes.pct_change(lookback)
    if lowest:
        score = closes.pct_change().rolling(lookback).std() * math.sqrt(252)
    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    current = pd.Series(0.0, index=closes.columns)
    monthly = _monthly_rebalance(closes.index)
    for offset, timestamp in enumerate(closes.index):
        should_rebalance = bool(monthly.loc[timestamp]) if rebalance_days is None else (
            offset >= lookback and (offset - lookback) % rebalance_days == 0
        )
        if should_rebalance and offset >= lookback:
            row = score.loc[timestamp].dropna()
            if eligibility is not None:
                allowed = eligibility.loc[timestamp].reindex(row.index).fillna(False)
                row = row[allowed]
            elif not lowest:
                row = row[row > 0]
            ranked = row.sort_values(ascending=lowest)
            selected = list(ranked.index[:top_n])
            current = pd.Series(0.0, index=closes.columns)
            if selected:
                current.loc[selected] = 1.0 / len(selected)
        weights.loc[timestamp] = current
    return weights


def smooth_momentum_proxy_weights(
    closes: pd.DataFrame,
    *,
    lookback: int = 252,
    skip_recent: int = 21,
    top_n: int = 2,
    shortlist_multiple: int = 3,
) -> pd.DataFrame:
    """Select persistent winners, not assets dominated by one recent jump.

    This is a transparent ETF-universe proxy inspired by published
    quality-momentum/frog-in-the-pan research. It is not a replication of any
    proprietary fund. The signal first shortlists positive 12-1 momentum, then
    prefers the highest share of positive daily returns over that same window.
    """
    if lookback <= skip_recent or skip_recent < 0:
        raise ValueError("lookback must exceed non-negative skip_recent")
    if top_n <= 0 or shortlist_multiple <= 0:
        raise ValueError("top_n and shortlist_multiple must be positive")

    momentum = closes.shift(skip_recent).div(closes.shift(lookback)).sub(1.0)
    daily_positive = closes.pct_change().gt(0).astype(float)
    smoothness = daily_positive.rolling(lookback - skip_recent).mean().shift(skip_recent)
    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    current = pd.Series(0.0, index=closes.columns)
    monthly = _monthly_rebalance(closes.index)
    for offset, timestamp in enumerate(closes.index):
        if bool(monthly.loc[timestamp]) and offset >= lookback:
            momentum_row = momentum.loc[timestamp].dropna()
            momentum_row = momentum_row[momentum_row > 0].sort_values(ascending=False)
            shortlist_size = min(len(momentum_row), max(top_n, top_n * shortlist_multiple))
            shortlist = list(momentum_row.index[:shortlist_size])
            selected: list[str] = []
            if shortlist:
                quality = pd.DataFrame({
                    "smoothness": smoothness.loc[timestamp, shortlist],
                    "momentum": momentum_row.reindex(shortlist),
                }).dropna()
                quality = quality.sort_values(
                    ["smoothness", "momentum"],
                    ascending=[False, False],
                    kind="mergesort",
                )
                selected = list(quality.index[:top_n])
            current = pd.Series(0.0, index=closes.columns)
            if selected:
                current.loc[selected] = 1.0 / len(selected)
        weights.loc[timestamp] = current
    return weights


def asset_class_trend_weights(closes: pd.DataFrame) -> pd.DataFrame:
    trend_ok = closes > closes.rolling(200).mean()
    dummy = closes.copy()
    weights = pd.DataFrame(0.0, index=closes.index, columns=closes.columns)
    current = pd.Series(0.0, index=closes.columns)
    monthly = _monthly_rebalance(closes.index)
    for offset, timestamp in enumerate(closes.index):
        if bool(monthly.loc[timestamp]) and offset >= 200:
            selected = list(dummy.columns[trend_ok.loc[timestamp].fillna(False)])
            current = pd.Series(0.0, index=closes.columns)
            if selected:
                current.loc[selected] = 1.0 / len(selected)
        weights.loc[timestamp] = current
    return weights


def strategy_returns(
    closes: pd.DataFrame,
    weights: pd.DataFrame,
    *,
    cost_per_notional: float = COST_PER_TRADED_NOTIONAL,
) -> pd.Series:
    returns = closes.pct_change().fillna(0.0)
    held = weights.shift(1).fillna(0.0)
    gross = (held * returns).sum(axis=1)
    changes = weights.diff()
    changes.iloc[0] = weights.iloc[0]
    turnover = changes.abs().sum(axis=1).shift(1).fillna(0.0)
    return gross - turnover * cost_per_notional


def _metrics(returns: pd.Series) -> dict[str, Any]:
    returns = returns.dropna()
    if returns.empty:
        return {"observations": 0}
    equity = (1.0 + returns).cumprod()
    years = len(returns) / 252.0
    cagr = equity.iloc[-1] ** (1.0 / years) - 1.0 if years > 0 and equity.iloc[-1] > 0 else -1.0
    volatility = float(returns.std() * math.sqrt(252))
    sharpe = float(returns.mean() / returns.std() * math.sqrt(252)) if returns.std() else 0.0
    drawdown = equity / equity.cummax() - 1.0
    yearly = (1.0 + returns).groupby(returns.index.year).prod() - 1.0
    return {
        "observations": len(returns),
        "start": str(returns.index[0].date()),
        "end": str(returns.index[-1].date()),
        "total_return_pct": round((equity.iloc[-1] - 1.0) * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "annual_volatility_pct": round(volatility * 100.0, 2),
        "sharpe_ratio": round(sharpe, 3),
        "max_drawdown_pct": round(abs(float(drawdown.min())) * 100.0, 2),
        "calmar_ratio": round(cagr / abs(float(drawdown.min())), 3) if drawdown.min() < 0 else None,
        "positive_year_rate": round(float((yearly > 0).mean()), 3),
        "worst_year_pct": round(float(yearly.min()) * 100.0, 2),
    }


def _window(returns: pd.Series, start: str, end: str | None = None) -> pd.Series:
    selected = returns.loc[returns.index >= pd.Timestamp(start)]
    if end:
        selected = selected.loc[selected.index <= pd.Timestamp(end)]
    return selected


def _report_strategy(
    name: str,
    returns: pd.Series,
    benchmark: pd.Series,
    double_cost_returns: pd.Series,
) -> dict[str, Any]:
    aligned = pd.concat({"strategy": returns, "benchmark": benchmark}, axis=1).dropna()
    windows = {
        "development": ("2007-01-01", "2021-12-31"),
        "selection": ("2022-01-01", "2024-12-31"),
        "final": ("2025-01-01", None),
    }
    split = {
        label: _metrics(_window(aligned["strategy"], start, end))
        for label, (start, end) in windows.items()
    }
    overall = _metrics(aligned["strategy"])
    benchmark_metrics = _metrics(aligned["benchmark"])
    double_cost = _metrics(double_cost_returns.reindex(aligned.index).fillna(0.0))
    passed = bool(
        split["selection"].get("cagr_pct", -1) > 0
        and split["final"].get("cagr_pct", -1) > 0
        and overall.get("sharpe_ratio", 0) > benchmark_metrics.get("sharpe_ratio", 0)
        and overall.get("max_drawdown_pct", 100) < benchmark_metrics.get("max_drawdown_pct", 100)
        and double_cost.get("cagr_pct", -1) > 0
    )
    return {
        "name": name,
        "overall": overall,
        "benchmark_same_dates": benchmark_metrics,
        "double_cost_overall": double_cost,
        "splits": split,
        "passed_risk_adjusted_challenger_gate": passed,
        "promotion_authority": "shadow_review_only" if passed else "blocked",
    }


def run_lab(closes: pd.DataFrame | None = None) -> dict[str, Any]:
    all_closes = fetch_closes() if closes is None else closes.copy()
    reports: list[dict[str, Any]] = []

    asset = all_closes.loc[:, list(ASSET_CLASSES)].dropna()
    spy_asset = asset["SPY"].pct_change().fillna(0.0)
    trend_weights = asset_class_trend_weights(asset)
    reports.append(_report_strategy(
        "asset_class_trend_200d_monthly",
        strategy_returns(asset, trend_weights),
        spy_asset,
        strategy_returns(asset, trend_weights, cost_per_notional=COST_PER_TRADED_NOTIONAL * 2),
    ))
    asset_momentum_weights = _scheduled_rank_weights(asset, lookback=252, top_n=3, rebalance_days=None)
    reports.append(_report_strategy(
        "asset_class_momentum_12m_top3_monthly",
        strategy_returns(asset, asset_momentum_weights),
        spy_asset,
        strategy_returns(asset, asset_momentum_weights, cost_per_notional=COST_PER_TRADED_NOTIONAL * 2),
    ))

    sector = all_closes.loc[:, list(SECTORS)].dropna()
    spy_sector = all_closes["SPY"].reindex(sector.index).pct_change().fillna(0.0)
    sector_momentum_weights = _scheduled_rank_weights(sector, lookback=252, top_n=3, rebalance_days=None)
    reports.append(_report_strategy(
        "sector_momentum_12m_top3_monthly",
        strategy_returns(sector, sector_momentum_weights),
        spy_sector,
        strategy_returns(sector, sector_momentum_weights, cost_per_notional=COST_PER_TRADED_NOTIONAL * 2),
    ))
    positive_momentum = sector.pct_change(252) > 0
    low_vol_sector_weights = _scheduled_rank_weights(
        sector,
        lookback=63,
        top_n=3,
        rebalance_days=None,
        lowest=True,
        eligibility=positive_momentum,
    )
    reports.append(_report_strategy(
        "sector_low_vol_positive_momentum_top3_monthly",
        strategy_returns(sector, low_vol_sector_weights),
        spy_sector,
        strategy_returns(sector, low_vol_sector_weights, cost_per_notional=COST_PER_TRADED_NOTIONAL * 2),
    ))

    canonical = all_closes.loc[:, list(CANONICAL)].dropna()
    canonical_benchmark = canonical["SPY"].pct_change().fillna(0.0)
    canonical_weights = _scheduled_rank_weights(canonical, lookback=252, top_n=2, rebalance_days=5)
    reports.append(_report_strategy(
        "existing_canonical_12m_top2_weekly",
        strategy_returns(canonical, canonical_weights),
        canonical_benchmark,
        strategy_returns(canonical, canonical_weights, cost_per_notional=COST_PER_TRADED_NOTIONAL * 2),
    ))
    smooth_momentum_weights = smooth_momentum_proxy_weights(canonical)
    reports.append(_report_strategy(
        "quality_momentum_smooth_12m_top2_monthly_proxy",
        strategy_returns(canonical, smooth_momentum_weights),
        canonical_benchmark,
        strategy_returns(
            canonical,
            smooth_momentum_weights,
            cost_per_notional=COST_PER_TRADED_NOTIONAL * 2,
        ),
    ))

    low_vol = all_closes.loc[:, ["SPY", *LOW_VOL_ETFS]].dropna()
    low_vol_weights = pd.DataFrame(0.0, index=low_vol.index, columns=list(LOW_VOL_ETFS))
    low_vol_weights.loc[:, :] = 0.5
    reports.append(_report_strategy(
        "low_vol_etf_proxy_equal_weight",
        strategy_returns(low_vol.loc[:, list(LOW_VOL_ETFS)], low_vol_weights),
        low_vol["SPY"].pct_change().fillna(0.0),
        strategy_returns(
            low_vol.loc[:, list(LOW_VOL_ETFS)],
            low_vol_weights,
            cost_per_notional=COST_PER_TRADED_NOTIONAL * 2,
        ),
    ))

    return {
        "schema_version": 2,
        "experiment": "PYQUANT-STRATEGY-FAMILY-CHALLENGER",
        "cost_per_traded_notional": COST_PER_TRADED_NOTIONAL,
        "signal_execution_lag_days": 1,
        "strategies": reports,
        "quality_momentum_proxy": {
            "source": "Alpha Architect published quantitative momentum process",
            "status": "transparent_proxy_not_fund_replication",
            "rules": "monthly; positive 12-1 momentum; shortlist top six; select two with highest positive-day share; equal weight; execute next trading day",
            "promotion_authority": "blocked",
        },
        "fx_carry": {
            "status": "not_tested",
            "reason": "requires point-in-time interest-rate differentials and executable forward or spot-plus-funding returns; price-only currency ETFs are not a valid replication",
        },
        "survivor_count": int(sum(row["passed_risk_adjusted_challenger_gate"] for row in reports)),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = run_lab()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
