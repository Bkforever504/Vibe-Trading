#!/usr/bin/env python3
"""Chronological 5-minute replay for the ICT macro shadow strategy."""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ict_macro_shadow_logger import SYMBOLS, fetch_futures
from scripts.market_catalyst_calendar import risk_window_for_date
from strategies.ict_macro_shadow import build_session_levels, evaluate_macro_setup

POINT_VALUE = {"MNQ": 2.0, "MES": 5.0}


@dataclass(frozen=True)
class ReplayCosts:
    slippage_ticks_per_side: float = 1.0
    tick_size: float = 0.25
    commission_round_trip: float = 1.24


def _high_impact_day_veto(day: date) -> bool:
    risk = risk_window_for_date(day)
    return risk.get("max_impact") == "high" and any(
        event.get("time_et") in {"all_day", "14:00"} for event in risk.get("events", [])
    )


def resolve_outcome(
    day_bars: pd.DataFrame,
    signal: dict[str, Any],
    *,
    symbol: str,
    costs: ReplayCosts | None = None,
) -> dict[str, Any]:
    """Resolve bars after entry; ties are counted as stops conservatively."""
    costs = costs or ReplayCosts()
    entry_at = pd.Timestamp(signal["entry_at"])
    index = pd.to_datetime(day_bars.index)
    if index.tz is None:
        index = index.tz_localize("America/New_York")
    else:
        index = index.tz_convert("America/New_York")
    bars = day_bars.copy()
    bars.index = index
    future = bars[bars.index > entry_at]
    entry = float(signal["entry"])
    stop = float(signal["stop"])
    target = float(signal["target"])
    direction = str(signal["direction"])
    exit_price = float(future.iloc[-1]["close"]) if not future.empty else entry
    outcome = "eod"
    exit_at = future.index[-1].isoformat() if not future.empty else entry_at.isoformat()
    for timestamp, row in future.iterrows():
        stop_hit = float(row["low"]) <= stop if direction == "buy" else float(row["high"]) >= stop
        target_hit = float(row["high"]) >= target if direction == "buy" else float(row["low"]) <= target
        if stop_hit:
            exit_price, outcome, exit_at = stop, "loss", timestamp.isoformat()
            break
        if target_hit:
            exit_price, outcome, exit_at = target, "win", timestamp.isoformat()
            break
    raw_points = exit_price - entry if direction == "buy" else entry - exit_price
    slippage_points = 2.0 * costs.slippage_ticks_per_side * costs.tick_size
    net_pnl = raw_points * POINT_VALUE[symbol] - slippage_points * POINT_VALUE[symbol] - costs.commission_round_trip
    return {
        "outcome": outcome,
        "exit_at": exit_at,
        "exit": round(exit_price, 4),
        "raw_points": round(raw_points, 4),
        "net_pnl": round(net_pnl, 2),
    }


def replay_symbol(symbol: str, bars: pd.DataFrame, costs: ReplayCosts | None = None) -> dict[str, Any]:
    costs = costs or ReplayCosts()
    frame = bars.copy().sort_index()
    index = pd.to_datetime(frame.index)
    if index.tz is None:
        index = index.tz_localize("America/New_York")
    else:
        index = index.tz_convert("America/New_York")
    frame.index = index
    dates = sorted(set(frame.index.date))
    trades: list[dict[str, Any]] = []
    statuses: dict[str, int] = {}
    for trading_day in dates[1:]:
        history = frame[frame.index.date <= trading_day]
        day_bars = frame[frame.index.date == trading_day]
        levels = build_session_levels(history, trading_day)
        signal = evaluate_macro_setup(
            day_bars,
            levels=levels,
            high_impact_news_veto=_high_impact_day_veto(trading_day),
        )
        status = str(signal.get("status", "unknown"))
        statuses[status] = statuses.get(status, 0) + 1
        if status != "signal":
            continue
        outcome = resolve_outcome(day_bars, signal, symbol=symbol, costs=costs)
        trades.append({"date": trading_day.isoformat(), **signal, **outcome})
    split = max(1, math.floor(len(trades) * 0.70)) if trades else 0
    all_metrics = summarize(trades)
    holdout_metrics = summarize(trades[split:])
    return {
        "symbol": symbol,
        "data_symbol": SYMBOLS[symbol],
        "days_evaluated": max(0, len(dates) - 1),
        "statuses": statuses,
        "costs": asdict(costs),
        "all": all_metrics,
        "train": summarize(trades[:split]),
        "holdout": holdout_metrics,
        "readiness": readiness(all_metrics, holdout_metrics),
        "trades": trades,
    }


def summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    pnl = [float(trade["net_pnl"]) for trade in trades]
    wins = [value for value in pnl if value > 0]
    losses = [value for value in pnl if value < 0]
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trades": len(trades),
        "wins": len(wins),
        "win_rate": round(len(wins) / len(trades), 4) if trades else None,
        "net_pnl": round(sum(pnl), 2),
        "expectancy": round(sum(pnl) / len(trades), 2) if trades else None,
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else (None if not wins else "inf"),
        "max_drawdown": round(max_drawdown, 2),
    }


def readiness(all_metrics: dict[str, Any], holdout_metrics: dict[str, Any]) -> dict[str, Any]:
    """Evidence score, not a prediction of future profitability."""
    checks = {
        "at_least_30_total_trades": int(all_metrics["trades"]) >= 30,
        "at_least_10_holdout_trades": int(holdout_metrics["trades"]) >= 10,
        "positive_total_expectancy": float(all_metrics["expectancy"] or 0) > 0,
        "total_profit_factor_above_one": (
            all_metrics["profit_factor"] == "inf"
            or isinstance(all_metrics["profit_factor"], (int, float)) and float(all_metrics["profit_factor"]) > 1
        ),
        "positive_holdout_expectancy": float(holdout_metrics["expectancy"] or 0) > 0,
        "holdout_profit_factor_above_one": (
            holdout_metrics["profit_factor"] == "inf"
            or isinstance(holdout_metrics["profit_factor"], (int, float)) and float(holdout_metrics["profit_factor"]) > 1
        ),
    }
    passed = sum(checks.values())
    return {
        "evidence_confidence_score": round(1.0 + 8.0 * passed / len(checks), 1),
        "verdict": "SHADOW_ONLY" if all(checks.values()) else "BLOCKED",
        "checks": checks,
        "note": "Score measures available validation evidence, not expected returns.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="MNQ,MES")
    parser.add_argument("--period", default="60d")
    parser.add_argument("--output", type=Path, default=Path.home() / ".vibe-trading" / "reports" / "ict-macro-replay.json")
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    symbols = [value.strip().upper() for value in args.symbols.split(",") if value.strip()]
    rows = [replay_symbol(symbol, fetch_futures(symbol, args.period)) for symbol in symbols]
    report = {"schema_version": 1, "mode": "research_only", "execution_enabled": False, "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    if args.do_print:
        for row in rows:
            print(f"{row['symbol']} all={row['all']} holdout={row['holdout']}")
        print("No orders placed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
