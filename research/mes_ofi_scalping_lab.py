#!/usr/bin/env python3
"""Preregistered executable-fill MES OFI scalping test."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "databento" / "mes_bbo_ofi_30s_2024_2026.parquet"
OUTPUT = ROOT / "data" / "mes_ofi_scalping_results.json"
WINDOW = 60
Z_THRESHOLD = 2.5
MAX_TRADES_DAY = 3
COOLDOWN_SECONDS = 300
TICK = 0.25
POINT_USD = 5.0
BASE_COMMISSION = 2.48
STRESS_COMMISSION = 4.96
STRESS_SLIPPAGE = 2.50


def executable_pnl(
    *, direction: int, entry_bid: float, entry_ask: float, exit_bid: float, exit_ask: float, stress: bool
) -> float:
    if direction not in (-1, 1):
        raise ValueError("direction must be -1 or 1")
    entry = entry_ask if direction == 1 else entry_bid
    exit_price = exit_bid if direction == 1 else exit_ask
    gross = direction * (exit_price - entry) * POINT_USD
    return gross - (STRESS_COMMISSION + STRESS_SLIPPAGE if stress else BASE_COMMISSION)


def add_point_in_time_zscore(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.sort_values(["session_date", "instrument_id", "bucket_start"]).copy()
    grouped = result.groupby(["session_date", "instrument_id"], sort=False)["ofi"]
    prior_mean = grouped.transform(lambda values: values.shift(1).rolling(WINDOW, min_periods=WINDOW).mean())
    prior_std = grouped.transform(lambda values: values.shift(1).rolling(WINDOW, min_periods=WINDOW).std(ddof=1))
    result["ofi_z"] = (result["ofi"] - prior_mean) / prior_std.replace(0.0, np.nan)
    return result


def generate_trades(frame: pd.DataFrame, *, reversal: bool) -> list[dict[str, Any]]:
    data = add_point_in_time_zscore(frame)
    trades: list[dict[str, Any]] = []
    for (session_date, instrument_id), group in data.groupby(["session_date", "instrument_id"], sort=True):
        rows = group.sort_values("bucket_start").reset_index(drop=True)
        last_entry: pd.Timestamp | None = None
        session_trades = 0
        for pos in range(len(rows) - 1):
            if session_trades >= MAX_TRADES_DAY:
                break
            row, nxt = rows.iloc[pos], rows.iloc[pos + 1]
            timestamp = pd.Timestamp(row["bucket_start"])
            next_timestamp = pd.Timestamp(nxt["bucket_start"])
            if (next_timestamp - timestamp).total_seconds() != 30:
                continue
            zscore = float(row["ofi_z"])
            if not np.isfinite(zscore) or abs(zscore) < Z_THRESHOLD:
                continue
            if int(row["quote_seconds"]) < 20 or int(nxt["quote_seconds"]) < 20:
                continue
            entry_spread = float(row["end_ask"] - row["end_bid"])
            exit_spread = float(nxt["end_ask"] - nxt["end_bid"])
            if not (0 < entry_spread <= TICK + 1e-9 and 0 < exit_spread <= TICK + 1e-9):
                continue
            if last_entry is not None and (timestamp - last_entry).total_seconds() < COOLDOWN_SECONDS:
                continue
            direction = 1 if zscore > 0 else -1
            if reversal:
                direction *= -1
            common = {
                "direction": direction,
                "entry_bid": float(row["end_bid"]),
                "entry_ask": float(row["end_ask"]),
                "exit_bid": float(nxt["end_bid"]),
                "exit_ask": float(nxt["end_ask"]),
            }
            trades.append(
                {
                    "session_date": str(session_date),
                    "instrument_id": int(instrument_id),
                    "entry_time": timestamp.isoformat(),
                    "exit_time": next_timestamp.isoformat(),
                    "ofi_z": zscore,
                    "base_pnl": executable_pnl(**common, stress=False),
                    "stress_pnl": executable_pnl(**common, stress=True),
                }
            )
            last_entry = timestamp
            session_trades += 1
    return trades


def metrics(trades: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = np.asarray([float(row[field]) for row in trades], dtype=float)
    if not len(values):
        return {"trades": 0}
    wins, losses = values[values > 0], values[values < 0]
    equity = np.cumsum(values)
    peak = np.maximum.accumulate(np.concatenate(([0.0], equity)))[1:]
    remove_count = max(1, math.ceil(len(values) * 0.01))
    trimmed = np.sort(values)[:-remove_count]
    return {
        "trades": int(len(values)),
        "total_pnl": round(float(values.sum()), 2),
        "expectancy": round(float(values.mean()), 4),
        "win_rate": round(float((values > 0).mean()), 4),
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 4) if len(losses) else None,
        "max_drawdown": round(float((peak - equity).max()), 2),
        "top_one_pct_removed_expectancy": round(float(trimmed.mean()), 4),
    }


def session_splits(frame: pd.DataFrame) -> dict[str, set[str]]:
    sessions = sorted(str(value) for value in frame["session_date"].drop_duplicates())
    first = int(len(sessions) * 0.60)
    second = int(len(sessions) * 0.80)
    return {
        "development": set(sessions[:first]),
        "selection": set(sessions[first:second]),
        "final": set(sessions[second:]),
    }


def build_report() -> dict[str, Any]:
    frame = pd.read_parquet(INPUT)
    frame["bucket_start"] = pd.to_datetime(frame["bucket_start"])
    splits = session_splits(frame)
    results = []
    for name, reversal in (("ofi_momentum_scalp", False), ("ofi_reversal_scalp", True)):
        trades = generate_trades(frame, reversal=reversal)
        stages: dict[str, Any] = {}
        for stage, dates in splits.items():
            subset = [row for row in trades if row["session_date"] in dates]
            stages[stage] = {
                "base": metrics(subset, "base_pnl"),
                "stress": metrics(subset, "stress_pnl"),
            }
        final_dates = sorted(splits["final"])
        halfway = len(final_dates) // 2
        final_halves = [set(final_dates[:halfway]), set(final_dates[halfway:])]
        final_half_pnl = [
            round(sum(row["stress_pnl"] for row in trades if row["session_date"] in dates), 2)
            for dates in final_halves
        ]
        gates = {
            "minimum_100_trades": len(trades) >= 100,
            "selection_base_positive": (stages["selection"]["base"].get("expectancy") or 0) > 0,
            "final_base_positive": (stages["final"]["base"].get("expectancy") or 0) > 0,
            "selection_stress_positive": (stages["selection"]["stress"].get("expectancy") or 0) > 0,
            "final_stress_positive": (stages["final"]["stress"].get("expectancy") or 0) > 0,
            "selection_trimmed_positive": (
                stages["selection"]["stress"].get("top_one_pct_removed_expectancy") or 0
            ) > 0,
            "final_trimmed_positive": (
                stages["final"]["stress"].get("top_one_pct_removed_expectancy") or 0
            ) > 0,
            "selection_profit_factor_above_one": (stages["selection"]["stress"].get("profit_factor") or 0) > 1,
            "final_profit_factor_above_one": (stages["final"]["stress"].get("profit_factor") or 0) > 1,
            "both_final_halves_positive": all(value > 0 for value in final_half_pnl),
        }
        results.append(
            {
                "variant": name,
                "trade_count": len(trades),
                "stages": stages,
                "final_stress_half_pnl": final_half_pnl,
                "gates": {**gates, "all_pass": all(gates.values())},
                "shadow_candidate": all(gates.values()),
            }
        )
    return {
        "schema_version": 1,
        "protocol": "MES_OFI_SCALPING_PREREGISTRATION_2026-08-13",
        "mode": "research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "source": str(INPUT),
        "session_counts": {name: len(values) for name, values in splits.items()},
        "configuration_count": len(results),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
