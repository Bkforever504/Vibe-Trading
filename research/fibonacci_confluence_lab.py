#!/usr/bin/env python3
"""Causal Fibonacci anchoring and staged confluence backtest.

Research only. This module has no broker, credential, scheduler, or order code.
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

from strategies.fibonacci_structure import confirmed_zigzag_pivots


DATA_DIR = ROOT / "data" / "liquid_edge_lab"
DEFAULT_OUTPUT = ROOT / "data" / "fibonacci_confluence_limit_lab.json"
GOLDEN = round((5 ** 0.5 - 1) / 2, 6)
RATIOS = (0.382, 0.5, GOLDEN)
STAGES = (
    "fib_touch",
    "fib_rejection",
    "fib_rejection_trend",
    "fib_rejection_trend_vwap",
    "fib_rejection_trend_vwap_volume",
)


@dataclass(frozen=True)
class Config:
    atr_length: int = 14
    zigzag_reversal_atr: float = 0.75
    minimum_impulse_atr: float = 2.0
    zone_half_width: float = 0.025
    stop_buffer_atr: float = 0.05
    maximum_impulse_age_bars: int = 48
    entry_start: str = "10:00"
    entry_end: str = "14:30"
    relative_volume_minimum: float = 1.20
    round_trip_cost_bps: float = 2.0
    minimum_reward_risk: float = 1.0
    minimum_target_to_cost: float = 3.0
    minimum_final_trades: int = 40


def load_market(symbol: str) -> pd.DataFrame:
    path = DATA_DIR / f"{symbol.lower()}_5m.parquet"
    frame = pd.read_parquet(path).copy().sort_index()
    frame.index = pd.to_datetime(frame.index)
    if frame.index.tz is not None:
        frame.index = frame.index.tz_convert("America/New_York").tz_localize(None)
    frame = frame[~frame.index.duplicated(keep="last")]
    required = ["open", "high", "low", "close", "volume"]
    missing = set(required).difference(frame.columns)
    if missing:
        raise ValueError(f"{symbol} missing columns: {sorted(missing)}")
    frame = frame[required].astype(float).between_time("09:30", "15:59")
    previous = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr"] = true_range.rolling(14, min_periods=14).mean()
    frame["ema20"] = frame["close"].ewm(span=20, adjust=False).mean()
    frame["ema50"] = frame["close"].ewm(span=50, adjust=False).mean()
    frame["ema20_slope"] = frame["ema20"].diff(5)

    sessions = frame.groupby(frame.index.date, sort=False)
    typical_volume = ((frame["high"] + frame["low"] + frame["close"]) / 3.0) * frame["volume"]
    frame["vwap"] = typical_volume.groupby(frame.index.date).cumsum() / frame["volume"].groupby(frame.index.date).cumsum().replace(0, np.nan)
    frame["volume_median20"] = sessions["volume"].transform(
        lambda values: values.shift(1).rolling(20, min_periods=10).median()
    )
    frame["relative_volume"] = frame["volume"] / frame["volume_median20"].replace(0, np.nan)
    return frame


def _trade_outcome(
    future: pd.DataFrame,
    *,
    direction: int,
    entry: float,
    stop: float,
    target: float,
    cost_bps: float,
) -> dict[str, Any] | None:
    risk = abs(entry - stop)
    if risk <= 0 or (direction == 1 and not stop < entry < target) or (direction == -1 and not target < entry < stop):
        return None
    exit_price = float(future.iloc[-1]["close"])
    reason = "session_close"
    for _, bar in future.iterrows():
        stop_hit = float(bar["low"]) <= stop if direction == 1 else float(bar["high"]) >= stop
        target_hit = float(bar["high"]) >= target if direction == 1 else float(bar["low"]) <= target
        if stop_hit:
            exit_price, reason = stop, "stop_first"
            break
        if target_hit:
            exit_price, reason = target, "target"
            break
    gross_r = direction * (exit_price - entry) / risk
    cost_r = entry * cost_bps / 10_000.0 / risk
    return {
        "exit_reason": reason,
        "gross_r": gross_r,
        "cost_r": cost_r,
        "net_r": gross_r - cost_r,
        "double_cost_net_r": gross_r - 2.0 * cost_r,
    }


def _conditions(
    bar: pd.Series,
    previous: pd.Series,
    *,
    direction: int,
    level: float,
    relative_volume_minimum: float,
) -> dict[str, bool]:
    rejection = (
        float(bar["close"]) >= level
        and float(bar["close"]) > float(bar["open"])
        and float(bar["close"]) > float(previous["close"])
        if direction == 1
        else float(bar["close"]) <= level
        and float(bar["close"]) < float(bar["open"])
        and float(bar["close"]) < float(previous["close"])
    )
    trend = (
        float(bar["close"]) > float(bar["ema20"]) > float(bar["ema50"])
        and float(bar["ema20_slope"]) > 0
        if direction == 1
        else float(bar["close"]) < float(bar["ema20"]) < float(bar["ema50"])
        and float(bar["ema20_slope"]) < 0
    )
    vwap = float(bar["close"]) > float(bar["vwap"]) if direction == 1 else float(bar["close"]) < float(bar["vwap"])
    relative_volume = float(bar.get("relative_volume") or 0.0)
    return {
        "fib_touch": True,
        "fib_rejection": rejection,
        "fib_rejection_trend": rejection and trend,
        "fib_rejection_trend_vwap": rejection and trend and vwap,
        "fib_rejection_trend_vwap_volume": rejection and trend and vwap and relative_volume >= relative_volume_minimum,
    }


def session_events(session: pd.DataFrame, ratio: float, config: Config) -> dict[str, dict[str, Any]]:
    bars = session.reset_index(drop=False)
    price_bars = session[["open", "high", "low", "close"]]
    pivots = confirmed_zigzag_pivots(
        price_bars,
        atr_length=config.atr_length,
        reversal_atr=config.zigzag_reversal_atr,
    )
    impulses = []
    for start, end in zip(pivots, pivots[1:]):
        if start["kind"] == "low" and end["kind"] == "high":
            direction = 1
        elif start["kind"] == "high" and end["kind"] == "low":
            direction = -1
        else:
            continue
        impulses.append({"start": start, "end": end, "direction": direction})

    found: dict[str, dict[str, Any]] = {}
    start_time = pd.Timestamp(config.entry_start).time()
    end_time = pd.Timestamp(config.entry_end).time()
    for position in range(1, len(session) - 1):
        timestamp = session.index[position]
        if timestamp.time() < start_time or timestamp.time() > end_time:
            continue
        available = [
            impulse for impulse in impulses
            if impulse["end"]["confirmed_position"] <= position
            and position - impulse["end"]["position"] <= config.maximum_impulse_age_bars
        ]
        if not available:
            continue
        impulse = available[-1]
        start_price = float(impulse["start"]["price"])
        end_price = float(impulse["end"]["price"])
        size = abs(end_price - start_price)
        current_atr = float(session.iloc[position]["atr"])
        if not np.isfinite(current_atr) or current_atr <= 0 or size / current_atr < config.minimum_impulse_atr:
            continue
        direction = int(impulse["direction"])
        level = end_price - direction * size * ratio
        price_a = end_price - direction * size * (ratio - config.zone_half_width)
        price_b = end_price - direction * size * (ratio + config.zone_half_width)
        zone_low, zone_high = min(price_a, price_b), max(price_a, price_b)
        bar = session.iloc[position]
        previous = session.iloc[position - 1]
        touched = float(bar["low"]) <= zone_high and float(bar["high"]) >= zone_low
        invalidated = float(bar["close"]) <= start_price if direction == 1 else float(bar["close"]) >= start_price
        if not touched or invalidated:
            continue
        conditions = _conditions(
            bar,
            previous,
            direction=direction,
            level=level,
            relative_volume_minimum=config.relative_volume_minimum,
        )
        for stage in STAGES:
            if stage in found or not conditions[stage]:
                continue
            next_bar = session.iloc[position + 1]
            if not float(next_bar["low"]) <= level <= float(next_bar["high"]):
                continue
            entry = level
            stop = start_price - direction * config.stop_buffer_atr * current_atr
            risk = abs(entry - stop)
            reward = abs(end_price - entry)
            round_trip_cost = entry * config.round_trip_cost_bps / 10_000.0
            if risk <= 0 or reward / risk < config.minimum_reward_risk:
                continue
            if round_trip_cost <= 0 or reward / round_trip_cost < config.minimum_target_to_cost:
                continue
            outcome = _trade_outcome(
                session.iloc[position + 1 :],
                direction=direction,
                entry=entry,
                stop=stop,
                target=end_price,
                cost_bps=config.round_trip_cost_bps,
            )
            if outcome is None:
                continue
            found[stage] = {
                "date": str(timestamp.date()),
                "timestamp": timestamp.isoformat(),
                "ratio": ratio,
                "stage": stage,
                "direction": "long" if direction == 1 else "short",
                "entry": entry,
                "stop": stop,
                "target": end_price,
                "impulse_atr": size / current_atr,
                "retracement_level": level,
                "relative_volume": float(bar.get("relative_volume") or 0.0),
                **outcome,
            }
        if len(found) == len(STAGES):
            break
    return found


def collect(frame: pd.DataFrame, ratio: float, config: Config) -> dict[str, list[dict[str, Any]]]:
    rows = {stage: [] for stage in STAGES}
    for _, session in frame.groupby(frame.index.date, sort=True):
        for stage, event in session_events(session, ratio, config).items():
            rows[stage].append(event)
    return rows


def metrics(rows: list[dict[str, Any]], *, double_cost: bool = False) -> dict[str, Any]:
    key = "double_cost_net_r" if double_cost else "net_r"
    values = np.array([float(row[key]) for row in rows], dtype=float)
    if not len(values):
        return {"trades": 0, "expectancy_r": None, "win_rate": None, "profit_factor": None, "max_drawdown_r": None}
    gains = float(values[values > 0].sum())
    losses = abs(float(values[values < 0].sum()))
    equity = values.cumsum()
    peaks = np.maximum.accumulate(np.r_[0.0, equity])
    drawdown = peaks[1:] - equity
    return {
        "trades": len(values),
        "expectancy_r": round(float(values.mean()), 5),
        "win_rate": round(float((values > 0).mean()), 5),
        "profit_factor": round(gains / losses, 4) if losses else None,
        "net_r": round(float(values.sum()), 4),
        "max_drawdown_r": round(float(drawdown.max(initial=0.0)), 4),
    }


def _period(row: dict[str, Any]) -> str:
    year = int(row["date"][:4])
    return "development" if year <= 2023 else "selection" if year == 2024 else "final"


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for period in ("development", "selection", "final"):
        subset = [row for row in rows if _period(row) == period]
        result[period] = {
            "base_cost": metrics(subset),
            "double_cost": metrics(subset, double_cost=True),
        }
    return result


def build_report(config: Config = Config()) -> dict[str, Any]:
    frames = {symbol: load_market(symbol) for symbol in ("SPY", "QQQ", "IWM")}
    corpus: dict[str, Any] = {}
    for symbol, frame in frames.items():
        corpus[symbol] = {}
        for ratio in RATIOS:
            collected = collect(frame, ratio, config)
            corpus[symbol][str(ratio)] = {
                stage: summarize(rows) for stage, rows in collected.items()
            }

    gates = {}
    for stage in STAGES:
        spy = corpus["SPY"][str(GOLDEN)][stage]["final"]
        qqq = corpus["QQQ"][str(GOLDEN)][stage]["final"]["base_cost"]
        iwm = corpus["IWM"][str(GOLDEN)][stage]["final"]["base_cost"]
        base = spy["base_cost"]
        stress = spy["double_cost"]
        checks = {
            "minimum_final_spy_trades": base["trades"] >= config.minimum_final_trades,
            "positive_final_spy_expectancy": (base.get("expectancy_r") or 0) > 0,
            "final_spy_profit_factor_gte_1_10": (base.get("profit_factor") or 0) >= 1.10,
            "positive_final_spy_double_cost": (stress.get("expectancy_r") or 0) > 0,
            "positive_final_qqq_expectancy": (qqq.get("expectancy_r") or 0) > 0,
            "positive_final_iwm_expectancy": (iwm.get("expectancy_r") or 0) > 0,
        }
        gates[stage] = {"checks": checks, "passed": all(checks.values())}

    hashes = {
        symbol: hashlib.sha256((DATA_DIR / f"{symbol.lower()}_5m.parquet").read_bytes()).hexdigest()
        for symbol in frames
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "research_only_no_execution_authority",
        "method": "causal_atr_zigzag_fibonacci_next_bar_limit_staged_confluence",
        "config": asdict(config),
        "ratios": list(RATIOS),
        "stages": list(STAGES),
        "input_sha256": hashes,
        "date_ranges": {symbol: [str(frame.index.min()), str(frame.index.max())] for symbol, frame in frames.items()},
        "results": corpus,
        "golden_stage_gates": gates,
        "any_stage_passed": any(row["passed"] for row in gates.values()),
        "same_bar_ambiguity": "stop_first",
        "entry_timing": "next_bar_limit_at_exact_retracement_or_no_fill",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    compact = {
        "SPY_0.618034": {
            stage: report["results"]["SPY"][str(GOLDEN)][stage]
            for stage in STAGES
        },
        "external_final": {
            symbol: {
                stage: report["results"][symbol][str(GOLDEN)][stage]["final"]["base_cost"]
                for stage in STAGES
            }
            for symbol in ("QQQ", "IWM")
        },
        "gates": report["golden_stage_gates"],
        "any_stage_passed": report["any_stage_passed"],
    }
    print(json.dumps(compact, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
