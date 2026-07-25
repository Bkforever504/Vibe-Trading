#!/usr/bin/env python3
"""Preregistered one-minute MES failed-breakdown/reclaim research lab.

This is an isolated research family. It does not route orders, mutate strategy
state, or feed an execution gate. Parameters are selected on development data,
checked on a separate selection period, and only then evaluated once on the
family-specific final period.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "examples" / "mes_v0_1m_2022-01-01_2026-07-19_rth.csv"
DEFAULT_REPORT = ROOT / "data" / "mes_failed_breakdown_results.json"

TICK = 0.25
POINT_VALUE = 5.0
TICK_VALUE = TICK * POINT_VALUE


@dataclass(frozen=True)
class FBDConfig:
    level_family: str = "all"
    min_excursion_ticks: int = 2
    max_excursion_ticks: int = 40
    reclaim_window_bars: int = 3
    acceptance_bars: int = 1
    reward_risk: float = 1.5
    stop_buffer_ticks: int = 1
    min_risk_ticks: int = 4
    max_risk_ticks: int = 60
    entry_start: time = time(9, 35)
    entry_cutoff: time = time(11, 30)
    exit_time: time = time(15, 55)
    slippage_ticks_per_side: int = 1
    commission_round_trip: float = 2.48


def load_bars(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["timestamp"])
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    frame = frame.sort_values("timestamp").set_index("timestamp")
    if frame.index.has_duplicates:
        raise ValueError("duplicate timestamps are not permitted")
    return frame[["open", "high", "low", "close", "volume"]].astype(float)


def session_map(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        str(day): group.copy()
        for day, group in frame.groupby(frame.index.date, sort=True)
    }


def _level_candidates(
    current: pd.DataFrame,
    previous: pd.DataFrame | None,
    config: FBDConfig,
) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    if previous is not None and config.level_family in {"all", "prior_day"}:
        levels.extend(
            [
                {
                    "name": "prior_day_low",
                    "side": "long",
                    "price": float(previous["low"].min()),
                    "available_at": config.entry_start,
                },
                {
                    "name": "prior_day_high",
                    "side": "short",
                    "price": float(previous["high"].max()),
                    "available_at": config.entry_start,
                },
            ]
        )
    if config.level_family in {"all", "opening_range"}:
        opening = current.between_time("09:30", "09:59")
        if not opening.empty:
            levels.extend(
                [
                    {
                        "name": "opening_range_low",
                        "side": "long",
                        "price": float(opening["low"].min()),
                        "available_at": time(10, 0),
                    },
                    {
                        "name": "opening_range_high",
                        "side": "short",
                        "price": float(opening["high"].max()),
                        "available_at": time(10, 0),
                    },
                ]
            )
    return levels


def _simulate_exit(
    bars: pd.DataFrame,
    *,
    entry_position: int,
    side: str,
    stop: float,
    target: float,
    exit_time: time,
) -> tuple[float, pd.Timestamp, str]:
    future = bars.iloc[entry_position:]
    timed = future[future.index.time <= exit_time]
    if timed.empty:
        timed = future.iloc[:1]
    for timestamp, bar in timed.iterrows():
        if side == "long":
            if float(bar["low"]) <= stop:
                return stop, timestamp, "stop"
            if float(bar["high"]) >= target:
                return target, timestamp, "target"
        else:
            if float(bar["high"]) >= stop:
                return stop, timestamp, "stop"
            if float(bar["low"]) <= target:
                return target, timestamp, "target"
    last_timestamp = timed.index[-1]
    return float(timed.iloc[-1]["close"]), last_timestamp, "time"


def find_level_trade(
    bars: pd.DataFrame,
    level: dict[str, Any],
    config: FBDConfig,
    *,
    entry_delay_bars: int = 0,
) -> dict[str, Any] | None:
    """Return the first qualifying trade at one precomputed level.

    The first qualifying excursion consumes the level for the session even when
    it fails to reclaim. This prevents repeated hindsight attempts.
    """
    side = str(level["side"])
    level_price = float(level["price"])
    available_at = max(config.entry_start, level["available_at"])
    positions = [
        position
        for position, timestamp in enumerate(bars.index)
        if available_at <= timestamp.time() < config.entry_cutoff
    ]
    min_excursion = config.min_excursion_ticks * TICK
    max_excursion = config.max_excursion_ticks * TICK
    for flush_position in positions:
        flush = bars.iloc[flush_position]
        crossed = (
            float(flush["low"]) <= level_price - min_excursion
            if side == "long"
            else float(flush["high"]) >= level_price + min_excursion
        )
        if not crossed:
            continue

        extreme = float(flush["low"] if side == "long" else flush["high"])
        deadline = min(len(bars) - 1, flush_position + config.reclaim_window_bars)
        reclaim_position: int | None = None
        invalid = False
        for position in range(flush_position, deadline + 1):
            bar = bars.iloc[position]
            extreme = (
                min(extreme, float(bar["low"]))
                if side == "long"
                else max(extreme, float(bar["high"]))
            )
            excursion = level_price - extreme if side == "long" else extreme - level_price
            if excursion > max_excursion:
                invalid = True
                break
            reclaimed = (
                float(bar["close"]) >= level_price
                if side == "long"
                else float(bar["close"]) <= level_price
            )
            if reclaimed:
                reclaim_position = position
                break
        if invalid or reclaim_position is None:
            return None

        acceptance_start = reclaim_position + 1
        acceptance_end = acceptance_start + config.acceptance_bars
        if acceptance_end > len(bars):
            return None
        acceptance = bars.iloc[acceptance_start:acceptance_end]
        accepted = (
            bool((acceptance["close"] >= level_price).all())
            if side == "long"
            else bool((acceptance["close"] <= level_price).all())
        )
        if not accepted:
            return None

        entry_position = acceptance_end + entry_delay_bars
        if entry_position >= len(bars):
            return None
        entry_timestamp = bars.index[entry_position]
        if entry_timestamp.time() >= config.entry_cutoff:
            return None
        entry = float(bars.iloc[entry_position]["open"])
        stop = (
            extreme - config.stop_buffer_ticks * TICK
            if side == "long"
            else extreme + config.stop_buffer_ticks * TICK
        )
        risk = entry - stop if side == "long" else stop - entry
        risk_ticks = risk / TICK
        if not config.min_risk_ticks <= risk_ticks <= config.max_risk_ticks:
            return None
        target = (
            entry + config.reward_risk * risk
            if side == "long"
            else entry - config.reward_risk * risk
        )
        exit_price, exit_timestamp, exit_reason = _simulate_exit(
            bars,
            entry_position=entry_position,
            side=side,
            stop=stop,
            target=target,
            exit_time=config.exit_time,
        )
        gross_points = exit_price - entry if side == "long" else entry - exit_price
        gross_pnl = gross_points * POINT_VALUE
        return {
            "date": entry_timestamp.date().isoformat(),
            "level": level["name"],
            "side": side,
            "flush_at": bars.index[flush_position].isoformat(),
            "reclaim_at": bars.index[reclaim_position].isoformat(),
            "entry_at": entry_timestamp.isoformat(),
            "exit_at": exit_timestamp.isoformat(),
            "entry": round(entry, 4),
            "stop": round(stop, 4),
            "target": round(target, 4),
            "risk_ticks": round(risk_ticks, 2),
            "exit_reason": exit_reason,
            "gross_pnl": round(gross_pnl, 2),
        }
    return None


def replay_sessions(
    sessions: dict[str, pd.DataFrame],
    dates: Iterable[str],
    config: FBDConfig,
    *,
    entry_delay_bars: int = 0,
) -> list[dict[str, Any]]:
    ordered = sorted(sessions)
    previous_by_date = {
        ordered[position]: (sessions[ordered[position - 1]] if position else None)
        for position in range(len(ordered))
    }
    trades: list[dict[str, Any]] = []
    for date in dates:
        bars = sessions[date]
        candidates = _level_candidates(bars, previous_by_date.get(date), config)
        day_trades = [
            trade
            for level in candidates
            if (
                trade := find_level_trade(
                    bars,
                    level,
                    config,
                    entry_delay_bars=entry_delay_bars,
                )
            )
            is not None
        ]
        if day_trades:
            trades.append(min(day_trades, key=lambda trade: trade["entry_at"]))
    return trades


def metrics(
    trades: list[dict[str, Any]],
    config: FBDConfig,
    *,
    cost_multiple: float = 1.0,
    remove_top_pct: float = 0.0,
) -> dict[str, Any]:
    per_trade_cost = (
        config.commission_round_trip
        + 2 * config.slippage_ticks_per_side * TICK_VALUE
    ) * cost_multiple
    values = [float(trade["gross_pnl"]) - per_trade_cost for trade in trades]
    if remove_top_pct > 0 and values:
        remove_count = max(1, int(np.ceil(len(values) * remove_top_pct)))
        winners = sorted(range(len(values)), key=values.__getitem__, reverse=True)[:remove_count]
        removed = set(winners)
        values = [value for index, value in enumerate(values) if index not in removed]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    equity = peak = max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "trades": len(values),
        "total_pnl": round(sum(values), 2),
        "expectancy": round(float(np.mean(values)), 2) if values else None,
        "win_rate": round(len(wins) / len(values), 4) if values else None,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 3) if losses else None,
        "max_drawdown": round(max_drawdown, 2),
    }


def _development_pass(rows: list[dict[str, Any]]) -> bool:
    return all(
        row["trades"] >= 20
        and (row["expectancy"] or 0) > 0
        and (row["profit_factor"] or 0) >= 1.05
        for row in rows
    )


def _selection_pass(base: dict[str, Any], stressed: dict[str, Any]) -> bool:
    return (
        base["trades"] >= 30
        and (base["expectancy"] or 0) > 0
        and (base["profit_factor"] or 0) >= 1.20
        and (stressed["expectancy"] or 0) > 0
    )


def parameter_grid() -> list[FBDConfig]:
    return [
        FBDConfig(
            level_family=family,
            min_excursion_ticks=excursion,
            reclaim_window_bars=reclaim,
            acceptance_bars=acceptance,
            reward_risk=rr,
        )
        for family in ("prior_day", "opening_range", "all")
        for excursion in (1, 2, 4)
        for reclaim in (1, 3, 5)
        for acceptance in (1, 2)
        for rr in (1.5, 2.0)
    ]


def evaluate(frame: pd.DataFrame) -> dict[str, Any]:
    sessions = session_map(frame)
    dates = sorted(sessions)
    dev_end = int(len(dates) * 0.60)
    selection_end = int(len(dates) * 0.80)
    development = dates[:dev_end]
    selection = dates[dev_end:selection_end]
    final = dates[selection_end:]
    third = len(development) // 3
    regimes = [
        development[:third],
        development[third:2 * third],
        development[2 * third:],
    ]

    development_rows: list[dict[str, Any]] = []
    survivors: list[dict[str, Any]] = []
    for config in parameter_grid():
        regime_metrics = [
            metrics(replay_sessions(sessions, window, config), config)
            for window in regimes
        ]
        expectancies = [
            float(row["expectancy"])
            for row in regime_metrics
            if row["expectancy"] is not None
        ]
        positive_regimes = sum(
            row["trades"] >= 20
            and (row["expectancy"] or 0) > 0
            and (row["profit_factor"] or 0) >= 1.05
            for row in regime_metrics
        )
        aggregate_expectancy = (
            sum(float(row["total_pnl"]) for row in regime_metrics)
            / sum(int(row["trades"]) for row in regime_metrics)
            if sum(int(row["trades"]) for row in regime_metrics)
            else float("-inf")
        )
        entry = {
            "config": config,
            "development_regimes": regime_metrics,
            "positive_regime_count": positive_regimes,
            "worst_regime_expectancy": min(expectancies, default=float("-inf")),
            "aggregate_expectancy": aggregate_expectancy,
        }
        development_rows.append(entry)
        if _development_pass(regime_metrics):
            survivors.append(
                {
                    **entry,
                    "development_score": min(expectancies),
                }
            )
    development_rows.sort(
        key=lambda row: (
            row["positive_regime_count"],
            row["worst_regime_expectancy"],
            row["aggregate_expectancy"],
        ),
        reverse=True,
    )
    survivors.sort(key=lambda row: row["development_score"], reverse=True)

    selection_rows: list[dict[str, Any]] = []
    for row in survivors[:20]:
        config = row["config"]
        trades = replay_sessions(sessions, selection, config)
        base = metrics(trades, config)
        stressed = metrics(trades, config, cost_multiple=2.0)
        selection_rows.append(
            {
                **row,
                "selection": base,
                "selection_double_cost": stressed,
                "selection_pass": _selection_pass(base, stressed),
            }
        )
    passed = [row for row in selection_rows if row["selection_pass"]]
    passed.sort(
        key=lambda row: (
            float(row["selection_double_cost"]["expectancy"]),
            -float(row["selection"]["max_drawdown"]),
        ),
        reverse=True,
    )

    finalist: dict[str, Any] | None = None
    if passed:
        chosen = passed[0]
        config = chosen["config"]
        final_trades = replay_sessions(sessions, final, config)
        final_base = metrics(final_trades, config)
        final_double = metrics(final_trades, config, cost_multiple=2.0)
        final_triple = metrics(final_trades, config, cost_multiple=3.0)
        final_delay = metrics(
            replay_sessions(sessions, final, config, entry_delay_bars=1),
            config,
            cost_multiple=2.0,
        )
        final_without_top = metrics(
            final_trades,
            config,
            cost_multiple=2.0,
            remove_top_pct=0.01,
        )
        finalist = {
            **chosen,
            "config": asdict(config),
            "final": final_base,
            "final_double_cost": final_double,
            "final_triple_cost": final_triple,
            "final_one_bar_delay_double_cost": final_delay,
            "final_double_cost_without_top_1pct": final_without_top,
            "final_pass": (
                final_base["trades"] >= 30
                and (final_base["profit_factor"] or 0) >= 1.20
                and (final_double["expectancy"] or 0) > 0
                and (final_delay["expectancy"] or 0) > 0
                and (final_without_top["expectancy"] or 0) > 0
                and final_base["max_drawdown"] <= 200.0
            ),
        }

    return {
        "schema_version": 1,
        "experiment": "COPY-MES-FBD-01",
        "mode": "research_only",
        "execution_enabled": False,
        "dataset_sessions": len(dates),
        "periods": {
            "development": [development[0], development[-1], len(development)],
            "selection": [selection[0], selection[-1], len(selection)],
            "family_specific_final": [final[0], final[-1], len(final)],
        },
        "parameter_count": len(parameter_grid()),
        "development_survivor_count": len(survivors),
        "development_near_misses": [
            {
                **row,
                "config": asdict(row["config"]),
                "worst_regime_expectancy": (
                    round(row["worst_regime_expectancy"], 4)
                    if np.isfinite(row["worst_regime_expectancy"])
                    else None
                ),
                "aggregate_expectancy": (
                    round(row["aggregate_expectancy"], 4)
                    if np.isfinite(row["aggregate_expectancy"])
                    else None
                ),
            }
            for row in development_rows[:10]
        ],
        "selection_evaluated_count": len(selection_rows),
        "selection_pass_count": len(passed),
        "selection_rows": [
            {
                **row,
                "config": asdict(row["config"]),
            }
            for row in selection_rows
        ],
        "finalist": finalist,
        "warnings": [
            "The dataset was used by earlier MES research, so the final period is family-specific rather than globally pristine.",
            "Stop is resolved before target when both are touched in one minute.",
            "Only the earliest qualifying level trade per session is retained.",
            "No orders or execution-gate state were changed.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = evaluate(load_bars(args.csv))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    if args.do_print:
        summary = {
            key: report[key]
            for key in (
                "dataset_sessions",
                "parameter_count",
                "development_survivor_count",
                "selection_evaluated_count",
                "selection_pass_count",
                "finalist",
            )
        }
        print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
