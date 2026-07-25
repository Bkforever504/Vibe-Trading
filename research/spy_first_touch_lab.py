#!/usr/bin/env python3
"""Point-in-time SPY first-touch rejection challenger.

Underlying-only research. Option returns are deliberately not inferred from
SPY bars. The lab freezes touch events first, selects parameters on development
and selection periods, and opens the family-specific final period at most once.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PARQUET = ROOT / "data" / "spy_1m_edge_lab.parquet"
DEFAULT_REPORT = ROOT / "data" / "spy_first_touch_results.json"


@dataclass(frozen=True)
class FirstTouchConfig:
    level_family: str = "all"
    rsi_extreme: int = 75
    approach_minutes: int = 3
    min_approach_bps: float = 3.0
    reward_risk: float = 1.5
    rsi_period: int = 14
    stop_buffer: float = 0.05
    min_risk: float = 0.05
    max_risk: float = 1.00
    start: time = time(9, 30)
    cutoff: time = time(11, 15)
    exit_time: time = time(15, 55)
    slippage_bps_per_side: float = 1.0


def load_bars(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    frame.index = pd.to_datetime(frame.index)
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("America/New_York")
    else:
        frame.index = frame.index.tz_convert("America/New_York")
    frame = frame.sort_index()
    if frame.index.has_duplicates:
        frame = frame[~frame.index.duplicated(keep="last")]
    return frame[["open", "high", "low", "close", "volume"]].astype(float)


def rth_session_dates(frame: pd.DataFrame) -> list[str]:
    rth = frame.between_time("09:30", "16:00")
    return sorted({str(day) for day in rth.index.date})


def rsi(values: pd.Series, period: int = 14) -> pd.Series:
    delta = values.diff()
    gain = delta.clip(lower=0).rolling(period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).rolling(period, min_periods=period).mean()
    valid = gain.notna() & loss.notna()
    relative = gain / loss.replace(0, np.nan)
    output = 100 - 100 / (1 + relative)
    output = output.where(loss > 0, 100.0)
    output = output.where(gain > 0, 0.0)
    return output.where(valid)


def _levels(
    day_all: pd.DataFrame,
    prior_rth: pd.DataFrame | None,
) -> list[dict[str, Any]]:
    rth = day_all.between_time("09:30", "16:00")
    if rth.empty:
        return []
    opening_price = float(rth.iloc[0]["open"])
    levels: list[dict[str, Any]] = []
    if prior_rth is not None:
        levels.extend(
            [
                {"name": "prior_day_high", "family": "prior_day", "side": "short", "price": float(prior_rth["high"].max())},
                {"name": "prior_day_low", "family": "prior_day", "side": "long", "price": float(prior_rth["low"].min())},
            ]
        )
    premarket = day_all.between_time("04:00", "09:29")
    if not premarket.empty:
        levels.extend(
            [
                {"name": "premarket_high", "family": "premarket", "side": "short", "price": float(premarket["high"].max())},
                {"name": "premarket_low", "family": "premarket", "side": "long", "price": float(premarket["low"].min())},
            ]
        )
    lower = int(np.floor(opening_price - 6))
    upper = int(np.ceil(opening_price + 6))
    for whole in range(lower, upper + 1):
        if whole > opening_price:
            levels.append({"name": f"whole_{whole}", "family": "whole", "side": "short", "price": float(whole)})
        elif whole < opening_price:
            levels.append({"name": f"whole_{whole}", "family": "whole", "side": "long", "price": float(whole)})
    return levels


def build_events(frame: pd.DataFrame, base: FirstTouchConfig | None = None) -> list[dict[str, Any]]:
    base = base or FirstTouchConfig()
    all_days = {str(day): group for day, group in frame.groupby(frame.index.date, sort=True)}
    dates = sorted(all_days)
    prior_rth: pd.DataFrame | None = None
    events: list[dict[str, Any]] = []
    for date in dates:
        day_all = all_days[date]
        rth = day_all.between_time(base.start.strftime("%H:%M"), "16:00").copy()
        if rth.empty:
            continue
        rth["rsi"] = rsi(rth["close"], base.rsi_period)
        for minutes in (3, 5):
            rth[f"approach_{minutes}"] = (rth["close"] / rth["close"].shift(minutes) - 1) * 10_000
        for level in _levels(day_all, prior_rth):
            candidates = rth[rth.index.time < base.cutoff]
            touch_position: int | None = None
            for position in range(1, len(candidates)):
                bar = candidates.iloc[position]
                previous_close = float(candidates.iloc[position - 1]["close"])
                touched = (
                    previous_close < level["price"] <= float(bar["high"])
                    if level["side"] == "short"
                    else previous_close > level["price"] >= float(bar["low"])
                )
                if touched:
                    touch_position = rth.index.get_loc(candidates.index[position])
                    break
            if touch_position is None or touch_position + 1 >= len(rth):
                continue
            touch = rth.iloc[touch_position]
            rejected = (
                float(touch["close"]) <= level["price"]
                if level["side"] == "short"
                else float(touch["close"]) >= level["price"]
            )
            if not rejected or not np.isfinite(float(touch["rsi"])):
                continue
            entry_position = touch_position + 1
            entry_at = rth.index[entry_position]
            if entry_at.time() >= base.cutoff:
                continue
            entry = float(rth.iloc[entry_position]["open"])
            stop = (
                float(touch["high"]) + base.stop_buffer
                if level["side"] == "short"
                else float(touch["low"]) - base.stop_buffer
            )
            risk = stop - entry if level["side"] == "short" else entry - stop
            if not base.min_risk <= risk <= base.max_risk:
                continue
            events.append(
                {
                    "date": date,
                    "level": level["name"],
                    "family": level["family"],
                    "side": level["side"],
                    "level_price": round(level["price"], 4),
                    "touch_at": rth.index[touch_position].isoformat(),
                    "entry_at": entry_at.isoformat(),
                    "entry_position": entry_position,
                    "entry": entry,
                    "stop": stop,
                    "risk": risk,
                    "rsi": float(touch["rsi"]),
                    "approach_3": float(touch["approach_3"]),
                    "approach_5": float(touch["approach_5"]),
                    "_bars": rth,
                }
            )
        prior_rth = day_all.between_time("09:30", "16:00")
    return events


def _event_passes(event: dict[str, Any], config: FirstTouchConfig) -> bool:
    if config.level_family != "all" and event["family"] != config.level_family:
        return False
    if event["side"] == "short":
        if event["rsi"] < config.rsi_extreme:
            return False
        approach = event[f"approach_{config.approach_minutes}"]
        return np.isfinite(approach) and approach >= config.min_approach_bps
    if event["rsi"] > 100 - config.rsi_extreme:
        return False
    approach = event[f"approach_{config.approach_minutes}"]
    return np.isfinite(approach) and approach <= -config.min_approach_bps


def _simulate(event: dict[str, Any], config: FirstTouchConfig, cost_multiple: float) -> dict[str, Any]:
    bars = event["_bars"]
    entry_position = int(event["entry_position"])
    entry = float(event["entry"])
    stop = float(event["stop"])
    risk = float(event["risk"])
    side = event["side"]
    target = entry - config.reward_risk * risk if side == "short" else entry + config.reward_risk * risk
    future = bars.iloc[entry_position:]
    future = future[future.index.time <= config.exit_time]
    exit_price = float(future.iloc[-1]["close"])
    reason = "time"
    for _, bar in future.iterrows():
        if side == "long":
            if float(bar["low"]) <= stop:
                exit_price, reason = stop, "stop"
                break
            if float(bar["high"]) >= target:
                exit_price, reason = target, "target"
                break
        else:
            if float(bar["high"]) >= stop:
                exit_price, reason = stop, "stop"
                break
            if float(bar["low"]) <= target:
                exit_price, reason = target, "target"
                break
    gross = entry - exit_price if side == "short" else exit_price - entry
    cost = 2 * entry * config.slippage_bps_per_side * cost_multiple / 10_000
    return {
        "date": event["date"],
        "entry_at": event["entry_at"],
        "side": side,
        "family": event["family"],
        "reason": reason,
        "net_r": (gross - cost) / risk,
    }


def trades_for(
    events: list[dict[str, Any]],
    dates: list[str],
    config: FirstTouchConfig,
    *,
    cost_multiple: float = 1.0,
) -> list[dict[str, Any]]:
    allowed_dates = set(dates)
    eligible = [event for event in events if event["date"] in allowed_dates and _event_passes(event, config)]
    earliest: dict[str, dict[str, Any]] = {}
    for event in eligible:
        current = earliest.get(event["date"])
        if current is None or event["entry_at"] < current["entry_at"]:
            earliest[event["date"]] = event
    return [_simulate(earliest[date], config, cost_multiple) for date in sorted(earliest)]


def metrics(trades: list[dict[str, Any]], *, remove_top_pct: float = 0.0) -> dict[str, Any]:
    values = [float(trade["net_r"]) for trade in trades]
    if remove_top_pct > 0 and values:
        remove_count = max(1, int(np.ceil(len(values) * remove_top_pct)))
        removed = set(sorted(range(len(values)), key=values.__getitem__, reverse=True)[:remove_count])
        values = [value for index, value in enumerate(values) if index not in removed]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "trades": len(values),
        "expectancy_r": round(float(np.mean(values)), 4) if values else None,
        "win_rate": round(len(wins) / len(values), 4) if values else None,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 3) if losses else None,
        "net_r": round(sum(values), 3),
        "max_drawdown_r": round(drawdown, 3),
    }


def parameter_grid() -> list[FirstTouchConfig]:
    return [
        FirstTouchConfig(
            level_family=family,
            rsi_extreme=extreme,
            approach_minutes=minutes,
            min_approach_bps=speed,
            reward_risk=rr,
        )
        for family in ("prior_day", "premarket", "whole", "all")
        for extreme in (70, 75, 80)
        for minutes in (3, 5)
        for speed in (0.0, 3.0, 6.0)
        for rr in (1.0, 1.5)
    ]


def evaluate(frame: pd.DataFrame) -> dict[str, Any]:
    events = build_events(frame)
    dates = rth_session_dates(frame)
    dev_end, selection_end = int(len(dates) * 0.60), int(len(dates) * 0.80)
    development, selection, final = dates[:dev_end], dates[dev_end:selection_end], dates[selection_end:]
    third = len(development) // 3
    regimes = [development[:third], development[third:2 * third], development[2 * third:]]
    development_rows = []
    for config in parameter_grid():
        rows = [metrics(trades_for(events, window, config)) for window in regimes]
        positive = sum(
            row["trades"] >= 20
            and (row["expectancy_r"] or 0) > 0
            and (row["profit_factor"] or 0) >= 1.05
            for row in rows
        )
        development_rows.append(
            {
                "config": config,
                "development_regimes": rows,
                "positive_regime_count": positive,
                "worst_expectancy_r": min(
                    (float(row["expectancy_r"]) for row in rows if row["expectancy_r"] is not None),
                    default=float("-inf"),
                ),
            }
        )
    development_rows.sort(
        key=lambda row: (row["positive_regime_count"], row["worst_expectancy_r"]),
        reverse=True,
    )
    survivors = [row for row in development_rows if row["positive_regime_count"] == 3]
    selection_rows = []
    for row in survivors[:20]:
        config = row["config"]
        base = metrics(trades_for(events, selection, config))
        stress = metrics(trades_for(events, selection, config, cost_multiple=2.0))
        selection_rows.append(
            {
                **row,
                "selection": base,
                "selection_double_cost": stress,
                "selection_pass": (
                    base["trades"] >= 30
                    and (base["expectancy_r"] or 0) > 0
                    and (base["profit_factor"] or 0) >= 1.20
                    and (stress["expectancy_r"] or 0) > 0
                ),
            }
        )
    passed = [row for row in selection_rows if row["selection_pass"]]
    passed.sort(key=lambda row: row["selection_double_cost"]["expectancy_r"], reverse=True)
    finalist = None
    if passed:
        chosen = passed[0]
        config = chosen["config"]
        base_trades = trades_for(events, final, config)
        double_trades = trades_for(events, final, config, cost_multiple=2.0)
        triple_trades = trades_for(events, final, config, cost_multiple=3.0)
        base = metrics(base_trades)
        double = metrics(double_trades)
        triple = metrics(triple_trades)
        trimmed = metrics(double_trades, remove_top_pct=0.01)
        finalist = {
            **chosen,
            "config": asdict(config),
            "final": base,
            "final_double_cost": double,
            "final_triple_cost": triple,
            "final_double_cost_without_top_1pct": trimmed,
            "final_pass": (
                base["trades"] >= 30
                and (base["profit_factor"] or 0) >= 1.20
                and (double["expectancy_r"] or 0) > 0
                and (trimmed["expectancy_r"] or 0) > 0
                and base["max_drawdown_r"] <= 10.0
            ),
        }
    clean = lambda row: {**row, "config": asdict(row["config"]), "worst_expectancy_r": None if not np.isfinite(row["worst_expectancy_r"]) else row["worst_expectancy_r"]}
    return {
        "schema_version": 1,
        "experiment": "COPY-SPY-FT-01",
        "mode": "research_only",
        "execution_enabled": False,
        "instrument": "SPY underlying",
        "options_pnl_tested": False,
        "event_count": len(events),
        "session_count": len(dates),
        "periods": {
            "development": [development[0], development[-1], len(development)],
            "selection": [selection[0], selection[-1], len(selection)],
            "family_specific_final": [final[0], final[-1], len(final)],
        },
        "parameter_count": len(parameter_grid()),
        "development_survivor_count": len(survivors),
        "development_near_misses": [clean(row) for row in development_rows[:10]],
        "selection_evaluated_count": len(selection_rows),
        "selection_pass_count": len(passed),
        "selection_rows": [clean(row) for row in selection_rows],
        "finalist": finalist,
        "warnings": [
            "IEX minute bars are not consolidated SIP data.",
            "Underlying R-multiples do not establish an option-pricing edge.",
            "Stop is resolved before target on same-minute ambiguity.",
            "Only the earliest eligible event per session is retained.",
            "No order or execution-gate state was changed.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, default=DEFAULT_PARQUET)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = evaluate(load_bars(args.parquet))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    if args.do_print:
        print(json.dumps({
            key: report[key]
            for key in (
                "event_count",
                "session_count",
                "parameter_count",
                "development_survivor_count",
                "selection_pass_count",
                "finalist",
            )
        }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
