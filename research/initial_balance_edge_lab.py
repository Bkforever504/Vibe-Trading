#!/usr/bin/env python3
"""Preregistered Initial Balance and opening-range challenger lab.

Research only. This module contains no broker, scheduler, or order-routing code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MES_CSV = ROOT / "examples" / "mes_v0_1m_2022-01-01_2026-07-19_rth.csv"
NQ_CSV = ROOT / "examples" / "nq_5m_60d.csv"
SPY_PARQUET = ROOT / "data" / "spy_1m_edge_lab.parquet"
REPORT = ROOT / "data" / "initial_balance_edge_results.json"

STRATEGIES = (
    "extreme_order_sweep",
    "close_confirmed_sweep",
    "aggressive_close_sweep",
    "close_breakout_1r",
)


@dataclass(frozen=True)
class MarketSpec:
    name: str
    tick_size: float
    point_value: float | None = None
    commission_round_trip: float = 0.0
    slippage_ticks_per_side: int = 1
    slippage_bps_per_side: float = 0.0


MES = MarketSpec("MES", tick_size=0.25, point_value=5.0, commission_round_trip=2.48)
MNQ = MarketSpec("MNQ", tick_size=0.25, point_value=2.0, commission_round_trip=2.48)
SPY = MarketSpec("SPY", tick_size=0.01, slippage_bps_per_side=1.0)


def load_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["timestamp"]).set_index("timestamp")
    return normalize(frame)


def load_parquet(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    frame.index = pd.to_datetime(frame.index)
    return normalize(frame)


def normalize(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.sort_index()
    if frame.index.tz is not None:
        frame.index = frame.index.tz_convert("America/New_York").tz_localize(None)
    if frame.index.has_duplicates:
        frame = frame[~frame.index.duplicated(keep="last")]
    required = ["open", "high", "low", "close", "volume"]
    missing = set(required).difference(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    return frame[required].astype(float).between_time("09:30", "15:59")


def _bar_minutes(frame: pd.DataFrame) -> int:
    differences = frame.index.to_series().diff().dt.total_seconds().div(60)
    intraday = differences[(differences > 0) & (differences <= 15)]
    if intraday.empty:
        raise ValueError("cannot infer bar resolution")
    return int(intraday.mode().iloc[0])


def complete_sessions(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    step = _bar_minutes(frame)
    expected = 390 // step
    complete: list[pd.DataFrame] = []
    total = 0
    for _, bars in frame.groupby(frame.index.date, sort=True):
        total += 1
        expected_index = pd.date_range(
            bars.index[0].normalize() + pd.Timedelta(hours=9, minutes=30),
            periods=expected,
            freq=f"{step}min",
        )
        if len(bars) == expected and bars.index.equals(expected_index):
            complete.append(bars)
    output = pd.concat(complete) if complete else frame.iloc[:0].copy()
    return output, {
        "raw_sessions": total,
        "complete_sessions": len(complete),
        "excluded_incomplete_sessions": total - len(complete),
        "bar_minutes": step,
        "expected_bars_per_session": expected,
    }


def _opening_end(minutes: int) -> time:
    if minutes == 15:
        return time(9, 44)
    if minutes == 60:
        return time(10, 29)
    raise ValueError("opening_minutes must be 15 or 60")


def _session_context(bars: pd.DataFrame, opening_minutes: int) -> dict[str, Any] | None:
    opening = bars.between_time("09:30", _opening_end(opening_minutes).strftime("%H:%M"))
    future = bars[bars.index.time > _opening_end(opening_minutes)]
    if opening.empty or future.empty:
        return None
    high = float(opening["high"].max())
    low = float(opening["low"].min())
    width = high - low
    if width <= 0:
        return None
    high_at = opening.index[opening["high"] == high][0]
    low_at = opening.index[opening["low"] == low][0]
    order = "high_first" if high_at < low_at else "low_first" if low_at < high_at else "tie"
    close = float(opening.iloc[-1]["close"])
    location = (close - low) / width
    return {
        "opening": opening,
        "future": future,
        "high": high,
        "low": low,
        "width": width,
        "order": order,
        "close_location": location,
    }


def descriptive(frame: pd.DataFrame, opening_minutes: int) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for day, bars in frame.groupby(frame.index.date, sort=True):
        context = _session_context(bars, opening_minutes)
        if context is None:
            continue
        future = context["future"]
        high_wick = bool((future["high"] > context["high"]).any())
        low_wick = bool((future["low"] < context["low"]).any())
        high_close = bool((future["close"] > context["high"]).any())
        low_close = bool((future["close"] < context["low"]).any())
        target_swept = (
            bool((future["low"] <= context["low"]).any())
            if context["order"] == "high_first"
            else bool((future["high"] >= context["high"]).any())
            if context["order"] == "low_first"
            else False
        )
        rows.append({
            "date": str(day),
            "order": context["order"],
            "close_location": context["close_location"],
            "high_wick": high_wick,
            "low_wick": low_wick,
            "high_close": high_close,
            "low_close": low_close,
            "target_swept": target_swept,
        })
    total = len(rows)

    def frequency(predicate: Any) -> float | None:
        return round(sum(bool(predicate(row)) for row in rows) / total, 4) if total else None

    non_ties = [row for row in rows if row["order"] != "tie"]
    aggressive = [
        row for row in non_ties
        if (row["order"] == "high_first" and row["close_location"] <= 0.25)
        or (row["order"] == "low_first" and row["close_location"] >= 0.75)
    ]
    high_first_50_75 = [
        row for row in non_ties
        if row["order"] == "high_first" and 0.50 <= row["close_location"] <= 0.75
    ]
    high_first_aggressive = [
        row for row in non_ties
        if row["order"] == "high_first" and row["close_location"] <= 0.25
    ]
    return {
        "sessions": total,
        "wick": {
            "any_break": frequency(lambda row: row["high_wick"] or row["low_wick"]),
            "single_break": frequency(lambda row: row["high_wick"] ^ row["low_wick"]),
            "double_break": frequency(lambda row: row["high_wick"] and row["low_wick"]),
            "no_break": frequency(lambda row: not row["high_wick"] and not row["low_wick"]),
        },
        "close": {
            "any_break": frequency(lambda row: row["high_close"] or row["low_close"]),
            "single_break": frequency(lambda row: row["high_close"] ^ row["low_close"]),
            "double_break": frequency(lambda row: row["high_close"] and row["low_close"]),
            "no_break": frequency(lambda row: not row["high_close"] and not row["low_close"]),
        },
        "opposite_boundary_sweep_after_extreme_order": {
            "sample": len(non_ties),
            "frequency": round(sum(row["target_swept"] for row in non_ties) / len(non_ties), 4) if non_ties else None,
        },
        "opposite_boundary_sweep_after_aggressive_close": {
            "sample": len(aggressive),
            "frequency": round(sum(row["target_swept"] for row in aggressive) / len(aggressive), 4) if aggressive else None,
        },
        "low_sweep_after_high_first_close_50_75": {
            "sample": len(high_first_50_75),
            "frequency": (
                round(sum(row["target_swept"] for row in high_first_50_75) / len(high_first_50_75), 4)
                if high_first_50_75 else None
            ),
        },
        "low_sweep_after_high_first_aggressive_close": {
            "sample": len(high_first_aggressive),
            "frequency": (
                round(sum(row["target_swept"] for row in high_first_aggressive) / len(high_first_aggressive), 4)
                if high_first_aggressive else None
            ),
        },
    }


def _cost_r(spec: MarketSpec, entry: float, risk: float) -> float:
    if spec.point_value:
        price_cost = (
            2 * spec.slippage_ticks_per_side * spec.tick_size
            + spec.commission_round_trip / spec.point_value
        )
    else:
        price_cost = 2 * entry * spec.slippage_bps_per_side / 10_000.0
    return price_cost / risk


def _exit_r(
    future: pd.DataFrame,
    *,
    side: int,
    entry: float,
    stop: float,
    target: float,
    cost_r: float,
) -> tuple[float, float, str]:
    risk = abs(entry - stop)
    for _, bar in future.iterrows():
        stop_hit = float(bar["low"]) <= stop if side > 0 else float(bar["high"]) >= stop
        target_hit = float(bar["high"]) >= target if side > 0 else float(bar["low"]) <= target
        if stop_hit:
            return -1.0, round(-1.0 - cost_r, 6), "stop"
        if target_hit:
            gross_r = abs(target - entry) / risk
            return round(gross_r, 6), round(gross_r - cost_r, 6), "target"
    exit_price = float(future.iloc[-1]["close"])
    gross_r = (exit_price - entry) * side / risk
    return round(gross_r, 6), round(gross_r - cost_r, 6), "eod"


def _sweep_trade(
    context: dict[str, Any],
    strategy: str,
    spec: MarketSpec,
) -> dict[str, Any] | None:
    order = context["order"]
    location = context["close_location"]
    if order == "tie":
        return None
    if strategy == "close_confirmed_sweep":
        if not ((order == "high_first" and location < 0.5) or (order == "low_first" and location > 0.5)):
            return None
    if strategy == "aggressive_close_sweep":
        if not ((order == "high_first" and location <= 0.25) or (order == "low_first" and location >= 0.75)):
            return None
    future = context["future"]
    entry = float(future.iloc[0]["open"])
    side = -1 if order == "high_first" else 1
    target = context["low"] if side < 0 else context["high"]
    if (side < 0 and target >= entry) or (side > 0 and target <= entry):
        return None
    risk = abs(entry - target)
    if risk <= spec.tick_size:
        return None
    stop = entry + risk if side < 0 else entry - risk
    cost_r = _cost_r(spec, entry, risk)
    gross_r, net_r, outcome = _exit_r(
        future,
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        cost_r=cost_r,
    )
    return {
        "gross_r": gross_r,
        "cost_r": round(cost_r, 6),
        "net_r": net_r,
        "outcome": outcome,
        "direction": "long" if side > 0 else "short",
    }


def _breakout_trade(context: dict[str, Any], spec: MarketSpec) -> dict[str, Any] | None:
    future = context["future"]
    trigger_position: int | None = None
    side = 0
    for position, (_, bar) in enumerate(future.iterrows()):
        if float(bar["close"]) > context["high"]:
            trigger_position, side = position, 1
            break
        if float(bar["close"]) < context["low"]:
            trigger_position, side = position, -1
            break
    if trigger_position is None or trigger_position + 1 >= len(future):
        return None
    execution = future.iloc[trigger_position + 1:]
    entry = float(execution.iloc[0]["open"])
    stop = context["low"] if side > 0 else context["high"]
    risk = abs(entry - stop)
    if risk <= spec.tick_size:
        return None
    target = entry + side * risk
    cost_r = _cost_r(spec, entry, risk)
    gross_r, net_r, outcome = _exit_r(
        execution,
        side=side,
        entry=entry,
        stop=stop,
        target=target,
        cost_r=cost_r,
    )
    return {
        "gross_r": gross_r,
        "cost_r": round(cost_r, 6),
        "net_r": net_r,
        "outcome": outcome,
        "direction": "long" if side > 0 else "short",
    }


def replay(frame: pd.DataFrame, opening_minutes: int, spec: MarketSpec) -> dict[str, list[dict[str, Any]]]:
    output = {name: [] for name in STRATEGIES}
    for day, bars in frame.groupby(frame.index.date, sort=True):
        context = _session_context(bars, opening_minutes)
        if context is None:
            continue
        for strategy in STRATEGIES:
            trade = (
                _breakout_trade(context, spec)
                if strategy == "close_breakout_1r"
                else _sweep_trade(context, strategy, spec)
            )
            if trade:
                output[strategy].append({"date": str(day), **trade})
    return output


def _moving_block_ci(
    values: list[float],
    *,
    percentiles: tuple[float, float] = (2.5, 97.5),
    seed: int = 20260725,
) -> list[float | None]:
    if len(values) < 10:
        return [None, None]
    rng = np.random.default_rng(seed)
    data = np.asarray(values, dtype=float)
    block = min(5, len(data))
    starts = np.arange(0, len(data) - block + 1)
    blocks_needed = int(np.ceil(len(data) / block))
    selected_starts = rng.choice(starts, size=(2000, blocks_needed))
    offsets = np.arange(block)
    indices = (selected_starts[:, :, None] + offsets).reshape(2000, -1)[:, :len(data)]
    means = data[indices].mean(axis=1)
    low, high = np.percentile(means, percentiles)
    return [round(float(low), 4), round(float(high), 4)]


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(trade["net_r"]) for trade in trades]
    gross_values = [float(trade["gross_r"]) for trade in trades]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "trades": len(values),
        "positive_return_rate": round(len(wins) / len(values), 4) if values else None,
        "target_hit_rate": (
            round(sum(trade["outcome"] == "target" for trade in trades) / len(trades), 4)
            if trades else None
        ),
        "stop_hit_rate": (
            round(sum(trade["outcome"] == "stop" for trade in trades) / len(trades), 4)
            if trades else None
        ),
        "gross_expectancy_r": round(float(np.mean(gross_values)), 4) if gross_values else None,
        "average_cost_r": (
            round(float(np.mean([float(trade["cost_r"]) for trade in trades])), 4)
            if trades else None
        ),
        "expectancy_r": round(float(np.mean(values)), 4) if values else None,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else ("inf" if wins else None),
        "max_drawdown_r": round(drawdown, 4),
        "expectancy_95pct_moving_5_trade_block_ci": _moving_block_ci(values),
        "expectancy_familywise_95pct_8_tests_ci": _moving_block_ci(
            values,
            percentiles=(0.3125, 99.6875),
        ),
    }


def _partition(trades: list[dict[str, Any]], all_dates: list[str]) -> dict[str, list[dict[str, Any]]]:
    first = int(len(all_dates) * 0.60)
    second = int(len(all_dates) * 0.80)
    boundaries = (set(all_dates[:first]), set(all_dates[first:second]), set(all_dates[second:]))
    return {
        name: [trade for trade in trades if trade["date"] in dates]
        for name, dates in zip(("development", "selection", "diagnostic_later"), boundaries)
    }


def evaluate_market(frame: pd.DataFrame, spec: MarketSpec, *, resolution: str) -> dict[str, Any]:
    frame, coverage = complete_sessions(frame)
    dates = sorted({str(day) for day in frame.index.date})
    windows: dict[str, Any] = {}
    for minutes in (15, 60):
        trades = replay(frame, minutes, spec)
        strategies = {}
        for name, rows in trades.items():
            parts = _partition(rows, dates)
            strategies[name] = {
                "aggregate": metrics(rows),
                **{part: metrics(part_rows) for part, part_rows in parts.items()},
            }
        windows[f"{minutes}m"] = {
            "descriptive": descriptive(frame, minutes),
            "strategies": strategies,
        }
    return {
        "market": spec.name,
        "resolution": resolution,
        "coverage": coverage,
        "sessions": len(dates),
        "first_session": dates[0] if dates else None,
        "last_session": dates[-1] if dates else None,
        "windows": windows,
    }


def evaluate(mes: pd.DataFrame, spy: pd.DataFrame, nq: pd.DataFrame) -> dict[str, Any]:
    source_files = (MES_CSV, SPY_PARQUET, NQ_CSV)
    return {
        "schema_version": 1,
        "experiment": "IB-OR-CHALLENGER-2026-07-25",
        "mode": "research_only",
        "execution_enabled": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_files
        },
        "cost_specs": {
            spec.name: {
                "tick_size": spec.tick_size,
                "point_value": spec.point_value,
                "commission_round_trip": spec.commission_round_trip,
                "slippage_ticks_per_side": spec.slippage_ticks_per_side,
                "slippage_bps_per_side": spec.slippage_bps_per_side,
            }
            for spec in (MES, MNQ, SPY)
        },
        "markets": {
            "MES": evaluate_market(mes, MES, resolution="1m"),
            "SPY": evaluate_market(spy, SPY, resolution="1m-IEX-underlying-only"),
            "MNQ_proxy": evaluate_market(nq, MNQ, resolution="5m-NQ-price-path-limited-sample"),
        },
        "warnings": [
            "Descriptive break frequency is not executable expectancy.",
            "SPY option P&L is not inferred from underlying bars.",
            "NQ history is a short portability diagnostic, not a promotion gate.",
            "All datasets were consumed by prior research; diagnostic_later is not globally untouched.",
            "No orders, schedulers, broker state, or execution gates were changed.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mes-csv", type=Path, default=MES_CSV)
    parser.add_argument("--spy-parquet", type=Path, default=SPY_PARQUET)
    parser.add_argument("--nq-csv", type=Path, default=NQ_CSV)
    parser.add_argument("--out", type=Path, default=REPORT)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = evaluate(load_csv(args.mes_csv), load_parquet(args.spy_parquet), load_csv(args.nq_csv))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.do_print:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
