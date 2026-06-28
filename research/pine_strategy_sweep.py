from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import importlib.util
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from research.pine_strategy_lab import BacktestMetrics, CandidateEvaluation, PineStrategyIdea, evaluate_candidate
from research.pine_strategy_lab_backtest import BacktestConfig, StrategyFn, fetch_ohlcv, run_backtest, run_backtest_on_ohlcv


BacktestFn = Callable[[StrategyFn, BacktestConfig], BacktestMetrics]
FetchFn = Callable[[str, str, str], pd.DataFrame]


@dataclass(frozen=True)
class SweepResult:
    strategy_name: str
    symbol: str
    start: str
    end: str
    params: dict
    metrics: BacktestMetrics
    evaluation: CandidateEvaluation


def parse_date_ranges(values: Iterable[str]) -> list[tuple[str, str]]:
    ranges: list[tuple[str, str]] = []
    for value in values:
        if ":" not in value:
            raise ValueError(f"Date range must be START:END, got {value!r}")
        start, end = value.split(":", 1)
        ranges.append((start.strip(), end.strip()))
    return ranges


def run_strategy_sweep(
    strategy_path: Path,
    symbols: list[str],
    date_ranges: list[tuple[str, str]],
    param_grid: list[dict] | None = None,
    backtest_fn: BacktestFn = run_backtest,
    fetch_fn: FetchFn = fetch_ohlcv,
    slippage_pct: float = 0.05,
    commission_pct: float = 0.01,
    oos_split: float = 0.20,
    wf_folds: int = 5,
    purge_bars: int = 5,
    include_vix: bool = False,
    defensive_symbol: str | None = None,
    defensive_sma_window: int | None = None,
) -> list[SweepResult]:
    module = _load_strategy_module(strategy_path)
    strategy_fn = getattr(module, "strategy")
    grid = param_grid if param_grid is not None else _module_parameter_grid(module)
    results: list[SweepResult] = []
    data_cache: dict[tuple[str, str, str], pd.DataFrame] = {}
    vix_cache: dict[tuple[str, str], pd.DataFrame] = {}
    defensive_cache: dict[tuple[str, str], pd.DataFrame] = {}

    for params in grid:
        wrapped = _bind_strategy_params(strategy_fn, params)
        for symbol in symbols:
            for start, end in date_ranges:
                config = BacktestConfig(
                    symbol=symbol,
                    start=start,
                    end=end,
                    slippage_pct=slippage_pct,
                    commission_pct=commission_pct,
                    oos_split=oos_split,
                    wf_folds=wf_folds,
                    purge_bars=purge_bars,
                )
                if backtest_fn is run_backtest:
                    cache_key = (symbol, start, end)
                    if cache_key not in data_cache:
                        data = fetch_fn(symbol, start, end)
                        if include_vix:
                            vix_key = (start, end)
                            if vix_key not in vix_cache:
                                vix_cache[vix_key] = fetch_fn("^VIX", start, end)
                            data = merge_vix_close(data, vix_cache[vix_key])
                        if defensive_symbol is not None:
                            def_key = (start, end)
                            if def_key not in defensive_cache:
                                defensive_cache[def_key] = fetch_fn(defensive_symbol, start, end)
                            data = merge_defensive_close(
                                data,
                                defensive_cache[def_key],
                                defensive_sma_window=defensive_sma_window,
                            )
                        data_cache[cache_key] = data
                    metrics = run_backtest_on_ohlcv(wrapped, data_cache[cache_key], config)
                else:
                    metrics = backtest_fn(wrapped, config)
                idea = PineStrategyIdea(name=strategy_path.stem, license="mit")
                evaluation = evaluate_candidate(idea, metrics)
                results.append(SweepResult(
                    strategy_name=strategy_path.stem,
                    symbol=symbol,
                    start=start,
                    end=end,
                    params=dict(params),
                    metrics=metrics,
                    evaluation=evaluation,
                ))

    results = _attach_population_pbo(results)
    return sorted(
        results,
        key=lambda item: (
            item.evaluation.confidence_score,
            item.metrics.out_of_sample_profit_factor,
            item.metrics.profit_factor,
            -item.metrics.max_drawdown_pct,
        ),
        reverse=True,
    )


def write_sweep_report(results: list[SweepResult], path: Path) -> None:
    pbo_score = results[0].metrics.pbo_score if results else 0.0
    lines = [
        "# Pine Strategy Sweep Report",
        "",
        "Research only. Sweep winners still need red-flag review, paper-forward validation, and execution guard approval.",
        "",
        f"PBO score: {pbo_score:.2f} (0.00=stable, 1.00=likely overfit)",
        "",
        "| Strategy | Symbol | Window | Params | Status | Conf | PF | OOS PF | WF | Sharpe | WR% | Trades | Max DD |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        metrics = result.metrics
        params = _format_params(result.params)
        lines.append(
            "| "
            + " | ".join([
                result.strategy_name,
                result.symbol,
                f"{result.start}:{result.end}",
                params,
                result.evaluation.status,
                f"{result.evaluation.confidence_score:.1f}",
                f"{metrics.profit_factor:.2f}",
                f"{metrics.out_of_sample_profit_factor:.2f}",
                f"{metrics.walk_forward_pass_rate:.2f}",
                f"{metrics.sharpe_ratio:.2f}",
                f"{metrics.win_rate_pct:.1f}%",
                str(metrics.trade_count),
                f"{metrics.max_drawdown_pct:.1f}%",
            ])
            + " |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge_vix_close(ohlcv: pd.DataFrame, vix_ohlcv: pd.DataFrame) -> pd.DataFrame:
    merged = ohlcv.copy()
    vix_close = vix_ohlcv["close"].reindex(merged.index).ffill()
    merged["vix_close"] = vix_close
    return merged


def merge_defensive_close(
    ohlcv: pd.DataFrame,
    defensive_ohlcv: pd.DataFrame,
    defensive_sma_window: int | None = None,
) -> pd.DataFrame:
    """Merge defensive asset close into equity OHLCV as 'defensive_close'.

    The backtester uses this column to earn defensive returns during flat
    periods (signal=0) instead of sitting in cash.
    """
    merged = ohlcv.copy()
    defensive_close = defensive_ohlcv["close"].reindex(merged.index).ffill()
    merged["defensive_close"] = defensive_close
    if defensive_sma_window is not None:
        defensive_sma = defensive_close.rolling(defensive_sma_window).mean()
        merged["defensive_risk_on"] = (defensive_close > defensive_sma).fillna(False)
    return merged


def pool_sweep_results_by_params(results: list[SweepResult]) -> list[SweepResult]:
    groups: dict[tuple, list[SweepResult]] = {}
    for result in results:
        key = (
            result.strategy_name,
            result.start,
            result.end,
            tuple(sorted(result.params.items())),
        )
        groups.setdefault(key, []).append(result)

    pooled: list[SweepResult] = []
    for (strategy_name, start, end, params_tuple), rows in groups.items():
        params = dict(params_tuple)
        metrics = _pool_metrics([row.metrics for row in rows])
        idea = PineStrategyIdea(name=f"{strategy_name}_pooled", license="mit")
        evaluation = evaluate_candidate(idea, metrics)
        pooled.append(SweepResult(
            strategy_name=strategy_name,
            symbol=f"POOL[{len(rows)}]",
            start=start,
            end=end,
            params=params,
            metrics=metrics,
            evaluation=evaluation,
        ))

    return sorted(
        pooled,
        key=lambda item: (
            item.evaluation.confidence_score,
            item.metrics.out_of_sample_profit_factor,
            item.metrics.profit_factor,
            -item.metrics.max_drawdown_pct,
        ),
        reverse=True,
    )


def _load_strategy_module(path: Path):
    spec = importlib.util.spec_from_file_location("_sweep_strategy", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load strategy module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "strategy"):
        raise AttributeError(f"{path} must define strategy(ohlcv, **params)")
    return module


def _pool_metrics(metrics_rows: list[BacktestMetrics]) -> BacktestMetrics:
    trade_count = sum(row.trade_count for row in metrics_rows)
    gross_win = 0.0
    gross_loss = 0.0
    weighted_win_rate = 0.0
    weighted_avg_win = 0.0
    weighted_avg_loss = 0.0
    for row in metrics_rows:
        wins = row.trade_count * row.win_rate_pct / 100
        losses = max(0.0, row.trade_count - wins)
        gross_win += wins * max(row.avg_win_pct, 0.0)
        gross_loss += losses * abs(min(row.avg_loss_pct, 0.0))
        weighted_win_rate += row.win_rate_pct * row.trade_count
        weighted_avg_win += row.avg_win_pct * row.trade_count
        weighted_avg_loss += row.avg_loss_pct * row.trade_count

    profit_factor = gross_win / gross_loss if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
    return BacktestMetrics(
        total_return_pct=round(sum(row.total_return_pct for row in metrics_rows) / len(metrics_rows), 3),
        profit_factor=round(min(profit_factor, 99.0), 3),
        max_drawdown_pct=round(max(row.max_drawdown_pct for row in metrics_rows), 3),
        trade_count=trade_count,
        out_of_sample_profit_factor=round(_median([row.out_of_sample_profit_factor for row in metrics_rows]), 3),
        walk_forward_pass_rate=round(sum(row.walk_forward_pass_rate for row in metrics_rows) / len(metrics_rows), 3),
        avg_win_pct=round(weighted_avg_win / trade_count, 3) if trade_count else 0.0,
        avg_loss_pct=round(weighted_avg_loss / trade_count, 3) if trade_count else 0.0,
        expectancy_pct=round(sum(row.expectancy_pct * row.trade_count for row in metrics_rows) / trade_count, 3) if trade_count else 0.0,
        max_consecutive_losses=max(row.max_consecutive_losses for row in metrics_rows),
        time_in_market_pct=round(sum(row.time_in_market_pct for row in metrics_rows) / len(metrics_rows), 3),
        sharpe_ratio=round(sum(row.sharpe_ratio for row in metrics_rows) / len(metrics_rows), 3),
        win_rate_pct=round(weighted_win_rate / trade_count, 3) if trade_count else 0.0,
        calmar_ratio=round(sum(row.calmar_ratio for row in metrics_rows) / len(metrics_rows), 3),
        pbo_score=round(max(row.pbo_score for row in metrics_rows), 3),
    )


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2)


def _attach_population_pbo(results: list[SweepResult]) -> list[SweepResult]:
    pbo_score = estimate_pbo_score([result.metrics for result in results])
    annotated: list[SweepResult] = []
    for result in results:
        metrics = replace(result.metrics, pbo_score=pbo_score)
        evaluation = evaluate_candidate(result.evaluation.idea, metrics)
        annotated.append(SweepResult(
            strategy_name=result.strategy_name,
            symbol=result.symbol,
            start=result.start,
            end=result.end,
            params=result.params,
            metrics=metrics,
            evaluation=evaluation,
        ))
    return annotated


def estimate_pbo_score(metrics: list[BacktestMetrics], max_combinations: int = 64) -> float:
    """
    Estimate Probability of Backtest Overfitting from a sweep population.

    This is a lightweight CSCV-style proxy:
    - split parameter rows into symmetric train/test combinations
    - choose the train winner by in-sample profit factor
    - mark overfit when that winner ranks in the bottom half by OOS profit factor

    It is a research warning, not a formal statistical proof.
    """
    if len(metrics) < 4:
        return 0.0

    top_half_count = len(metrics) // 2
    is_ranked = sorted(range(len(metrics)), key=lambda idx: metrics[idx].profit_factor, reverse=True)
    oos_ranked = sorted(range(len(metrics)), key=lambda idx: metrics[idx].out_of_sample_profit_factor, reverse=True)
    bottom_oos = set(oos_ranked[top_half_count:])
    top_is = is_ranked[:top_half_count]
    failures = sum(1 for idx in top_is if idx in bottom_oos)
    return round(failures / len(top_is), 3) if top_is else 0.0


def _module_parameter_grid(module) -> list[dict]:
    if hasattr(module, "parameter_grid"):
        grid = module.parameter_grid()
    else:
        grid = getattr(module, "PARAM_GRID", [{}])
    if not grid:
        return [{}]
    return [dict(row) for row in grid]


def _bind_strategy_params(strategy_fn, params: dict) -> StrategyFn:
    def wrapped(ohlcv: pd.DataFrame) -> pd.Series:
        return strategy_fn(ohlcv, **params)

    wrapped._sweep_params = dict(params)
    return wrapped


def _format_params(params: dict) -> str:
    if not params:
        return "-"
    return ", ".join(f"{key}={value}" for key, value in sorted(params.items()))
