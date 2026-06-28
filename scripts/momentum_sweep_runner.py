"""
CLI: sweep momentum rotation across lookback periods and date ranges.

Example:
    python scripts/momentum_sweep_runner.py ^
        --symbols SPY,QQQ,GLD,XLE,TLT,IWM ^
        --lookbacks 3 6 12 ^
        --ranges 2018-01-01:2024-12-31 ^
        --out research/momentum_rotation/sweep_report.md
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.momentum_rotation_backtest import MomentumConfig, fetch_universe, run_momentum_backtest
from research.pine_strategy_lab import PineStrategyIdea, evaluate_candidate
from research.pine_strategy_sweep import (
    SweepResult,
    estimate_pbo_score,
    parse_date_ranges,
    write_sweep_report,
)


def run_momentum_sweep(
    symbols: list[str],
    date_ranges: list[tuple[str, str]],
    lookback_months_list: list[int],
    top_n_list: list[int] | None = None,
    rebalance_days: int = 21,
    slippage_pct: float = 0.05,
    commission_pct: float = 0.01,
    oos_split: float = 0.20,
    wf_folds: int = 5,
    purge_bars: int = 5,
) -> list[SweepResult]:
    results: list[SweepResult] = []
    universe_cache: dict[tuple[str, str], object] = {}
    top_n_values = top_n_list or [1]

    for start, end in date_ranges:
        cache_key = (start, end)
        if cache_key not in universe_cache:
            universe_cache[cache_key] = fetch_universe(symbols, start, end)
        universe = universe_cache[cache_key]

        for lb in lookback_months_list:
            for top_n in top_n_values:
                config = MomentumConfig(
                    symbols=symbols,
                    start=start,
                    end=end,
                    lookback_months=lb,
                    rebalance_days=rebalance_days,
                    top_n=top_n,
                    slippage_pct=slippage_pct,
                    commission_pct=commission_pct,
                    oos_split=oos_split,
                    wf_folds=wf_folds,
                    purge_bars=purge_bars,
                )
                metrics = run_momentum_backtest(config, universe=universe)
                idea = PineStrategyIdea(name="momentum_rotation", license="mit")
                evaluation = evaluate_candidate(idea, metrics)
                results.append(SweepResult(
                    strategy_name="momentum_rotation",
                    symbol=f"UNIVERSE[{len(symbols)}]",
                    start=start,
                    end=end,
                    params={"lookback_months": lb, "top_n": top_n},
                    metrics=metrics,
                    evaluation=evaluation,
                ))

    # Attach population-level PBO score
    pbo = estimate_pbo_score([r.metrics for r in results])
    updated: list[SweepResult] = []
    for result in results:
        m = replace(result.metrics, pbo_score=pbo)
        idea = PineStrategyIdea(name="momentum_rotation", license="mit")
        ev = evaluate_candidate(idea, m)
        updated.append(SweepResult(
            strategy_name=result.strategy_name,
            symbol=result.symbol,
            start=result.start,
            end=result.end,
            params=result.params,
            metrics=m,
            evaluation=ev,
        ))

    return sorted(
        updated,
        key=lambda r: (
            r.evaluation.confidence_score,
            r.metrics.out_of_sample_profit_factor,
            r.metrics.profit_factor,
            -r.metrics.max_drawdown_pct,
        ),
        reverse=True,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Run momentum rotation parameter sweeps.")
    p.add_argument("--symbols", default="SPY,QQQ,GLD,XLE,TLT,IWM", help="Comma-separated universe.")
    p.add_argument("--lookbacks", nargs="+", type=int, default=[3, 6, 12], metavar="MONTHS")
    p.add_argument("--top-n", nargs="+", type=int, default=[1], dest="top_n", metavar="N")
    p.add_argument("--ranges", nargs="+", required=True, help="Date ranges as START:END.")
    p.add_argument("--rebalance-days", type=int, default=21, dest="rebalance_days")
    p.add_argument("--out", type=Path, default=Path("research/momentum_rotation/sweep_report.md"))
    p.add_argument("--slippage", type=float, default=0.05)
    p.add_argument("--commission", type=float, default=0.01)
    p.add_argument("--oos-split", type=float, default=0.20, dest="oos_split")
    p.add_argument("--wf-folds", type=int, default=5, dest="wf_folds")
    p.add_argument("--purge-bars", type=int, default=5, dest="purge_bars")
    args = p.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    results = run_momentum_sweep(
        symbols=symbols,
        date_ranges=parse_date_ranges(args.ranges),
        lookback_months_list=args.lookbacks,
        top_n_list=args.top_n,
        rebalance_days=args.rebalance_days,
        slippage_pct=args.slippage,
        commission_pct=args.commission,
        oos_split=args.oos_split,
        wf_folds=args.wf_folds,
        purge_bars=args.purge_bars,
    )
    write_sweep_report(results, args.out)

    print(f"Wrote {args.out.resolve()}")
    print(f"Sweep rows: {len(results)}")
    for r in results[:10]:
        print(
            f"{r.strategy_name} {r.symbol} {r.start}:{r.end} "
            f"{r.params} conf={r.evaluation.confidence_score:.1f} "
            f"pf={r.metrics.profit_factor:.2f} oos={r.metrics.out_of_sample_profit_factor:.2f} "
            f"wf={r.metrics.walk_forward_pass_rate:.2f} dd={r.metrics.max_drawdown_pct:.1f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
