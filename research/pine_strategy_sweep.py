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
) -> list[SweepResult]:
    module = _load_strategy_module(strategy_path)
    strategy_fn = getattr(module, "strategy")
    grid = param_grid if param_grid is not None else _module_parameter_grid(module)
    results: list[SweepResult] = []
    data_cache: dict[tuple[str, str, str], pd.DataFrame] = {}

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
                        data_cache[cache_key] = fetch_fn(symbol, start, end)
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


def _load_strategy_module(path: Path):
    spec = importlib.util.spec_from_file_location("_sweep_strategy", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load strategy module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "strategy"):
        raise AttributeError(f"{path} must define strategy(ohlcv, **params)")
    return module


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
