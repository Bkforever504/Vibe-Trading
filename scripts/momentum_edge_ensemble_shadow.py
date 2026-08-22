#!/usr/bin/env python3
"""Record the momentum ensemble's current target weights without trading."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.momentum_edge_ensemble_lab import ALL_SYMBOLS, build_ensemble_weights
from research.pyquant_strategy_family_lab import fetch_closes


DEFAULT_LOG = ROOT / "data" / "momentum_edge_ensemble_shadow.jsonl"


def build_decision(closes: pd.DataFrame, *, generated_on: date) -> dict[str, Any]:
    prices = closes.loc[:, list(ALL_SYMBOLS)].dropna().sort_index()
    weights, _ = build_ensemble_weights(prices)
    latest = weights.iloc[-1]
    allocations = {
        symbol: round(float(weight), 6)
        for symbol, weight in latest.items()
        if float(weight) > 0.0
    }
    invested = sum(allocations.values())
    return {
        "schema_version": 1,
        "record_type": "signal",
        "strategy": "momentum_edge_ensemble_v1",
        "mode": "forward_shadow_only",
        "generated_on": generated_on.isoformat(),
        "signal_asof": str(pd.Timestamp(prices.index[-1]).date()),
        "allocations": allocations,
        "cash_weight": round(max(0.0, 1.0 - invested), 6),
        "maximum_asset_weight": max(allocations.values(), default=0.0),
        "execution_enabled": False,
        "can_submit_orders": False,
        "promotion_eligible": False,
        "blockers": [
            "requires_12_completed_monthly_observations",
            "requires_252_elapsed_forward_trading_sessions",
            "historical_results_use_consumed_data",
        ],
    }


def write_idempotent(entry: dict[str, Any], path: Path) -> None:
    rows: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("signal_asof") != entry.get("signal_asof"):
                rows.append(row)
    rows.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    args = parser.parse_args()
    today = date.today()
    closes = fetch_closes(ALL_SYMBOLS, start=(today - timedelta(days=1100)).isoformat())
    decision = build_decision(closes, generated_on=today)
    write_idempotent(decision, args.log)
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
