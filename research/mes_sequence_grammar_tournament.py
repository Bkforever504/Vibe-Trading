#!/usr/bin/env python3
"""Development-only tournament for 288 causal MES trading sequences.

The grammar composes declared liquidity references, event types,
confirmations, entries, and exits. Every combination is retained. This module
has no broker imports and cannot submit or promote orders.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
from statistics import NormalDist

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "examples" / "mes_v0_1m_2022-01-01_2026-07-19_rth.csv"
DEFAULT_REGISTRY = ROOT / "research" / "edge_trials" / "mes_sequence_grammar_registry_2026-08-18.json"
DEFAULT_OUT = ROOT / "data" / "mes_sequence_grammar_results.json"
SPEC = "research/MES_SEQUENCE_GRAMMAR_SPEC_2026-08-18.md"

TICK = 0.25
POINT_VALUE = 5.0
ROUND_TRIP_FRICTION = 4.98
EXISTING_ATTEMPTS = 515
ANCHORS = ("opening_15m", "opening_30m", "prior_day", "session_vwap")
EVENTS = ("breakout", "sweep_reclaim")
CONFIRMATIONS = ("none", "volume_1_2x", "displacement_0_6atr")
ENTRIES = ("signal_close", "next_bar_confirm", "level_retest")
REWARD_RISKS = (1.0, 1.5, 2.0, 3.0)
TRIAL_COUNT = len(ANCHORS) * len(EVENTS) * len(CONFIRMATIONS) * len(ENTRIES) * len(REWARD_RISKS)
EFFECTIVE_ATTEMPTS = EXISTING_ATTEMPTS + TRIAL_COUNT
BONFERRONI_ALPHA = 0.05 / EFFECTIVE_ATTEMPTS
ENTRY_START = "10:00"
ENTRY_END = "11:30"
MAX_HOLD_BARS = 12
MAX_RETEST_BARS = 6
MIN_RISK_TICKS = 4
MAX_RISK_TICKS = 60


def build_registry() -> dict:
    trials = []
    combinations = itertools.product(ANCHORS, EVENTS, CONFIRMATIONS, ENTRIES, REWARD_RISKS)
    for idx, (anchor, event, confirmation, entry, reward_risk) in enumerate(combinations, start=1):
        trials.append({
            "trial_id": f"SEQ288-{idx:03d}",
            "anchor": anchor,
            "event": event,
            "confirmation": confirmation,
            "entry": entry,
            "reward_risk": reward_risk,
            "entry_start_et": ENTRY_START,
            "entry_end_et": ENTRY_END,
            "max_hold_bars_5m": MAX_HOLD_BARS,
        })
    payload = {
        "experiment": "MES-SEQUENCE-GRAMMAR-288",
        "specification": SPEC,
        "trial_count": len(trials),
        "existing_attempt_count": EXISTING_ATTEMPTS,
        "effective_attempt_count": EFFECTIVE_ATTEMPTS,
        "execution_enabled": False,
        "can_submit_orders": False,
        "trials": trials,
    }
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload["registry_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return payload


def prepare(raw: pd.DataFrame) -> tuple[list[str], dict[str, pd.DataFrame]]:
    frame = raw.copy()
    frame["dt"] = pd.to_datetime(frame["timestamp"], errors="raise")
    frame["date"] = frame["dt"].dt.date.astype(str)
    sessions: dict[str, pd.DataFrame] = {}
    for day, minute in frame.groupby("date", sort=True):
        fields = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        if "instrument_id" in minute.columns:
            fields["instrument_id"] = "last"
        five = minute.set_index("dt").resample("5min", label="left", closed="left").agg(fields).dropna().reset_index()
        if len(five) < 60:
            continue
        five["time"] = five["dt"].dt.strftime("%H:%M")
        prior_close = five["close"].shift(1)
        true_range = pd.concat([
            five["high"] - five["low"],
            (five["high"] - prior_close).abs(),
            (five["low"] - prior_close).abs(),
        ], axis=1).max(axis=1)
        five["atr6"] = true_range.shift(1).rolling(6).mean()
        five["volume_mean6"] = five["volume"].shift(1).rolling(6).mean()
        typical = (five["high"] + five["low"] + five["close"]) / 3.0
        cumulative_volume = five["volume"].clip(lower=0).cumsum()
        five["vwap"] = (typical * five["volume"].clip(lower=0)).cumsum() / cumulative_volume.replace(0, math.nan)
        sessions[day] = five
    return sorted(sessions), sessions


def _same_contract(current: pd.DataFrame, previous: pd.DataFrame | None) -> bool:
    if previous is None or "instrument_id" not in current or "instrument_id" not in previous:
        return previous is not None
    return str(current.iloc[0]["instrument_id"]) == str(previous.iloc[-1]["instrument_id"])


def _levels(bars: pd.DataFrame, previous: pd.DataFrame | None, idx: int, anchor: str) -> tuple[float, float] | None:
    if anchor == "opening_15m":
        opening = bars.iloc[:3]
        return float(opening["high"].max()), float(opening["low"].min())
    if anchor == "opening_30m":
        opening = bars.iloc[:6]
        return float(opening["high"].max()), float(opening["low"].min())
    if anchor == "prior_day":
        if not _same_contract(bars, previous):
            return None
        return float(previous["high"].max()), float(previous["low"].min())
    value = float(bars.iloc[idx]["vwap"])
    return (value, value) if math.isfinite(value) else None


def _event_side(
    bars: pd.DataFrame,
    idx: int,
    upper: float,
    lower: float,
    event: str,
) -> int:
    row = bars.iloc[idx]
    prior = bars.iloc[idx - 1]
    if event == "breakout":
        prior_upper = float(prior["vwap"]) if upper == lower else upper
        prior_lower = prior_upper if upper == lower else lower
        long_break = float(row["close"]) >= upper + TICK and float(prior["close"]) <= prior_upper
        short_break = float(row["close"]) <= lower - TICK and float(prior["close"]) >= prior_lower
        return 1 if long_break else -1 if short_break else 0
    short_reclaim = float(row["high"]) >= upper + TICK and float(row["close"]) < upper
    long_reclaim = float(row["low"]) <= lower - TICK and float(row["close"]) > lower
    return -1 if short_reclaim else 1 if long_reclaim else 0


def _confirmation_ok(row: pd.Series, side: int, confirmation: str) -> bool:
    if confirmation == "none":
        return True
    if confirmation == "volume_1_2x":
        baseline = float(row["volume_mean6"])
        return math.isfinite(baseline) and baseline > 0 and float(row["volume"]) >= 1.2 * baseline
    atr = float(row["atr6"])
    body = abs(float(row["close"]) - float(row["open"]))
    directional = side * (float(row["close"]) - float(row["open"])) > 0
    return math.isfinite(atr) and atr > 0 and directional and body >= 0.6 * atr


def _entry_index(
    bars: pd.DataFrame,
    signal_idx: int,
    side: int,
    upper: float,
    lower: float,
    event: str,
    entry: str,
) -> int | None:
    if entry == "signal_close":
        return signal_idx
    if entry == "next_bar_confirm":
        idx = signal_idx + 1
        if idx >= len(bars):
            return None
        row, signal = bars.iloc[idx], bars.iloc[signal_idx]
        continues = side * (float(row["close"]) - float(signal["close"])) > 0
        directional = side * (float(row["close"]) - float(row["open"])) > 0
        return idx if continues and directional else None
    level = upper if side > 0 else lower
    if event == "sweep_reclaim":
        level = upper if side < 0 else lower
    for idx in range(signal_idx + 1, min(len(bars), signal_idx + MAX_RETEST_BARS + 1)):
        row = bars.iloc[idx]
        if row["time"] >= ENTRY_END:
            break
        if side > 0 and float(row["low"]) <= level and float(row["close"]) > level:
            return idx
        if side < 0 and float(row["high"]) >= level and float(row["close"]) < level:
            return idx
    return None


def find_signal(
    bars: pd.DataFrame,
    trial: dict,
    previous: pd.DataFrame | None,
) -> tuple[int, int, float] | None:
    for idx in range(6, len(bars) - 1):
        row = bars.iloc[idx]
        if row["time"] < ENTRY_START or row["time"] >= ENTRY_END:
            continue
        levels = _levels(bars, previous, idx, trial["anchor"])
        if levels is None:
            continue
        upper, lower = levels
        side = _event_side(bars, idx, upper, lower, trial["event"])
        if not side or not _confirmation_ok(row, side, trial["confirmation"]):
            continue
        entry_idx = _entry_index(bars, idx, side, upper, lower, trial["event"], trial["entry"])
        if entry_idx is None:
            continue
        entry_row = bars.iloc[entry_idx]
        if entry_row["time"] >= ENTRY_END:
            continue
        if trial["event"] == "sweep_reclaim":
            stop = float(row["low"]) - TICK if side > 0 else float(row["high"]) + TICK
        else:
            anchor_level = upper if side > 0 else lower
            stop = min(float(row["low"]), anchor_level - TICK) if side > 0 else max(float(row["high"]), anchor_level + TICK)
        if trial["entry"] == "level_retest":
            stop = min(stop, float(entry_row["low"]) - TICK) if side > 0 else max(stop, float(entry_row["high"]) + TICK)
        risk_ticks = side * (float(entry_row["close"]) - stop) / TICK
        if MIN_RISK_TICKS <= risk_ticks <= MAX_RISK_TICKS:
            return entry_idx, side, stop
    return None


def manage(bars: pd.DataFrame, entry_idx: int, side: int, stop: float, reward_risk: float) -> float:
    entry = float(bars.iloc[entry_idx]["close"])
    risk = side * (entry - stop)
    target = entry + side * risk * reward_risk
    end = min(len(bars), entry_idx + 1 + MAX_HOLD_BARS)
    for _, row in bars.iloc[entry_idx + 1:end].iterrows():
        stop_hit = float(row["low"]) <= stop if side > 0 else float(row["high"]) >= stop
        target_hit = float(row["high"]) >= target if side > 0 else float(row["low"]) <= target
        if stop_hit:
            return -risk
        if target_hit:
            return reward_risk * risk
    return side * (float(bars.iloc[end - 1]["close"]) - entry)


def metrics(points: list[float], *, cost_multiple: float = 1.0) -> dict:
    pnls = [value * POINT_VALUE - ROUND_TRIP_FRICTION * cost_multiple for value in points]
    if not pnls:
        return {"trades": 0, "expectancy": None, "profit_factor": None, "p_value": None}
    mean = sum(pnls) / len(pnls)
    variance = sum((value - mean) ** 2 for value in pnls) / max(1, len(pnls) - 1)
    standard_error = math.sqrt(variance / len(pnls)) if variance > 0 else 0.0
    t_stat = mean / standard_error if standard_error > 0 else (math.inf if mean > 0 else 0.0)
    p_value = 1.0 - NormalDist().cdf(t_stat) if math.isfinite(t_stat) else 0.0
    wins = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value <= 0)
    equity = pd.Series([0.0, *pnls]).cumsum()
    return {
        "trades": len(pnls),
        "total_pnl": round(sum(pnls), 2),
        "expectancy": round(mean, 4),
        "win_rate": round(sum(value > 0 for value in pnls) / len(pnls), 4),
        "profit_factor": round(wins / losses, 4) if losses > 0 else None,
        "max_drawdown": round(float((equity.cummax() - equity).max()), 2),
        "t_stat": round(t_stat, 4) if math.isfinite(t_stat) else None,
        "p_value": round(p_value, 8),
    }


def run(raw: pd.DataFrame, registry: dict) -> dict:
    dates, sessions = prepare(raw)
    development_end = int(len(dates) * 0.70)
    selection_end = int(len(dates) * 0.85)
    development = dates[:development_end]
    thirds = len(development) // 3
    regimes = [
        set(development[:thirds]),
        set(development[thirds:2 * thirds]),
        set(development[2 * thirds:]),
    ]
    all_results = []
    for trial in registry["trials"]:
        points_by_date: dict[str, float] = {}
        for date_idx, day in enumerate(development):
            previous = sessions.get(dates[date_idx - 1]) if date_idx > 0 else None
            signal = find_signal(sessions[day], trial, previous)
            if signal is not None:
                entry_idx, side, stop = signal
                points_by_date[day] = manage(sessions[day], entry_idx, side, stop, float(trial["reward_risk"]))
        regime_metrics = [metrics([value for day, value in points_by_date.items() if day in regime]) for regime in regimes]
        aggregate = metrics(list(points_by_date.values()))
        stress = metrics(list(points_by_date.values()), cost_multiple=2.0)
        survives = (
            all(
                row.get("trades", 0) >= 20
                and (row.get("expectancy") or 0) > 0
                and (row.get("profit_factor") or 0) > 1.0
                for row in regime_metrics
            )
            and (stress.get("expectancy") or 0) > 0
            and (aggregate.get("p_value") if aggregate.get("p_value") is not None else 1.0) <= BONFERRONI_ALPHA
        )
        all_results.append({
            **trial,
            "development_regimes": regime_metrics,
            "development": aggregate,
            "development_2x_friction": stress,
            "discovery_survivor": survives,
        })
    survivors = [row for row in all_results if row["discovery_survivor"]]
    ranked = sorted(
        all_results,
        key=lambda row: (
            row["development_2x_friction"].get("expectancy") or -math.inf,
            row["development"].get("profit_factor") or -math.inf,
        ),
        reverse=True,
    )
    return {
        "experiment": registry["experiment"],
        "registry_sha256": registry["registry_sha256"],
        "mode": "development_only_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
        "dataset_sessions": len(dates),
        "development_sessions": len(development),
        "sealed_selection_sessions": selection_end - development_end,
        "sealed_final_sessions": len(dates) - selection_end,
        "trial_count": len(all_results),
        "effective_attempt_count": EFFECTIVE_ATTEMPTS,
        "bonferroni_alpha": BONFERRONI_ALPHA,
        "survivor_count": len(survivors),
        "survivors": survivors,
        "top_20_development_only": ranked[:20],
        "trials": all_results,
        "warning": "Development rankings are hypotheses, not execution evidence. Historical slices are broadly reused and any survivor still requires forward shadow validation.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()
    registry = build_registry()
    args.registry.parent.mkdir(parents=True, exist_ok=True)
    args.registry.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    report = run(pd.read_csv(args.csv), registry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.print_summary:
        print(json.dumps({key: report[key] for key in (
            "experiment", "trial_count", "effective_attempt_count", "bonferroni_alpha", "survivor_count", "top_20_development_only",
        )}, indent=2))


if __name__ == "__main__":
    main()
