#!/usr/bin/env python3
"""Rolling out-of-sample diagnosis for one frozen MES candidate.

This script does not optimize. It evaluates the same preregistered configuration
across sequential, non-overlapping windows to expose regime instability.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.mes_futures_strategy_search import Candidate, _by_date, _configs, _metrics, _slice
from strategies.topstep_prop_bot import load_candles_csv
from strategies.topstep_replay_backtester import run_backtest


FROZEN_ORB = Candidate(
    signal_type="orb",
    breakout_points=1.0,
    reward_risk=2.0,
    stop_ticks=40,
    tolerance_ticks=4,
    exit_model="full_target_stop",
    filter_name="gap",
    range_minutes=5,
)


def sequential_windows(dates: list[str], window_sessions: int) -> list[list[str]]:
    if window_sessions <= 0:
        raise ValueError("window_sessions must be positive")
    return [dates[start:start + window_sessions] for start in range(0, len(dates), window_sessions)]


def diagnose(csv_path: Path, *, window_sessions: int = 126) -> dict[str, object]:
    candles = load_candles_csv(csv_path)
    dates, grouped = _by_date(candles)
    windows = sequential_windows(dates, window_sessions)
    rows: list[dict[str, object]] = []
    aggregate_pnl = 0.0
    aggregate_stress_pnl = 0.0
    for index, window in enumerate(windows, start=1):
        subset = _slice(grouped, window)
        orb, bt = _configs(FROZEN_ORB)
        result = run_backtest(subset, orb_config=orb, bt_config=bt, symbol="MES")
        _, stress_bt = _configs(FROZEN_ORB, doubled_costs=True)
        stress = run_backtest(subset, orb_config=orb, bt_config=stress_bt, symbol="MES")
        base_metrics = _metrics(result, market_days=len(window))
        stress_metrics = _metrics(stress, market_days=len(window))
        aggregate_pnl += result.total_pnl
        aggregate_stress_pnl += stress.total_pnl
        rows.append({
            "window": index,
            "start": window[0],
            "end": window[-1],
            "sessions": len(window),
            "base": base_metrics,
            "double_costs": stress_metrics,
        })

    traded = [row for row in rows if row["base"]["trades"] > 0]  # type: ignore[index]
    return {
        "dataset": str(csv_path),
        "candidate": asdict(FROZEN_ORB),
        "window_sessions": window_sessions,
        "windows": rows,
        "summary": {
            "window_count": len(rows),
            "traded_window_count": len(traded),
            "profitable_base_windows": sum(row["base"]["total_pnl"] > 0 for row in traded),  # type: ignore[index]
            "profitable_double_cost_windows": sum(row["double_costs"]["total_pnl"] > 0 for row in traded),  # type: ignore[index]
            "aggregate_pnl": round(aggregate_pnl, 2),
            "aggregate_double_cost_pnl": round(aggregate_stress_pnl, 2),
            "worst_window_drawdown": max((row["base"]["max_drawdown"] for row in traded), default=0),  # type: ignore[index]
            "worst_double_cost_drawdown": max((row["double_costs"]["max_drawdown"] for row in traded), default=0),  # type: ignore[index]
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--window-sessions", type=int, default=126)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "mes_orb_rolling_diagnosis.json")
    args = parser.parse_args()
    report = diagnose(args.csv, window_sessions=args.window_sessions)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
