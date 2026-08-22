#!/usr/bin/env python3
"""Source-matched single-candle Failed 2 replication.

Research only. No broker, scheduler, or order-routing imports.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.indicator_recipe_lab import (
    CONFIG,
    MES_SPEC,
    SPY_SPEC,
    _ha_aligned,
    _killzone,
    _session_vwap,
    asof_htf,
    build_htf_states,
    heikin_ashi_state,
    htf_nonopposed,
    metrics,
    partition,
    promotion_gate,
    resample_real_bars,
    simulate_exit,
    stop_is_valid,
    traditional_levels,
)
from research.initial_balance_edge_lab import (
    MES_CSV,
    SPY_PARQUET,
    MarketSpec,
    complete_sessions,
    load_csv,
    load_parquet,
)

OUTPUT_PATH = ROOT / "data" / "failed2_source_matched_results.json"
VARIANTS = (
    "level_failed2_all_day",
    "level_failed2_killzone",
    "level_failed2_killzone_ha",
    "level_failed2_killzone_vwap",
    "level_failed2_full",
)


def strict_level_failed2(
    candle: pd.Series,
    levels: dict[str, float],
    tolerance: float,
) -> tuple[str, str] | None:
    """Match the public indicator's wick, reclaim, and candle-color rule."""
    events: list[tuple[float, str, str]] = []
    for name, level in levels.items():
        upside_excursion = float(candle["high"]) - level
        downside_excursion = level - float(candle["low"])
        if (
            float(candle["high"]) > level
            and float(candle["close"]) < level
            and float(candle["close"]) < float(candle["open"])
            and 0 < upside_excursion <= tolerance
        ):
            events.append((upside_excursion, "short", name))
        if (
            float(candle["low"]) < level
            and float(candle["close"]) > level
            and float(candle["close"]) > float(candle["open"])
            and 0 < downside_excursion <= tolerance
        ):
            events.append((downside_excursion, "long", name))
    directions = {event[1] for event in events}
    if len(directions) != 1:
        return None
    _, direction, name = min(events)
    return direction, name


def _allows(
    variant: str,
    *,
    killzone: bool,
    ha: bool,
    vwap: bool,
    htf: bool,
) -> bool:
    requirements = {
        "level_failed2_all_day": (),
        "level_failed2_killzone": ("killzone",),
        "level_failed2_killzone_ha": ("killzone", "ha"),
        "level_failed2_killzone_vwap": ("killzone", "vwap"),
        "level_failed2_full": ("killzone", "ha", "vwap", "htf"),
    }
    values = {"killzone": killzone, "ha": ha, "vwap": vwap, "htf": htf}
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


def replay(frame: pd.DataFrame, spec: MarketSpec) -> dict[str, list[dict[str, Any]]]:
    output = {variant: [] for variant in VARIANTS}
    sessions = [(day, bars) for day, bars in frame.groupby(frame.index.date, sort=True)]
    htf_table = build_htf_states(frame)
    for session_index in range(1, len(sessions)):
        day, bars = sessions[session_index]
        _, prior = sessions[session_index - 1]
        levels = traditional_levels(prior)
        prior_range = levels["pdh"] - levels["pdl"]
        if prior_range <= 0:
            continue
        five = resample_real_bars(bars, 5)
        fifteen_ha = heikin_ashi_state(resample_real_bars(bars, 15))
        vwap = _session_vwap(five)
        states = asof_htf(htf_table, day)
        for position in range(0, len(five) - 1):
            signal_bar = five.iloc[position]
            event = strict_level_failed2(
                signal_bar,
                levels,
                prior_range * CONFIG.pivot_tolerance_prior_range,
            )
            if event is None:
                continue
            direction, level_name = event
            signal_at = five.index[position]
            execution = five.iloc[position + 1:]
            entry = float(execution.iloc[0]["open"])
            stop = (
                float(signal_bar["low"]) - spec.tick_size
                if direction == "long"
                else float(signal_bar["high"]) + spec.tick_size
            )
            if not stop_is_valid(direction, entry, stop):
                continue
            risk = abs(entry - stop)
            if risk < CONFIG.minimum_risk_ticks * spec.tick_size:
                continue
            if risk > CONFIG.max_risk_prior_range * prior_range:
                continue
            target = (
                entry + CONFIG.reward_risk * risk
                if direction == "long"
                else entry - CONFIG.reward_risk * risk
            )
            ha_ok = _ha_aligned(fifteen_ha, signal_at, direction)
            vwap_value = float(vwap.iloc[position])
            vwap_ok = (
                float(signal_bar["close"]) > vwap_value
                if direction == "long"
                else float(signal_bar["close"]) < vwap_value
            )
            contexts = {
                "killzone": _killzone(signal_at, CONFIG),
                "ha": ha_ok,
                "vwap": vwap_ok,
                "htf": htf_nonopposed(states, direction),
            }
            outcome = simulate_exit(
                execution,
                direction=direction,
                entry=entry,
                stop=stop,
                target=target,
                cost_r=_cost_r(spec, entry, risk),
            )
            row = {
                "date": str(day),
                "signal_at": str(signal_at),
                "entry_at": str(execution.index[0]),
                "entry": round(entry, 6),
                "stop": round(stop, 6),
                "target": round(target, 6),
                "direction": direction,
                "level_name": level_name,
                "contexts": contexts,
                "htf_states": states,
                **outcome,
            }
            for variant in VARIANTS:
                if output[variant] and output[variant][-1]["date"] == str(day):
                    continue
                if _allows(variant, **contexts):
                    output[variant].append(row)
    return output


def evaluate_market(frame: pd.DataFrame, spec: MarketSpec) -> dict[str, Any]:
    complete, coverage = complete_sessions(frame)
    rows = replay(complete, spec)
    variants: dict[str, Any] = {}
    for variant, trades in rows.items():
        split = partition(trades)
        split_metrics = {name: metrics(values) for name, values in split.items()}
        variants[variant] = {
            "aggregate": metrics(trades),
            **split_metrics,
            "promotion_gate": promotion_gate(split_metrics),
        }
    return {"coverage": coverage, "variants": variants}


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
        "experiment": "FAILED2-SOURCE-MATCHED-2026-07-25",
        "mode": "research_only_preregistered",
        "execution_enabled": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "variants": list(VARIANTS),
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (MES_CSV, SPY_PARQUET)
        },
        "markets": markets,
        "cross_market_promotion": cross_market,
        "warnings": [
            "This run matches the public single-candle Failed 2 description.",
            "SPY results are IEX underlying paths, not option returns.",
            "Heikin-Ashi is state only; every fill uses real OHLC.",
            "The final period is consumed diagnostic evidence.",
            "No trading or scheduler state changed.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mes-csv", type=Path, default=MES_CSV)
    parser.add_argument("--spy-parquet", type=Path, default=SPY_PARQUET)
    parser.add_argument("--out", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    report = evaluate(load_csv(args.mes_csv), load_parquet(args.spy_parquet))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
