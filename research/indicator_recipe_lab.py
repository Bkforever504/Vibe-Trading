#!/usr/bin/env python3
"""Preregistered Failed 2, pivot, killzone, VWAP, HA, and HTF lab.

Research only. This module has no broker, scheduler, or order-routing imports.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.initial_balance_edge_lab import (
    MES_CSV,
    SPY_PARQUET,
    MarketSpec,
    complete_sessions,
    load_csv,
    load_parquet,
)

OUTPUT_PATH = ROOT / "data" / "indicator_recipe_results.json"

VARIANTS = (
    "failed2_raw",
    "failed2_killzone",
    "failed2_pivot",
    "failed2_pivot_killzone",
    "failed2_pivot_killzone_ha",
    "failed2_pivot_killzone_vwap",
    "full_recipe",
)

SPY_SPEC = MarketSpec(
    "SPY",
    tick_size=0.01,
    slippage_bps_per_side=1.0,
)
MES_SPEC = MarketSpec(
    "MES",
    tick_size=0.25,
    point_value=5.0,
    commission_round_trip=2.48,
    slippage_ticks_per_side=1,
)


@dataclass(frozen=True)
class RecipeConfig:
    reward_risk: float = 1.5
    pivot_tolerance_prior_range: float = 0.05
    max_risk_prior_range: float = 0.25
    minimum_risk_ticks: int = 2
    killzone_start: str = "09:35"
    killzone_end_exclusive: str = "11:00"
    cost_stress_multiple: float = 2.0


CONFIG = RecipeConfig()


def resample_real_bars(bars: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Aggregate real OHLCV without introducing synthetic prices."""
    rule = f"{minutes}min"
    output = bars.resample(rule, origin="start_day", offset="30min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })
    counts = bars["close"].resample(rule, origin="start_day", offset="30min").count()
    return output[counts == minutes].dropna()


def heikin_ashi_state(real_bars: pd.DataFrame) -> pd.DataFrame:
    """Return HA state values calculated from real bars.

    The caller must never use these values as entry, stop, target, or P&L
    prices.
    """
    if real_bars.empty:
        return real_bars.copy()
    ha_close = (
        real_bars["open"]
        + real_bars["high"]
        + real_bars["low"]
        + real_bars["close"]
    ) / 4.0
    ha_open = np.empty(len(real_bars), dtype=float)
    ha_open[0] = (float(real_bars.iloc[0]["open"]) + float(real_bars.iloc[0]["close"])) / 2.0
    for index in range(1, len(real_bars)):
        ha_open[index] = (ha_open[index - 1] + float(ha_close.iloc[index - 1])) / 2.0
    output = pd.DataFrame(index=real_bars.index)
    output["open"] = ha_open
    output["close"] = ha_close.astype(float)
    output["bullish"] = output["close"] > output["open"]
    output["bearish"] = output["close"] < output["open"]
    return output


def failed2_direction(base: pd.Series, attempt: pd.Series, confirmation: pd.Series) -> str | None:
    """Classify a strict Failed 2 using only three completed real bars."""
    attempted_up = float(attempt["high"]) > float(base["high"]) and float(attempt["low"]) >= float(base["low"])
    attempted_down = float(attempt["low"]) < float(base["low"]) and float(attempt["high"]) <= float(base["high"])
    bearish_failure = attempted_up and float(confirmation["close"]) < float(attempt["low"])
    bullish_failure = attempted_down and float(confirmation["close"]) > float(attempt["high"])
    if bearish_failure == bullish_failure:
        return None
    return "short" if bearish_failure else "long"


def traditional_levels(prior: pd.DataFrame) -> dict[str, float]:
    high = float(prior["high"].max())
    low = float(prior["low"].min())
    close = float(prior.iloc[-1]["close"])
    pivot = (high + low + close) / 3.0
    return {
        "pdh": high,
        "pdl": low,
        "pivot": pivot,
        "r1": 2.0 * pivot - low,
        "s1": 2.0 * pivot - high,
    }


def rejected_level(
    attempt: pd.Series,
    direction: str,
    levels: dict[str, float],
    tolerance: float,
) -> str | None:
    """Find a wick breach and close-back-through at a prior-session level."""
    candidates: list[tuple[float, str]] = []
    for name, level in levels.items():
        if direction == "short":
            excursion = float(attempt["high"]) - level
            rejected = float(attempt["high"]) >= level and float(attempt["close"]) < level
        else:
            excursion = level - float(attempt["low"])
            rejected = float(attempt["low"]) <= level and float(attempt["close"]) > level
        if rejected and 0 <= excursion <= tolerance:
            candidates.append((excursion, name))
    return min(candidates)[1] if candidates else None


def _trend_state(close: float, average: float, earlier_average: float) -> str:
    if not all(np.isfinite(value) for value in (close, average, earlier_average)):
        return "unavailable"
    if close > average and average > earlier_average:
        return "bullish"
    if close < average and average < earlier_average:
        return "bearish"
    return "mixed"


def build_htf_states(frame: pd.DataFrame) -> dict[str, pd.Series]:
    session_close = frame["close"].groupby(frame.index.normalize()).last().astype(float)
    daily_average = session_close.rolling(20, min_periods=20).mean()
    daily = pd.Series(
        [
            _trend_state(close, average, earlier)
            for close, average, earlier in zip(session_close, daily_average, daily_average.shift(5))
        ],
        index=session_close.index,
        dtype="object",
    )
    weekly_close = session_close.resample("W-FRI").last().dropna()
    weekly_average = weekly_close.rolling(20, min_periods=20).mean()
    weekly = pd.Series(
        [
            _trend_state(close, average, earlier)
            for close, average, earlier in zip(weekly_close, weekly_average, weekly_average.shift(5))
        ],
        index=weekly_close.index,
        dtype="object",
    )
    return {"daily": daily, "weekly": weekly}


def asof_htf(states: dict[str, pd.Series], session_date: date) -> dict[str, str]:
    stamp = pd.Timestamp(session_date)
    output: dict[str, str] = {}
    for frequency, series in states.items():
        eligible = series[series.index < stamp]
        output[frequency] = str(eligible.iloc[-1]) if not eligible.empty else "unavailable"
    return output


def htf_nonopposed(states: dict[str, str], direction: str) -> bool:
    opposite = "bearish" if direction == "long" else "bullish"
    return all(states.get(frequency, "unavailable") != opposite for frequency in ("daily", "weekly"))


def _killzone(timestamp: pd.Timestamp, config: RecipeConfig) -> bool:
    start_h, start_m = (int(value) for value in config.killzone_start.split(":"))
    end_h, end_m = (int(value) for value in config.killzone_end_exclusive.split(":"))
    return time(start_h, start_m) <= timestamp.time() < time(end_h, end_m)


def _ha_aligned(
    fifteen_minute_ha: pd.DataFrame,
    confirmation_start: pd.Timestamp,
    direction: str,
) -> bool:
    known_at = confirmation_start + pd.Timedelta(minutes=5)
    completed = fifteen_minute_ha[
        fifteen_minute_ha.index + pd.Timedelta(minutes=15) <= known_at
    ]
    if len(completed) < 2:
        return False
    column = "bullish" if direction == "long" else "bearish"
    return bool(completed[column].iloc[-2:].all())


def _session_vwap(five_minute: pd.DataFrame) -> pd.Series:
    typical = (five_minute["high"] + five_minute["low"] + five_minute["close"]) / 3.0
    cumulative_volume = five_minute["volume"].cumsum().replace(0, np.nan)
    return (typical * five_minute["volume"]).cumsum() / cumulative_volume


def _variant_allows(
    variant: str,
    *,
    killzone: bool,
    pivot: bool,
    ha: bool,
    vwap: bool,
    htf: bool,
) -> bool:
    requirements = {
        "failed2_raw": (),
        "failed2_killzone": ("killzone",),
        "failed2_pivot": ("pivot",),
        "failed2_pivot_killzone": ("pivot", "killzone"),
        "failed2_pivot_killzone_ha": ("pivot", "killzone", "ha"),
        "failed2_pivot_killzone_vwap": ("pivot", "killzone", "vwap"),
        "full_recipe": ("pivot", "killzone", "ha", "vwap", "htf"),
    }
    values = {"killzone": killzone, "pivot": pivot, "ha": ha, "vwap": vwap, "htf": htf}
    return all(values[name] for name in requirements[variant])


def _cost_r(spec: MarketSpec, entry: float, risk: float) -> float:
    if spec.point_value:
        price_cost = (
            2 * spec.slippage_ticks_per_side * spec.tick_size
            + spec.commission_round_trip / spec.point_value
        )
    else:
        price_cost = 2 * entry * spec.slippage_bps_per_side / 10_000.0
    return price_cost / risk


def stop_is_valid(direction: str, entry: float, stop: float) -> bool:
    return stop < entry if direction == "long" else stop > entry


def simulate_exit(
    path: pd.DataFrame,
    *,
    direction: str,
    entry: float,
    stop: float,
    target: float,
    cost_r: float,
) -> dict[str, Any]:
    side = 1 if direction == "long" else -1
    risk = abs(entry - stop)
    for timestamp, bar in path.iterrows():
        stop_hit = float(bar["low"]) <= stop if side > 0 else float(bar["high"]) >= stop
        target_hit = float(bar["high"]) >= target if side > 0 else float(bar["low"]) <= target
        if stop_hit:
            gross_r, outcome, exit_at = -1.0, "stop", timestamp
            break
        if target_hit:
            gross_r, outcome, exit_at = abs(target - entry) / risk, "target", timestamp
            break
    else:
        exit_at = path.index[-1]
        exit_price = float(path.iloc[-1]["close"])
        gross_r = (exit_price - entry) * side / risk
        outcome = "eod"
    return {
        "gross_r": round(float(gross_r), 6),
        "cost_r": round(float(cost_r), 6),
        "net_r": round(float(gross_r - cost_r), 6),
        "net_r_double_cost": round(float(gross_r - CONFIG.cost_stress_multiple * cost_r), 6),
        "outcome": outcome,
        "exit_at": str(exit_at),
    }


def session_candidates(
    bars: pd.DataFrame,
    prior: pd.DataFrame,
    htf_states: dict[str, str],
    spec: MarketSpec,
    config: RecipeConfig = CONFIG,
) -> list[dict[str, Any]]:
    five = resample_real_bars(bars, 5)
    fifteen = resample_real_bars(bars, 15)
    ha = heikin_ashi_state(fifteen)
    vwap = _session_vwap(five)
    levels = traditional_levels(prior)
    prior_range = levels["pdh"] - levels["pdl"]
    if len(five) < 4 or prior_range <= 0:
        return []
    candidates: list[dict[str, Any]] = []
    for position in range(2, len(five) - 1):
        base = five.iloc[position - 2]
        attempt = five.iloc[position - 1]
        confirmation = five.iloc[position]
        direction = failed2_direction(base, attempt, confirmation)
        if direction is None:
            continue
        confirmation_at = five.index[position]
        level = rejected_level(
            attempt,
            direction,
            levels,
            prior_range * config.pivot_tolerance_prior_range,
        )
        ha_ok = _ha_aligned(ha, confirmation_at, direction)
        vwap_value = float(vwap.iloc[position])
        vwap_ok = (
            float(confirmation["close"]) > vwap_value
            if direction == "long"
            else float(confirmation["close"]) < vwap_value
        )
        candidates.append({
            "position": position,
            "confirmation_at": confirmation_at,
            "direction": direction,
            "killzone": _killzone(confirmation_at, config),
            "pivot": level is not None,
            "pivot_name": level,
            "ha": ha_ok,
            "vwap": vwap_ok,
            "htf": htf_nonopposed(htf_states, direction),
            "attempt_high": float(attempt["high"]),
            "attempt_low": float(attempt["low"]),
            "confirmation_high": float(confirmation["high"]),
            "confirmation_low": float(confirmation["low"]),
            "prior_range": prior_range,
        })
    return candidates


def replay(
    frame: pd.DataFrame,
    spec: MarketSpec,
    config: RecipeConfig = CONFIG,
) -> dict[str, list[dict[str, Any]]]:
    output = {variant: [] for variant in VARIANTS}
    sessions = [(day, bars) for day, bars in frame.groupby(frame.index.date, sort=True)]
    htf_table = build_htf_states(frame)
    for session_index in range(1, len(sessions)):
        day, bars = sessions[session_index]
        _, prior = sessions[session_index - 1]
        states = asof_htf(htf_table, day)
        five = resample_real_bars(bars, 5)
        for candidate in session_candidates(bars, prior, states, spec, config):
            position = int(candidate["position"])
            execution = five.iloc[position + 1:]
            if execution.empty:
                continue
            direction = str(candidate["direction"])
            entry = float(execution.iloc[0]["open"])
            extreme = (
                min(candidate["attempt_low"], candidate["confirmation_low"])
                if direction == "long"
                else max(candidate["attempt_high"], candidate["confirmation_high"])
            )
            stop = extreme - spec.tick_size if direction == "long" else extreme + spec.tick_size
            if not stop_is_valid(direction, entry, stop):
                continue
            risk = abs(entry - stop)
            if risk < config.minimum_risk_ticks * spec.tick_size:
                continue
            if risk > config.max_risk_prior_range * float(candidate["prior_range"]):
                continue
            target = entry + config.reward_risk * risk if direction == "long" else entry - config.reward_risk * risk
            cost_r = _cost_r(spec, entry, risk)
            outcome = simulate_exit(
                execution,
                direction=direction,
                entry=entry,
                stop=stop,
                target=target,
                cost_r=cost_r,
            )
            row = {
                "date": str(day),
                "entry_at": str(execution.index[0]),
                "entry": round(entry, 6),
                "stop": round(stop, 6),
                "target": round(target, 6),
                "direction": direction,
                "pivot_name": candidate["pivot_name"],
                "contexts": {
                    name: bool(candidate[name])
                    for name in ("killzone", "pivot", "ha", "vwap", "htf")
                },
                "htf_states": states,
                **outcome,
            }
            for variant in VARIANTS:
                if output[variant] and output[variant][-1]["date"] == str(day):
                    continue
                if _variant_allows(
                    variant,
                    killzone=bool(candidate["killzone"]),
                    pivot=bool(candidate["pivot"]),
                    ha=bool(candidate["ha"]),
                    vwap=bool(candidate["vwap"]),
                    htf=bool(candidate["htf"]),
                ):
                    output[variant].append(row)
    return output


def _moving_block_ci(values: list[float], seed: int = 20260725) -> list[float | None]:
    if len(values) < 10:
        return [None, None]
    rng = np.random.default_rng(seed)
    data = np.asarray(values, dtype=float)
    block = min(5, len(data))
    starts = np.arange(0, len(data) - block + 1)
    blocks_needed = int(np.ceil(len(data) / block))
    chosen = rng.choice(starts, size=(2000, blocks_needed))
    indices = (chosen[:, :, None] + np.arange(block)).reshape(2000, -1)[:, :len(data)]
    low, high = np.percentile(data[indices].mean(axis=1), (2.5, 97.5))
    return [round(float(low), 4), round(float(high), 4)]


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(trade["net_r"]) for trade in trades]
    gross = [float(trade["gross_r"]) for trade in trades]
    double_cost = [float(trade["net_r_double_cost"]) for trade in trades]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    removal_count = max(1, math.ceil(len(values) * 0.01)) if values else 0
    trimmed = sorted(values)[:-removal_count] if removal_count and len(values) > removal_count else []
    return {
        "trades": len(values),
        "win_rate": round(len(wins) / len(values), 4) if values else None,
        "target_hit_rate": (
            round(sum(trade["outcome"] == "target" for trade in trades) / len(trades), 4)
            if trades else None
        ),
        "gross_expectancy_r": round(float(np.mean(gross)), 4) if gross else None,
        "average_cost_r": (
            round(float(np.mean([float(trade["cost_r"]) for trade in trades])), 4)
            if trades else None
        ),
        "expectancy_r": round(float(np.mean(values)), 4) if values else None,
        "double_cost_expectancy_r": round(float(np.mean(double_cost)), 4) if double_cost else None,
        "top_1pct_removed_expectancy_r": round(float(np.mean(trimmed)), 4) if trimmed else None,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 4) if losses else ("inf" if wins else None),
        "max_drawdown_r": round(drawdown, 4),
        "expectancy_95pct_moving_5_trade_block_ci": _moving_block_ci(values),
        "long_trades": sum(trade["direction"] == "long" for trade in trades),
        "short_trades": sum(trade["direction"] == "short" for trade in trades),
    }


def partition(trades: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "development_2022_2023": [
            trade for trade in trades if 2022 <= int(trade["date"][:4]) <= 2023
        ],
        "selection_2024": [trade for trade in trades if int(trade["date"][:4]) == 2024],
        "diagnostic_2025_plus": [trade for trade in trades if int(trade["date"][:4]) >= 2025],
    }


def promotion_gate(parts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    development = parts["development_2022_2023"]
    selection = parts["selection_2024"]
    diagnostic = parts["diagnostic_2025_plus"]
    checks = {
        "positive_all_windows": all(
            part["expectancy_r"] is not None and part["expectancy_r"] > 0
            for part in (development, selection, diagnostic)
        ),
        "selection_at_least_30": selection["trades"] >= 30,
        "diagnostic_at_least_30": diagnostic["trades"] >= 30,
        "diagnostic_pf_at_least_1_20": (
            diagnostic["profit_factor"] == "inf"
            or isinstance(diagnostic["profit_factor"], (int, float))
            and diagnostic["profit_factor"] >= 1.20
        ),
        "diagnostic_ci_lower_above_zero": (
            diagnostic["expectancy_95pct_moving_5_trade_block_ci"][0] is not None
            and diagnostic["expectancy_95pct_moving_5_trade_block_ci"][0] > 0
        ),
        "diagnostic_positive_double_cost": (
            diagnostic["double_cost_expectancy_r"] is not None
            and diagnostic["double_cost_expectancy_r"] > 0
        ),
        "diagnostic_positive_without_top_1pct": (
            diagnostic["top_1pct_removed_expectancy_r"] is not None
            and diagnostic["top_1pct_removed_expectancy_r"] > 0
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def evaluate_market(frame: pd.DataFrame, spec: MarketSpec) -> dict[str, Any]:
    complete, coverage = complete_sessions(frame)
    trades = replay(complete, spec)
    variants: dict[str, Any] = {}
    for variant, rows in trades.items():
        split_rows = partition(rows)
        split_metrics = {name: metrics(part) for name, part in split_rows.items()}
        variants[variant] = {
            "aggregate": metrics(rows),
            **split_metrics,
            "promotion_gate": promotion_gate(split_metrics),
        }
    return {
        "coverage": coverage,
        "first_session": str(complete.index.min().date()) if not complete.empty else None,
        "last_session": str(complete.index.max().date()) if not complete.empty else None,
        "variants": variants,
    }


def evaluate(mes: pd.DataFrame, spy: pd.DataFrame) -> dict[str, Any]:
    markets = {
        "MES": evaluate_market(mes, MES_SPEC),
        "SPY": evaluate_market(spy, SPY_SPEC),
    }
    cross_market = {
        variant: {
            "passed": all(markets[market]["variants"][variant]["promotion_gate"]["passed"] for market in markets),
            "market_passes": {
                market: markets[market]["variants"][variant]["promotion_gate"]["passed"]
                for market in markets
            },
        }
        for variant in VARIANTS
    }
    return {
        "schema_version": 1,
        "experiment": "INDICATOR-RECIPE-2026-07-25",
        "mode": "research_only_preregistered",
        "execution_enabled": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "config": asdict(CONFIG),
        "variants": list(VARIANTS),
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (MES_CSV, SPY_PARQUET)
        },
        "markets": markets,
        "cross_market_promotion": cross_market,
        "warnings": [
            "SPY uses IEX underlying bars, not SIP data or option premium paths.",
            "Heikin-Ashi is a signal-state filter only; all fills use real OHLC.",
            "The final period has been consumed by prior research and is diagnostic.",
            "No result can enable live or simulated trading.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mes-csv", type=Path, default=MES_CSV)
    parser.add_argument("--spy-parquet", type=Path, default=SPY_PARQUET)
    parser.add_argument("--out", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = evaluate(load_csv(args.mes_csv), load_parquet(args.spy_parquet))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.do_print:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
