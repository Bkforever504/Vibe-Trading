#!/usr/bin/env python3
"""Preregistered, cost-aware Fibonacci retracement placebo tournament.

Research only: no broker imports, credentials, scheduler, or order routing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.fibonacci_structure import FibonacciConfig, confirmed_pivots


DEFAULT_INPUT = ROOT / "data" / "liquid_edge_lab" / "spy_5m.parquet"
DEFAULT_OUTPUT = ROOT / "data" / "fibonacci_structure_lab.json"
GOLDEN = round((5 ** 0.5 - 1) / 2, 6)
RATIO_TOURNAMENT = (0.382, 0.5, 0.55, 0.6, GOLDEN, 0.65, 0.7)


@dataclass(frozen=True)
class LabConfig:
    zone_half_width: float = 0.025
    invalidation_gap: float = 0.168
    minimum_impulse_atr: float = 1.25
    entry_start: str = "10:00"
    entry_end: str = "14:30"
    round_trip_cost_bps: float = 2.0
    minimum_holdout_trades: int = 50


def _normalize(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path).copy().sort_index()
    frame.index = pd.to_datetime(frame.index)
    if frame.index.tz is not None:
        frame.index = frame.index.tz_convert("America/New_York").tz_localize(None)
    frame = frame[~frame.index.duplicated(keep="last")]
    required = ["open", "high", "low", "close", "volume"]
    missing = set(required).difference(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    return frame[required].astype(float).between_time("09:30", "15:59")


def _atr(bars: pd.DataFrame, length: int = 14) -> pd.Series:
    previous = bars["close"].shift(1)
    tr = pd.concat(
        [bars["high"] - bars["low"], (bars["high"] - previous).abs(), (bars["low"] - previous).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(length, min_periods=length).mean()


def _impulses_for_session(bars: pd.DataFrame, config: FibonacciConfig) -> list[dict[str, Any]]:
    pivots = confirmed_pivots(
        bars, left_bars=config.left_bars, right_bars=config.right_bars
    )
    impulses: list[dict[str, Any]] = []
    for left, right in zip(pivots, pivots[1:]):
        if left["kind"] == "low" and right["kind"] == "high" and right["price"] > left["price"]:
            direction = 1
        elif left["kind"] == "high" and right["kind"] == "low" and left["price"] > right["price"]:
            direction = -1
        else:
            continue
        impulses.append(
            {
                "direction": direction,
                "start": left,
                "end": right,
                "available_position": right["confirmed_position"],
                "size": abs(float(right["price"]) - float(left["price"])),
            }
        )
    return impulses


def _simulate_trade(
    future: pd.DataFrame,
    *,
    direction: int,
    entry: float,
    stop: float,
    target: float,
    cost_bps: float,
) -> dict[str, Any]:
    risk = abs(entry - stop)
    if risk <= 0 or (direction == 1 and target <= entry) or (direction == -1 and target >= entry):
        return {"valid": False}
    exit_price = float(future.iloc[-1]["close"])
    reason = "session_close"
    for timestamp, bar in future.iterrows():
        stop_hit = float(bar["low"]) <= stop if direction == 1 else float(bar["high"]) >= stop
        target_hit = float(bar["high"]) >= target if direction == 1 else float(bar["low"]) <= target
        if stop_hit:
            exit_price, reason = stop, "stop_first"
            break
        if target_hit:
            exit_price, reason = target, "target"
            break
    gross_r = direction * (exit_price - entry) / risk
    cost_r = (entry * cost_bps / 10_000.0) / risk
    return {
        "valid": True,
        "exit_reason": reason,
        "gross_r": gross_r,
        "net_r": gross_r - cost_r,
        "cost_r": cost_r,
    }


def _session_signal(
    bars: pd.DataFrame,
    ratio: float,
    *,
    lab: LabConfig,
    fib: FibonacciConfig,
    cost_multiplier: float,
) -> dict[str, Any] | None:
    atr = _atr(bars, fib.atr_length)
    impulses = _impulses_for_session(bars, fib)
    start_time = pd.Timestamp(lab.entry_start).time()
    end_time = pd.Timestamp(lab.entry_end).time()
    for position in range(1, len(bars) - 1):
        timestamp = bars.index[position]
        if timestamp.time() < start_time or timestamp.time() > end_time:
            continue
        available = [item for item in impulses if item["available_position"] <= position and item["end"]["position"] < position]
        if not available:
            continue
        impulse = available[-1]
        current_atr = float(atr.iloc[position]) if pd.notna(atr.iloc[position]) else 0.0
        if current_atr <= 0 or impulse["size"] / current_atr < lab.minimum_impulse_atr:
            continue
        direction = int(impulse["direction"])
        end_price = float(impulse["end"]["price"])
        size = float(impulse["size"])
        level = end_price - direction * size * ratio
        upper = end_price - direction * size * (ratio - lab.zone_half_width)
        lower = end_price - direction * size * (ratio + lab.zone_half_width)
        zone_low, zone_high = min(lower, upper), max(lower, upper)
        bar = bars.iloc[position]
        previous = bars.iloc[position - 1]
        touched = float(bar["low"]) <= zone_high and float(bar["high"]) >= zone_low
        rejection = (
            float(bar["close"]) >= level
            and float(bar["close"]) > float(bar["open"])
            and float(bar["close"]) > float(previous["close"])
            if direction == 1
            else float(bar["close"]) <= level
            and float(bar["close"]) < float(bar["open"])
            and float(bar["close"]) < float(previous["close"])
        )
        if not (touched and rejection):
            continue
        entry = float(bars.iloc[position + 1]["open"])
        stop_ratio = min(0.886, ratio + lab.invalidation_gap)
        stop = end_price - direction * size * stop_ratio
        target = end_price
        outcome = _simulate_trade(
            bars.iloc[position + 1 :],
            direction=direction,
            entry=entry,
            stop=stop,
            target=target,
            cost_bps=lab.round_trip_cost_bps * cost_multiplier,
        )
        if not outcome.get("valid"):
            continue
        return {
            "date": str(timestamp.date()),
            "timestamp": timestamp.isoformat(),
            "ratio": ratio,
            "direction": "long" if direction == 1 else "short",
            "entry": entry,
            "stop": stop,
            "target": target,
            "impulse_atr": impulse["size"] / current_atr,
            **outcome,
        }
    return None


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = np.array([float(row["net_r"]) for row in rows], dtype=float)
    if not len(values):
        return {"trades": 0, "dates": 0, "expectancy_r": None, "win_rate": None, "profit_factor": None, "max_drawdown_r": None}
    wins = values[values > 0].sum()
    losses = abs(values[values < 0].sum())
    equity = values.cumsum()
    peak = np.maximum.accumulate(np.r_[0.0, equity])
    drawdown = peak[1:] - equity
    return {
        "trades": int(len(values)),
        "dates": len({row["date"] for row in rows}),
        "expectancy_r": round(float(values.mean()), 5),
        "win_rate": round(float((values > 0).mean()), 5),
        "profit_factor": round(float(wins / losses), 4) if losses > 0 else None,
        "net_r": round(float(values.sum()), 4),
        "max_drawdown_r": round(float(drawdown.max(initial=0.0)), 4),
    }


def _split_dates(frame: pd.DataFrame) -> dict[str, set]:
    dates = sorted(set(frame.index.date))
    first = int(len(dates) * 0.6)
    second = int(len(dates) * 0.8)
    return {
        "development": set(dates[:first]),
        "selection": set(dates[first:second]),
        "holdout": set(dates[second:]),
    }


def build_report(path: Path, lab: LabConfig = LabConfig()) -> dict[str, Any]:
    frame = _normalize(path)
    fib = FibonacciConfig(min_impulse_atr=lab.minimum_impulse_atr)
    splits = _split_dates(frame)
    results: dict[str, Any] = {}
    raw: dict[float, dict[float, list[dict[str, Any]]]] = {}
    for ratio in RATIO_TOURNAMENT:
        raw[ratio] = {1.0: [], 2.0: []}
        for _, session in frame.groupby(frame.index.date, sort=True):
            for cost_multiplier in (1.0, 2.0):
                row = _session_signal(
                    session,
                    ratio,
                    lab=lab,
                    fib=fib,
                    cost_multiplier=cost_multiplier,
                )
                if row:
                    raw[ratio][cost_multiplier].append(row)
        stages = {}
        for stage, dates in splits.items():
            base = [row for row in raw[ratio][1.0] if pd.Timestamp(row["date"]).date() in dates]
            stress = [row for row in raw[ratio][2.0] if pd.Timestamp(row["date"]).date() in dates]
            stages[stage] = {"base_cost": _metrics(base), "double_cost": _metrics(stress)}
        results[str(ratio)] = stages

    golden = results[str(GOLDEN)]
    holdout = golden["holdout"]["base_cost"]
    stress = golden["holdout"]["double_cost"]
    placebo_expectancies = [
        results[str(ratio)]["holdout"]["base_cost"].get("expectancy_r")
        for ratio in RATIO_TOURNAMENT
        if ratio != GOLDEN
    ]
    placebo_expectancies = [float(value) for value in placebo_expectancies if value is not None]
    placebo_median = float(np.median(placebo_expectancies)) if placebo_expectancies else None
    gates = {
        "minimum_holdout_trades": holdout["trades"] >= lab.minimum_holdout_trades,
        "positive_holdout_expectancy": (holdout.get("expectancy_r") or 0) > 0,
        "holdout_profit_factor_gte_1_10": (holdout.get("profit_factor") or 0) >= 1.10,
        "positive_double_cost_holdout": (stress.get("expectancy_r") or 0) > 0,
        "beats_median_placebo": placebo_median is not None and (holdout.get("expectancy_r") or 0) > placebo_median,
    }
    input_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "research_only_no_execution_authority",
        "hypothesis": "0.618 rejection has incremental OOS value over nearby non-Fibonacci pullback ratios",
        "input": str(path),
        "input_sha256": input_hash,
        "date_range": [str(frame.index.min()), str(frame.index.max())],
        "sessions": len(set(frame.index.date)),
        "lab_config": asdict(lab),
        "fibonacci_config": asdict(fib),
        "ratios": list(RATIO_TOURNAMENT),
        "same_bar_ambiguity": "stop_first",
        "entry_timing": "next_bar_open_after_completed_rejection_bar",
        "results": results,
        "golden_holdout": holdout,
        "golden_double_cost_holdout": stress,
        "placebo_holdout_median_expectancy_r": round(placebo_median, 5) if placebo_median is not None else None,
        "promotion_gates": gates,
        "promotion_passed": all(gates.values()),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("golden_holdout", "golden_double_cost_holdout", "placebo_holdout_median_expectancy_r", "promotion_gates", "promotion_passed")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
