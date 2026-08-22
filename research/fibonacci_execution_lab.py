#!/usr/bin/env python3
"""Preregistered Fibonacci confirmation/retest execution tournament.

Research only. This module models underlying reference fills and has no broker,
credential, scheduler, option-pricing, or order-submission code.
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

from research.fibonacci_confluence_lab import (
    DATA_DIR,
    _conditions,
    _trade_outcome,
    load_market,
    metrics,
)
from strategies.fibonacci_structure import confirmed_zigzag_pivots


DEFAULT_OUTPUT = ROOT / "data" / "fibonacci_execution_lab.json"
GOLDEN = round((5 ** 0.5 - 1) / 2, 6)


@dataclass(frozen=True)
class Variant:
    name: str
    limit_ratio: float
    ttl_bars: int
    placebo: bool = False


VARIANTS = (
    Variant("exact_0618_ttl1", GOLDEN, 1),
    Variant("exact_0618_ttl3", GOLDEN, 3),
    Variant("exact_0618_ttl6", GOLDEN, 6),
    Variant("golden_zone_0650_ttl3", 0.65, 3),
    Variant("practitioner_0705_ttl3", 0.705, 3),
    Variant("deep_0786_ttl3", 0.786, 3),
    Variant("placebo_0550_ttl3", 0.55, 3, True),
)


@dataclass(frozen=True)
class Config:
    atr_length: int = 14
    zigzag_reversal_atr: float = 0.75
    minimum_impulse_atr: float = 2.0
    confirmation_ratio: float = GOLDEN
    confirmation_zone_half_width: float = 0.025
    stop_buffer_atr: float = 0.05
    maximum_impulse_age_bars: int = 48
    entry_start: str = "10:00"
    entry_end: str = "14:30"
    round_trip_cost_bps: float = 2.0
    minimum_reward_risk: float = 1.0
    minimum_target_to_cost: float = 3.0
    minimum_period_trades: int = 40


def _first_retest_fill(
    future: pd.DataFrame,
    *,
    direction: int,
    entry: float,
    stop: float,
    ttl_bars: int,
) -> int | None:
    """Return the first fill offset, or None after expiry/invalidation."""
    for offset, (_, bar) in enumerate(future.iloc[:ttl_bars].iterrows()):
        touched = float(bar["low"]) <= entry <= float(bar["high"])
        if touched:
            return offset
        invalidated = float(bar["close"]) <= stop if direction == 1 else float(bar["close"]) >= stop
        if invalidated:
            return None
    return None


def _impulses(session: pd.DataFrame, config: Config) -> list[dict[str, Any]]:
    pivots = confirmed_zigzag_pivots(
        session[["open", "high", "low", "close"]],
        atr_length=config.atr_length,
        reversal_atr=config.zigzag_reversal_atr,
    )
    result = []
    for start, end in zip(pivots, pivots[1:]):
        if start["kind"] == "low" and end["kind"] == "high":
            direction = 1
        elif start["kind"] == "high" and end["kind"] == "low":
            direction = -1
        else:
            continue
        result.append({"start": start, "end": end, "direction": direction})
    return result


def session_event(session: pd.DataFrame, variant: Variant, config: Config) -> dict[str, Any] | None:
    impulses = _impulses(session, config)
    attempted: set[tuple[int, int]] = set()
    start_time = pd.Timestamp(config.entry_start).time()
    end_time = pd.Timestamp(config.entry_end).time()
    for position in range(1, len(session) - 1):
        timestamp = session.index[position]
        if not start_time <= timestamp.time() <= end_time:
            continue
        available = [
            impulse
            for impulse in impulses
            if impulse["end"]["confirmed_position"] <= position
            and position - impulse["end"]["position"] <= config.maximum_impulse_age_bars
        ]
        if not available:
            continue
        impulse = available[-1]
        impulse_key = (int(impulse["start"]["position"]), int(impulse["end"]["position"]))
        if impulse_key in attempted:
            continue
        start_price = float(impulse["start"]["price"])
        end_price = float(impulse["end"]["price"])
        size = abs(end_price - start_price)
        direction = int(impulse["direction"])
        bar = session.iloc[position]
        previous = session.iloc[position - 1]
        atr = float(bar["atr"])
        if not np.isfinite(atr) or atr <= 0 or size / atr < config.minimum_impulse_atr:
            continue

        confirmation_level = end_price - direction * size * config.confirmation_ratio
        price_a = end_price - direction * size * (
            config.confirmation_ratio - config.confirmation_zone_half_width
        )
        price_b = end_price - direction * size * (
            config.confirmation_ratio + config.confirmation_zone_half_width
        )
        zone_low, zone_high = min(price_a, price_b), max(price_a, price_b)
        touched = float(bar["low"]) <= zone_high and float(bar["high"]) >= zone_low
        if not touched:
            continue
        flags = _conditions(
            bar,
            previous,
            direction=direction,
            level=confirmation_level,
            relative_volume_minimum=1.2,
        )
        if not flags["fib_rejection_trend"]:
            continue
        attempted.add(impulse_key)

        entry = end_price - direction * size * variant.limit_ratio
        confirmation_close = float(bar["close"])
        rests_behind_confirmation = (
            confirmation_close >= entry if direction == 1 else confirmation_close <= entry
        )
        if not rests_behind_confirmation:
            continue
        stop = start_price - direction * config.stop_buffer_atr * atr
        target = end_price
        risk = abs(entry - stop)
        reward = abs(target - entry)
        cost = entry * config.round_trip_cost_bps / 10_000.0
        valid_geometry = (
            stop < entry < target if direction == 1 else target < entry < stop
        )
        if (
            not valid_geometry
            or risk <= 0
            or reward / risk < config.minimum_reward_risk
            or cost <= 0
            or reward / cost < config.minimum_target_to_cost
        ):
            continue

        future = session.iloc[position + 1 :]
        fill_offset = _first_retest_fill(
            future,
            direction=direction,
            entry=entry,
            stop=stop,
            ttl_bars=variant.ttl_bars,
        )
        if fill_offset is None:
            continue
        fill_position = position + 1 + fill_offset
        outcome = _trade_outcome(
            session.iloc[fill_position:],
            direction=direction,
            entry=entry,
            stop=stop,
            target=target,
            cost_bps=config.round_trip_cost_bps,
        )
        if outcome is None:
            continue
        return {
            "date": str(timestamp.date()),
            "confirmation_timestamp": timestamp.isoformat(),
            "fill_timestamp": session.index[fill_position].isoformat(),
            "variant": variant.name,
            "limit_ratio": variant.limit_ratio,
            "ttl_bars": variant.ttl_bars,
            "placebo": variant.placebo,
            "direction": "long" if direction == 1 else "short",
            "entry": entry,
            "stop": stop,
            "target": target,
            "wait_bars": fill_offset + 1,
            "impulse_atr": size / atr,
            "reward_risk": reward / risk,
            **outcome,
        }
    return None


def collect(frame: pd.DataFrame, variant: Variant, config: Config) -> list[dict[str, Any]]:
    rows = []
    for _, session in frame.groupby(frame.index.date, sort=True):
        event = session_event(session, variant, config)
        if event is not None:
            rows.append(event)
    return rows


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
            "median_wait_bars": float(np.median([row["wait_bars"] for row in subset])) if subset else None,
        }
    return result


def _selection_checks(summary: dict[str, Any], config: Config) -> dict[str, bool]:
    checks = {}
    for period in ("development", "selection"):
        row = summary[period]["base_cost"]
        checks[f"{period}_minimum_trades"] = row["trades"] >= config.minimum_period_trades
        checks[f"{period}_positive_expectancy"] = (row.get("expectancy_r") or 0) > 0
        checks[f"{period}_profit_factor_gte_1_10"] = (row.get("profit_factor") or 0) >= 1.10
    return checks


def build_report(config: Config = Config()) -> dict[str, Any]:
    frames = {symbol: load_market(symbol) for symbol in ("SPY", "QQQ", "IWM")}
    results: dict[str, Any] = {}
    rows_by_symbol: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for symbol, frame in frames.items():
        rows_by_symbol[symbol] = {}
        results[symbol] = {}
        for variant in VARIANTS:
            rows = collect(frame, variant, config)
            rows_by_symbol[symbol][variant.name] = rows
            results[symbol][variant.name] = summarize(rows)

    selection = {}
    selectable = []
    for variant in VARIANTS:
        summary = results["SPY"][variant.name]
        checks = _selection_checks(summary, config)
        passed = all(checks.values())
        selection[variant.name] = {"checks": checks, "passed": passed}
        if passed:
            selectable.append(variant.name)
    selected = max(
        selectable,
        key=lambda name: results["SPY"][name]["selection"]["base_cost"]["expectancy_r"],
        default=None,
    )

    promotion = {"passed": False, "checks": {}, "selected_variant": selected}
    if selected is not None:
        spy = results["SPY"][selected]["final"]
        qqq = results["QQQ"][selected]["final"]["base_cost"]
        iwm = results["IWM"][selected]["final"]["base_cost"]
        checks = {
            "minimum_final_spy_trades": spy["base_cost"]["trades"] >= config.minimum_period_trades,
            "positive_final_spy_expectancy": (spy["base_cost"].get("expectancy_r") or 0) > 0,
            "final_spy_profit_factor_gte_1_10": (spy["base_cost"].get("profit_factor") or 0) >= 1.10,
            "positive_final_spy_double_cost": (spy["double_cost"].get("expectancy_r") or 0) > 0,
            "positive_final_qqq_expectancy": (qqq.get("expectancy_r") or 0) > 0,
            "positive_final_iwm_expectancy": (iwm.get("expectancy_r") or 0) > 0,
        }
        promotion = {"passed": all(checks.values()), "checks": checks, "selected_variant": selected}

    hashes = {
        symbol: hashlib.sha256((DATA_DIR / f"{symbol.lower()}_5m.parquet").read_bytes()).hexdigest()
        for symbol in frames
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "research_only_no_execution_authority",
        "method": "causal_fibonacci_confirmation_then_no_chase_retest_limit_tournament",
        "preregistration": "research/preregistrations/fibonacci_execution_v4.md",
        "config": asdict(config),
        "variants": [asdict(variant) for variant in VARIANTS],
        "input_sha256": hashes,
        "date_ranges": {symbol: [str(frame.index.min()), str(frame.index.max())] for symbol, frame in frames.items()},
        "results": results,
        "selection_gates": selection,
        "selected_without_final_period": selected,
        "promotion_gate": promotion,
        "same_bar_ambiguity": "stop_first",
        "fill_model": "underlying_limit_touch_after_confirmation_with_ttl_no_market_conversion",
        "execution_enabled": False,
        "can_submit_orders": False,
        "can_block_production_entry": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    compact = {
        "SPY": report["results"]["SPY"],
        "external_final": {
            symbol: {
                name: result["final"]["base_cost"]
                for name, result in report["results"][symbol].items()
            }
            for symbol in ("QQQ", "IWM")
        },
        "selection_gates": report["selection_gates"],
        "selected_without_final_period": report["selected_without_final_period"],
        "promotion_gate": report["promotion_gate"],
    }
    print(json.dumps(compact, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
