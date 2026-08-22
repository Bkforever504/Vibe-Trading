#!/usr/bin/env python3
"""Preregistered paid-indicator methodology proxy lab.

Research only. This module has no broker, scheduler, or order-routing imports.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.indicator_recipe_lab import (
    MES_SPEC,
    SPY_SPEC,
    _cost_r,
    metrics,
    partition,
    promotion_gate,
    resample_real_bars,
    simulate_exit,
    stop_is_valid,
)
from research.initial_balance_edge_lab import (
    MES_CSV,
    SPY_PARQUET,
    MarketSpec,
    complete_sessions,
    load_csv,
    load_parquet,
)

OUTPUT_PATH = ROOT / "data" / "commercial_indicator_proxy_results.json"
PREREG_PATH = ROOT / "research" / "COMMERCIAL_INDICATOR_PROXY_PREREGISTRATION_2026-07-25.md"

FAMILIES = (
    "adaptive_trend_pullback",
    "oscillator_money_flow",
    "liquidity_structure_reclaim",
    "multi_oscillator_consensus",
    "velocity_ema_ribbon",
    "squeeze_release",
)


@dataclass(frozen=True)
class ProxyConfig:
    entry_start: str = "10:00"
    entry_end: str = "13:30"
    stop_atr: float = 1.25
    reward_risk: float = 1.75
    minimum_risk_ticks: int = 2
    relative_volume_window: int = 20
    liquidity_lookback: int = 20
    cost_stress_multiple: float = 2.0


CONFIG = ProxyConfig()


def _ema(values: pd.Series, length: int) -> pd.Series:
    return values.ewm(span=length, adjust=False, min_periods=length).mean()


def _true_range(frame: pd.DataFrame) -> pd.Series:
    prior_close = frame["close"].shift(1)
    return pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prior_close).abs(),
            (frame["low"] - prior_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _atr(frame: pd.DataFrame, length: int) -> pd.Series:
    return _true_range(frame).ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    relative = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + relative))


def _mfi(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3
    flow = typical * frame["volume"]
    direction = typical.diff()
    positive = flow.where(direction > 0, 0.0).rolling(length, min_periods=length).sum()
    negative = flow.where(direction < 0, 0.0).rolling(length, min_periods=length).sum()
    ratio = positive / negative.replace(0, np.nan)
    return 100 - (100 / (1 + ratio))


def _kama(close: pd.Series, efficiency_length: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    change = close.diff(efficiency_length).abs()
    volatility = close.diff().abs().rolling(efficiency_length).sum()
    efficiency = (change / volatility.replace(0, np.nan)).fillna(0.0)
    fast_alpha = 2.0 / (fast + 1)
    slow_alpha = 2.0 / (slow + 1)
    smoothing = (efficiency * (fast_alpha - slow_alpha) + slow_alpha) ** 2
    output = pd.Series(np.nan, index=close.index, dtype=float)
    if close.empty:
        return output
    output.iloc[0] = float(close.iloc[0])
    for position in range(1, len(close)):
        prior = float(output.iloc[position - 1])
        output.iloc[position] = prior + float(smoothing.iloc[position]) * (
            float(close.iloc[position]) - prior
        )
    output.iloc[:efficiency_length] = np.nan
    return output


def _supertrend_direction(
    frame: pd.DataFrame, length: int = 10, multiplier: float = 3.0
) -> pd.Series:
    atr = _atr(frame, length)
    midpoint = (frame["high"] + frame["low"]) / 2
    upper = midpoint + multiplier * atr
    lower = midpoint - multiplier * atr
    final_upper = upper.copy()
    final_lower = lower.copy()
    direction = pd.Series(0, index=frame.index, dtype=int)
    for position in range(1, len(frame)):
        if not np.isfinite(atr.iloc[position]):
            continue
        prior_close = float(frame["close"].iloc[position - 1])
        if prior_close <= float(final_upper.iloc[position - 1]):
            final_upper.iloc[position] = min(
                float(upper.iloc[position]), float(final_upper.iloc[position - 1])
            )
        if prior_close >= float(final_lower.iloc[position - 1]):
            final_lower.iloc[position] = max(
                float(lower.iloc[position]), float(final_lower.iloc[position - 1])
            )
        prior_direction = int(direction.iloc[position - 1])
        close = float(frame["close"].iloc[position])
        if close > float(final_upper.iloc[position - 1]):
            direction.iloc[position] = 1
        elif close < float(final_lower.iloc[position - 1]):
            direction.iloc[position] = -1
        else:
            direction.iloc[position] = prior_direction
    return direction


def _wavetrend(frame: pd.DataFrame, channel: int = 10, average: int = 21) -> tuple[pd.Series, pd.Series]:
    source = (frame["high"] + frame["low"] + frame["close"]) / 3
    esa = _ema(source, channel)
    deviation = _ema((source - esa).abs(), channel)
    composite = (source - esa) / (0.015 * deviation.replace(0, np.nan))
    wt1 = _ema(composite, average)
    wt2 = wt1.rolling(4, min_periods=4).mean()
    return wt1, wt2


def _stochastic(frame: pd.DataFrame, length: int = 14) -> tuple[pd.Series, pd.Series]:
    low = frame["low"].rolling(length, min_periods=length).min()
    high = frame["high"].rolling(length, min_periods=length).max()
    k = 100 * (frame["close"] - low) / (high - low).replace(0, np.nan)
    return k, k.rolling(3, min_periods=3).mean()


def _adx(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    up = frame["high"].diff()
    down = -frame["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr = _atr(frame, length)
    plus_di = 100 * plus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


def five_minute_frame(frame: pd.DataFrame) -> pd.DataFrame:
    sessions = [
        resample_real_bars(bars, 5)
        for _, bars in frame.groupby(frame.index.date, sort=True)
    ]
    return pd.concat(sessions) if sessions else frame.iloc[:0].copy()


def indicator_table(five: pd.DataFrame) -> pd.DataFrame:
    table = five.copy()
    close = table["close"]
    for length in (13, 48, 50, 200):
        table[f"ema{length}"] = _ema(close, length)
    table["kama"] = _kama(close)
    table["supertrend"] = _supertrend_direction(table)
    table["atr14"] = _atr(table, 14)
    table["atr_median50"] = table["atr14"].rolling(50, min_periods=50).median()
    prior_volume_mean = table["volume"].shift(1).rolling(
        CONFIG.relative_volume_window,
        min_periods=CONFIG.relative_volume_window,
    ).mean()
    table["relative_volume"] = table["volume"] / prior_volume_mean.replace(0, np.nan)
    table["rsi"] = _rsi(close)
    table["mfi"] = _mfi(table)
    table["wt1"], table["wt2"] = _wavetrend(table)
    table["stoch_k"], table["stoch_d"] = _stochastic(table)
    macd = _ema(close, 12) - _ema(close, 26)
    table["macd_histogram"] = macd - _ema(macd, 9)
    table["adx"] = _adx(table)

    dates = pd.Series(table.index.date, index=table.index)
    typical = (table["high"] + table["low"] + table["close"]) / 3
    cumulative_pv = (typical * table["volume"]).groupby(dates).cumsum()
    cumulative_volume = table["volume"].groupby(dates).cumsum().replace(0, np.nan)
    table["vwap"] = cumulative_pv / cumulative_volume

    table["prior20_low"] = table["low"].shift(1).rolling(
        CONFIG.liquidity_lookback,
        min_periods=CONFIG.liquidity_lookback,
    ).min()
    table["prior20_high"] = table["high"].shift(1).rolling(
        CONFIG.liquidity_lookback,
        min_periods=CONFIG.liquidity_lookback,
    ).max()
    candle_range = (table["high"] - table["low"]).replace(0, np.nan)
    table["body_fraction"] = (table["close"] - table["open"]).abs() / candle_range

    center = close.rolling(20, min_periods=20).mean()
    deviation = close.rolling(20, min_periods=20).std(ddof=0)
    bb_upper, bb_lower = center + 2 * deviation, center - 2 * deviation
    range_average = _true_range(table).ewm(
        alpha=1 / 20, adjust=False, min_periods=20
    ).mean()
    kc_upper, kc_lower = center + 1.5 * range_average, center - 1.5 * range_average
    table["squeeze"] = (bb_upper < kc_upper) & (bb_lower > kc_lower)
    table["squeeze_momentum"] = close - center
    return table


def family_direction(table: pd.DataFrame, position: int, family: str) -> str | None:
    row = table.iloc[position]
    prior = table.iloc[position - 1]
    finite_fields = ("close", "atr14", "ema13", "ema50", "relative_volume")
    if not all(np.isfinite(row[field]) for field in finite_fields):
        return None

    if family == "adaptive_trend_pullback":
        long = (
            row["supertrend"] == 1
            and row["close"] > row["kama"]
            and prior["close"] <= prior["ema13"]
            and row["close"] > row["ema13"]
            and row["relative_volume"] >= 1.0
        )
        short = (
            row["supertrend"] == -1
            and row["close"] < row["kama"]
            and prior["close"] >= prior["ema13"]
            and row["close"] < row["ema13"]
            and row["relative_volume"] >= 1.0
        )
    elif family == "oscillator_money_flow":
        long = (
            prior["wt1"] <= prior["wt2"]
            and row["wt1"] > row["wt2"]
            and min(prior["wt1"], prior["wt2"]) < -40
            and row["mfi"] > prior["mfi"]
            and row["close"] > row["vwap"]
            and row["close"] > row["ema50"]
        )
        short = (
            prior["wt1"] >= prior["wt2"]
            and row["wt1"] < row["wt2"]
            and max(prior["wt1"], prior["wt2"]) > 40
            and row["mfi"] < prior["mfi"]
            and row["close"] < row["vwap"]
            and row["close"] < row["ema50"]
        )
    elif family == "liquidity_structure_reclaim":
        long = (
            row["low"] < row["prior20_low"]
            and row["close"] > row["prior20_low"]
            and row["close"] > row["open"]
            and row["body_fraction"] >= 0.60
            and row["relative_volume"] >= 1.25
        )
        short = (
            row["high"] > row["prior20_high"]
            and row["close"] < row["prior20_high"]
            and row["close"] < row["open"]
            and row["body_fraction"] >= 0.60
            and row["relative_volume"] >= 1.25
        )
    elif family == "multi_oscillator_consensus":
        long_confirmations = sum(
            (
                row["macd_histogram"] > 0,
                row["stoch_k"] > row["stoch_d"],
                row["adx"] >= 20,
                row["close"] > row["ema50"],
            )
        )
        short_confirmations = sum(
            (
                row["macd_histogram"] < 0,
                row["stoch_k"] < row["stoch_d"],
                row["adx"] >= 20,
                row["close"] < row["ema50"],
            )
        )
        long = prior["rsi"] <= 50 < row["rsi"] and long_confirmations >= 3
        short = prior["rsi"] >= 50 > row["rsi"] and short_confirmations >= 3
    elif family == "velocity_ema_ribbon":
        long = (
            row["ema13"] > row["ema48"] > row["ema200"]
            and row["ema13"] > prior["ema13"]
            and prior["close"] <= prior["ema13"]
            and row["low"] <= row["ema13"]
            and row["close"] > row["ema13"]
            and row["atr14"] > row["atr_median50"]
        )
        short = (
            row["ema13"] < row["ema48"] < row["ema200"]
            and row["ema13"] < prior["ema13"]
            and prior["close"] >= prior["ema13"]
            and row["high"] >= row["ema13"]
            and row["close"] < row["ema13"]
            and row["atr14"] > row["atr_median50"]
        )
    elif family == "squeeze_release":
        long = (
            bool(prior["squeeze"])
            and not bool(row["squeeze"])
            and row["squeeze_momentum"] > 0
            and row["close"] > row["ema50"]
            and row["relative_volume"] >= 1.0
        )
        short = (
            bool(prior["squeeze"])
            and not bool(row["squeeze"])
            and row["squeeze_momentum"] < 0
            and row["close"] < row["ema50"]
            and row["relative_volume"] >= 1.0
        )
    else:
        raise ValueError(f"unknown family: {family}")
    if bool(long) == bool(short):
        return None
    return "long" if long else "short"


def replay(
    frame: pd.DataFrame,
    spec: MarketSpec,
    config: ProxyConfig = CONFIG,
) -> dict[str, list[dict[str, Any]]]:
    five = indicator_table(five_minute_frame(frame))
    output = {family: [] for family in FAMILIES}
    start = time.fromisoformat(config.entry_start)
    end = time.fromisoformat(config.entry_end)
    for day, session in five.groupby(five.index.date, sort=True):
        positions = five.index.get_indexer(session.index)
        for family in FAMILIES:
            for global_position in positions:
                timestamp = five.index[global_position]
                if global_position < 1 or not (start <= timestamp.time() <= end):
                    continue
                direction = family_direction(five, global_position, family)
                if direction is None or global_position + 1 >= len(five):
                    continue
                entry_at = five.index[global_position + 1]
                if entry_at.date() != day:
                    continue
                execution = five.loc[entry_at:].loc[
                    lambda rows: pd.Series(rows.index.date == day, index=rows.index)
                ]
                if execution.empty:
                    continue
                entry = float(execution.iloc[0]["open"])
                atr = float(five.iloc[global_position]["atr14"])
                risk = config.stop_atr * atr
                if not np.isfinite(risk) or risk < config.minimum_risk_ticks * spec.tick_size:
                    continue
                stop = entry - risk if direction == "long" else entry + risk
                if not stop_is_valid(direction, entry, stop):
                    continue
                target = (
                    entry + config.reward_risk * risk
                    if direction == "long"
                    else entry - config.reward_risk * risk
                )
                outcome = simulate_exit(
                    execution,
                    direction=direction,
                    entry=entry,
                    stop=stop,
                    target=target,
                    cost_r=_cost_r(spec, entry, risk),
                )
                output[family].append(
                    {
                        "date": str(day),
                        "signal_at": str(timestamp),
                        "entry_at": str(entry_at),
                        "direction": direction,
                        "entry": round(entry, 6),
                        "stop": round(stop, 6),
                        "target": round(target, 6),
                        "atr": round(atr, 6),
                        **outcome,
                    }
                )
                break
    return output


def evaluate_market(frame: pd.DataFrame, spec: MarketSpec) -> dict[str, Any]:
    complete, coverage = complete_sessions(frame)
    trades = replay(complete, spec)
    families: dict[str, Any] = {}
    for family, rows in trades.items():
        split_rows = partition(rows)
        split_metrics = {name: metrics(part) for name, part in split_rows.items()}
        families[family] = {
            "aggregate": metrics(rows),
            **split_metrics,
            "promotion_gate": promotion_gate(split_metrics),
        }
    return {
        "coverage": coverage,
        "first_session": str(complete.index.min().date()) if not complete.empty else None,
        "last_session": str(complete.index.max().date()) if not complete.empty else None,
        "families": families,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(mes: pd.DataFrame, spy: pd.DataFrame) -> dict[str, Any]:
    markets = {
        "MES": evaluate_market(mes, MES_SPEC),
        "SPY": evaluate_market(spy, SPY_SPEC),
    }
    cross_market = {}
    for family in FAMILIES:
        market_passes = {
            market: markets[market]["families"][family]["promotion_gate"]["passed"]
            for market in markets
        }
        cross_market[family] = {
            "passed": all(market_passes.values()),
            "market_passes": market_passes,
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "protected_vendor_code_used": False,
        "config": asdict(CONFIG),
        "preregistration": str(PREREG_PATH.relative_to(ROOT)),
        "preregistration_sha256": _sha256(PREREG_PATH),
        "markets": markets,
        "cross_market": cross_market,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mes", type=Path, default=MES_CSV)
    parser.add_argument("--spy", type=Path, default=SPY_PARQUET)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    result = evaluate(load_csv(args.mes), load_parquet(args.spy))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["cross_market"], indent=2))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
