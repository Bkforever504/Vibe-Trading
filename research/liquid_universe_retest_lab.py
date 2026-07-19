#!/usr/bin/env python3
"""Test objective opening-range retests across liquid option underlyings.

This lab translates recurring public-trader claims into rules that can be
falsified on five-minute underlying bars. It does not infer option P&L and it
cannot place orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.liquid_universe_orb_replication import load_bars, metrics, moving_block_bootstrap

NY = ZoneInfo("America/New_York")
OUTPUT = Path.home() / ".vibe-trading" / "reports" / "liquid-universe-retest-lab.json"
SYMBOLS = ("QQQ", "TQQQ", "SPY", "IWM")
RTH_START = "09:30"
RTH_END = "15:55"
DEVELOPMENT_END = "2023-12-31"
TEST_START = "2025-01-01"


@dataclass(frozen=True)
class RetestConfig:
    name: str
    opening_minutes: int
    require_ema_fan: bool = False
    require_rvol: bool = False
    require_prior_day_level: bool = False
    target_r: float = 2.0
    max_retest_bars: int = 12
    latest_entry: str = "11:30"
    tolerance_bps: float = 5.0
    min_stop_bps: float = 5.0
    max_stop_bps: float = 75.0


CONFIGS = tuple(
    config
    for minutes in (15, 30)
    for config in (
        RetestConfig(f"or{minutes}_retest_2r", minutes),
        RetestConfig(f"or{minutes}_retest_ema_2r", minutes, require_ema_fan=True),
        RetestConfig(
            f"or{minutes}_retest_ema_rvol_2r", minutes, require_ema_fan=True, require_rvol=True
        ),
        RetestConfig(
            f"or{minutes}_retest_ema_level_rvol_2r",
            minutes,
            require_ema_fan=True,
            require_rvol=True,
            require_prior_day_level=True,
        ),
    )
)


def prepare(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[Any, dict[str, float]]]:
    """Build only backward-looking EMA, volume, and prior-session context."""
    rth = frame.between_time(RTH_START, RTH_END).copy().sort_index()
    for span in (13, 48, 200):
        rth[f"ema{span}"] = rth["close"].ewm(span=span, adjust=False).mean()

    grouped = rth.groupby(rth.index.date)
    daily = grouped.agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    daily[["prior_high", "prior_low", "prior_close"]] = daily[["high", "low", "close"]].shift(1)

    contexts: dict[Any, dict[str, float]] = {}
    for opening_minutes in (15, 30):
        opening_bars = opening_minutes // 5
        opening_volume = grouped["volume"].apply(lambda values: float(values.iloc[:opening_bars].sum()))
        expected = opening_volume.rolling(20).mean().shift(1)
        daily[f"opening_volume_{opening_minutes}"] = opening_volume
        daily[f"expected_opening_volume_{opening_minutes}"] = expected
    for day, row in daily.iterrows():
        contexts[day] = {
            key: float(value) if pd.notna(value) else float("nan") for key, value in row.items()
        }
    return rth, contexts


def _ema_aligned(row: pd.Series, direction: str) -> bool:
    if direction == "long":
        return float(row["close"]) > float(row["ema13"]) > float(row["ema48"]) > float(row["ema200"])
    return float(row["close"]) < float(row["ema13"]) < float(row["ema48"]) < float(row["ema200"])


def _level_for_direction(
    opening_high: float,
    opening_low: float,
    context: dict[str, float],
    direction: str,
    require_prior_day_level: bool,
) -> float | None:
    if not require_prior_day_level:
        return opening_high if direction == "long" else opening_low
    prior = context.get("prior_high" if direction == "long" else "prior_low", float("nan"))
    if not np.isfinite(prior):
        return None
    return max(opening_high, prior) if direction == "long" else min(opening_low, prior)


def replay(
    frame: pd.DataFrame,
    config: RetestConfig,
    cost_bps_per_side: float = 1.0,
    prepared: tuple[pd.DataFrame, dict[Any, dict[str, float]]] | None = None,
) -> list[dict[str, Any]]:
    rth, contexts = prepared if prepared is not None else prepare(frame)
    trades: list[dict[str, Any]] = []
    opening_bars = config.opening_minutes // 5

    for day, bars in rth.groupby(rth.index.date):
        bars = bars.sort_index()
        if len(bars) <= opening_bars + 2 or bars.index[0].strftime("%H:%M") != RTH_START:
            continue
        context = contexts.get(day, {})
        expected_volume = context.get(f"expected_opening_volume_{config.opening_minutes}", float("nan"))
        actual_volume = context.get(f"opening_volume_{config.opening_minutes}", float("nan"))
        if not np.isfinite(expected_volume) or expected_volume <= 0:
            continue
        rvol = actual_volume / expected_volume
        if config.require_rvol and rvol < 1.0:
            continue

        opening = bars.iloc[:opening_bars]
        opening_high = float(opening["high"].max())
        opening_low = float(opening["low"].min())
        candidates = bars.iloc[opening_bars:]
        trade: dict[str, Any] | None = None

        for direction in ("long", "short"):
            level = _level_for_direction(
                opening_high, opening_low, context, direction, config.require_prior_day_level
            )
            if level is None:
                continue
            if direction == "long":
                breakout_mask = candidates["close"] > level
            else:
                breakout_mask = candidates["close"] < level
            if not breakout_mask.any():
                continue
            breakout_position = int(np.flatnonzero(breakout_mask.to_numpy())[0])
            breakout = candidates.iloc[breakout_position]
            after = candidates.iloc[breakout_position + 1 : breakout_position + 1 + config.max_retest_bars]
            tolerance = level * config.tolerance_bps / 10_000.0

            for retest_position, (_, retest) in enumerate(after.iterrows(), start=breakout_position + 1):
                if direction == "long":
                    accepted = float(retest["low"]) <= level + tolerance and float(retest["close"]) > level
                else:
                    accepted = float(retest["high"]) >= level - tolerance and float(retest["close"]) < level
                if not accepted or (config.require_ema_fan and not _ema_aligned(retest, direction)):
                    continue
                entry_position = opening_bars + retest_position + 1
                if entry_position >= len(bars):
                    break
                entry_bar = bars.iloc[entry_position]
                if entry_bar.name.strftime("%H:%M") > config.latest_entry:
                    break
                entry = float(entry_bar["open"])
                stop = float(retest["low"] if direction == "long" else retest["high"])
                risk = entry - stop if direction == "long" else stop - entry
                risk_bps = risk / entry * 10_000.0
                if risk <= 0 or risk_bps < config.min_stop_bps or risk_bps > config.max_stop_bps:
                    continue
                target = entry + config.target_r * risk if direction == "long" else entry - config.target_r * risk
                remaining = bars.iloc[entry_position:]
                exit_price, outcome = float(remaining.iloc[-1]["close"]), "eod"
                for _, candle in remaining.iterrows():
                    stop_hit = float(candle["low"]) <= stop if direction == "long" else float(candle["high"]) >= stop
                    target_hit = float(candle["high"]) >= target if direction == "long" else float(candle["low"]) <= target
                    if stop_hit:
                        exit_price, outcome = stop, "stop"
                        break
                    if target_hit:
                        exit_price, outcome = target, "target"
                        break
                gross = exit_price - entry if direction == "long" else entry - exit_price
                cost = 2.0 * entry * cost_bps_per_side / 10_000.0
                candidate_trade = {
                    "date": str(day),
                    "direction": direction,
                    "entry_time": entry_bar.name.isoformat(),
                    "level": round(level, 4),
                    "entry": round(entry, 4),
                    "stop": round(stop, 4),
                    "target": round(target, 4),
                    "outcome": outcome,
                    "rvol": round(float(rvol), 4),
                    "risk_bps": round(float(risk_bps), 3),
                    "net_return_bps": round(float((gross - cost) / entry * 10_000.0), 3),
                    "net_r": round(float((gross - cost) / risk), 5),
                }
                if trade is None or candidate_trade["entry_time"] < trade["entry_time"]:
                    trade = candidate_trade
                break
        if trade is not None:
            trades.append(trade)
    return trades


def evaluate(symbol: str, frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    prepared = prepare(frame)
    for config in CONFIGS:
        trades = replay(frame, config, 1.0, prepared)
        stressed = replay(frame, config, 2.0, prepared)
        development = [trade for trade in trades if trade["date"] <= DEVELOPMENT_END]
        test = [trade for trade in trades if trade["date"] >= TEST_START]
        stressed_test = [trade for trade in stressed if trade["date"] >= TEST_START]
        years = sorted({trade["date"][:4] for trade in trades})
        rows.append(
            {
                "symbol": symbol,
                "config": config.name,
                "rules": asdict(config),
                "development": metrics(development),
                "test_2025_plus": metrics(test),
                "test_long": metrics([trade for trade in test if trade["direction"] == "long"]),
                "test_short": metrics([trade for trade in test if trade["direction"] == "short"]),
                "double_cost_test": metrics(stressed_test),
                "test_block_bootstrap": moving_block_bootstrap([float(trade["net_r"]) for trade in test]),
                "yearly": {year: metrics([trade for trade in trades if trade["date"].startswith(year)]) for year in years},
                "execution_enabled": False,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(SYMBOLS))
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for symbol in [item.strip().upper() for item in args.symbols.split(",") if item.strip()]:
        try:
            rows.extend(evaluate(symbol, load_bars(symbol, args.start, args.end, args.refresh)))
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)[:240]})
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(NY).isoformat(),
        "mode": "research_only",
        "execution_enabled": False,
        "options_pnl_tested": False,
        "development_end": DEVELOPMENT_END,
        "test_start": TEST_START,
        "rows": rows,
        "errors": errors,
        "warnings": [
            "The 2025+ test is post-specification for this script but not pristine market data; other project research has inspected parts of this period.",
            "Underlying returns do not establish option profitability because spread, IV, theta, and strike selection are not modeled.",
            "Alpaca IEX bars are not consolidated SIP data.",
            "Same-bar stop and target ambiguity is resolved against the strategy by checking the stop first.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
