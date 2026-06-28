"""
CLI: sweep a translated Pine/Python strategy across symbols, windows, and params.

Example:
    uv run --no-project --with yfinance --with pandas python scripts/strategy_sweep_runner.py ^
        --strategy research/pine_strategy_lab/examples/ema_crossover_python.py ^
        --symbols SPY,QQQ,IWM ^
        --ranges 2020-01-01:2024-12-31 2022-01-01:2024-12-31
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.pine_strategy_sweep import parse_date_ranges, run_strategy_sweep, write_sweep_report


def main() -> int:
    p = argparse.ArgumentParser(description="Run Pine Strategy Lab parameter sweeps.")
    p.add_argument("--strategy", required=True, type=Path, help="Python strategy file with strategy(ohlcv, **params).")
    p.add_argument("--symbols", default="SPY,QQQ,IWM", help="Comma-separated symbols.")
    p.add_argument("--ranges", nargs="+", required=True, help="Date ranges as START:END.")
    p.add_argument("--out", type=Path, default=Path("research/pine_strategy_lab/sweep_report.md"))
    p.add_argument("--slippage", type=float, default=0.05)
    p.add_argument("--commission", type=float, default=0.01)
    p.add_argument("--oos-split", type=float, default=0.20, dest="oos_split")
    p.add_argument("--wf-folds", type=int, default=5, dest="wf_folds")
    p.add_argument("--purge-bars", type=int, default=5, dest="purge_bars")
    args = p.parse_args()

    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    results = run_strategy_sweep(
        args.strategy,
        symbols=symbols,
        date_ranges=parse_date_ranges(args.ranges),
        slippage_pct=args.slippage,
        commission_pct=args.commission,
        oos_split=args.oos_split,
        wf_folds=args.wf_folds,
        purge_bars=args.purge_bars,
    )
    write_sweep_report(results, args.out)

    print(f"Wrote {args.out.resolve()}")
    print(f"Sweep rows: {len(results)}")
    for result in results[:10]:
        print(
            f"{result.strategy_name} {result.symbol} {result.start}:{result.end} "
            f"{result.params} conf={result.evaluation.confidence_score:.1f} "
            f"pf={result.metrics.profit_factor:.2f} oos={result.metrics.out_of_sample_profit_factor:.2f} "
            f"wf={result.metrics.walk_forward_pass_rate:.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
