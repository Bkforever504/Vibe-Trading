#!/usr/bin/env python3
"""Extend the frozen 2024 momentum candidate into the 2025+ period."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.momentum_rotation_backtest import (
    _metrics_from_equity,
    _momentum_equity_curve,
    _momentum_signal,
    fetch_universe,
)

NY = ZoneInfo("America/New_York")
SYMBOLS = ("SPY", "QQQ", "GLD", "XLE", "TLT", "IWM", "XLK", "XLV", "XLF", "XLI")
OUTPUT = Path.home() / ".vibe-trading" / "reports" / "momentum-rotation-forward-extension.json"
TEST_START = "2025-01-01"


def evaluate_forward(universe: pd.DataFrame, cost_pct: float = 0.06) -> dict:
    signal = _momentum_signal(universe, lookback_days=12 * 21, rebalance_days=5, top_n=2)
    test = universe.loc[universe.index >= TEST_START]
    test_signal = signal.reindex(test.index)
    equity = _momentum_equity_curve(test, test_signal, slippage_pct=cost_pct, commission_pct=0.0)
    metrics = _metrics_from_equity(equity, test_signal)
    yearly = {}
    for year in sorted({str(index.year) for index in test.index}):
        year_data = test.loc[test.index.year == int(year)]
        year_signal = test_signal.reindex(year_data.index)
        year_equity = _momentum_equity_curve(year_data, year_signal, slippage_pct=cost_pct, commission_pct=0.0)
        yearly[year] = _metrics_from_equity(year_equity, year_signal)
    latest_raw = signal.dropna().iloc[-1] if not signal.dropna().empty else None
    latest = list(latest_raw) if isinstance(latest_raw, tuple) else None
    return {"metrics": metrics, "yearly": yearly, "latest_holdings": latest}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2026-07-19")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    universe = fetch_universe(list(SYMBOLS), args.start, args.end)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(NY).isoformat(),
        "mode": "research_only",
        "execution_enabled": False,
        "selection_frozen_before_test": True,
        "selection_source": "research/momentum_rotation/validation_2015_2024.md",
        "config": {"symbols": list(SYMBOLS), "lookback_months": 12, "rebalance_days": 5, "top_n": 2},
        "data_coverage": {"start": str(universe.index.min().date()), "end": str(universe.index.max().date())},
        "forward_2025_plus": evaluate_forward(universe, 0.06),
        "double_cost_forward": evaluate_forward(universe, 0.12),
        "warnings": [
            "ETF total-return data from yfinance is adjusted and is not venue-level executable data.",
            "The model rotates underlying ETFs; buying calls or puts instead would require a separate option replay.",
            "The 2025+ period is now consumed evidence and cannot be called untouched again.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
