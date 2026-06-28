"""
CLI: run a Python strategy file against real market data and print
manifest-ready metrics for the Pine Strategy Lab.

Usage:
    uv run --no-project python scripts/pine_backtest_runner.py \\
        --strategy research/pine_strategy_lab/examples/vwap_pullback_python.py \\
        --symbol SPY --start 2022-01-01 --end 2024-12-31

The strategy file must define a top-level function:

    def strategy(ohlcv: pd.DataFrame) -> pd.Series:
        ...  # returns Series of {1, 0, -1} aligned to ohlcv.index
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.pine_strategy_lab_backtest import BacktestConfig, run_backtest


def _load_strategy_fn(path: Path):
    spec = importlib.util.spec_from_file_location("_pine_strategy", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "strategy"):
        raise AttributeError(f"{path} must define a top-level function named 'strategy'")
    return mod.strategy


def main() -> int:
    p = argparse.ArgumentParser(description="Backtest a Pine-translated Python strategy.")
    p.add_argument("--strategy", required=True, type=Path, help="Python file with strategy(ohlcv) -> signals.")
    p.add_argument("--symbol",   required=True, help="Ticker, e.g. SPY, QQQ, IWM.")
    p.add_argument("--start",    required=True, help="Start date YYYY-MM-DD.")
    p.add_argument("--end",      required=True, help="End date YYYY-MM-DD.")
    p.add_argument("--slippage", type=float, default=0.05, help="Slippage %% per fill (default 0.05).")
    p.add_argument("--commission", type=float, default=0.01, help="Commission %% per fill (default 0.01).")
    p.add_argument("--oos-split", type=float, default=0.20, dest="oos_split")
    p.add_argument("--wf-folds", type=int, default=5, dest="wf_folds")
    args = p.parse_args()

    strategy_fn = _load_strategy_fn(args.strategy)
    config = BacktestConfig(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        slippage_pct=args.slippage,
        commission_pct=args.commission,
        oos_split=args.oos_split,
        wf_folds=args.wf_folds,
    )

    print(f"Running backtest: {args.strategy.name} on {args.symbol} {args.start}→{args.end}")
    metrics = run_backtest(strategy_fn, config)
    d = asdict(metrics)

    print("\n--- Paste into manifest.json ---")
    print(json.dumps({"metrics": d}, indent=2))

    print("\n--- Evaluation summary ---")
    from research.pine_strategy_lab import PineStrategyIdea, evaluate_candidate
    dummy = PineStrategyIdea(name=args.strategy.stem, license="mit")
    result = evaluate_candidate(dummy, metrics)
    print(f"Status:     {result.status}")
    print(f"Confidence: {result.confidence_score}/10")
    if result.reject_reasons:
        for r in result.reject_reasons:
            print(f"  ✗ {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
