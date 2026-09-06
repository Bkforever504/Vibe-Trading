#!/usr/bin/env python3
"""Exact 3m CE-cross interpretation of the Trader Barbie screenshots.

The experiment is historical, SPY-only, and has no live ranking authority.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import time, timedelta
from pathlib import Path
from statistics import NormalDist
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "spy_1m_edge_lab.parquet"
DEFAULT_OUT = ROOT / "data" / "trader_barbie_3m_ce_results.json"
DEFAULT_REPORT = Path.home() / ".vibe-trading" / "reports" / "trader-barbie-3m-ce-lab.json"
PREREGISTRATION = "research/TRADER_BARBIE_3M_CE_PREREGISTRATION_2026-08-30.md"
LANES = ("first_ce_cross", "second_ce_recross", "second_ce_recross_strat2")
NOTIONAL = 10_000.0
BASELINE_BPS = 4.0
STRESS_BPS = 8.0
EFFECTIVE_ATTEMPTS = 992
BONFERRONI_ALPHA = 0.05 / EFFECTIVE_ATTEMPTS


def load_complete_sessions(path: Path = SOURCE) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    raw = pd.read_parquet(path)
    if isinstance(raw.index, pd.DatetimeIndex):
        raw = raw.reset_index()
    timestamp = "timestamp" if "timestamp" in raw.columns else raw.columns[0]
    raw["dt"] = pd.to_datetime(raw[timestamp], errors="raise")
    if raw["dt"].dt.tz is None:
        raw["dt"] = raw["dt"].dt.tz_localize("America/New_York")
    else:
        raw["dt"] = raw["dt"].dt.tz_convert("America/New_York")
    raw = raw[(raw["dt"].dt.time >= time(9, 30)) & (raw["dt"].dt.time < time(16, 0))].copy()
    raw["date"] = raw["dt"].dt.date.astype(str)
    all_days = raw["date"].nunique()
    eligible = raw.groupby("date")["dt"].nunique()
    complete_days = set(eligible[eligible == 390].index)
    raw = raw[raw["date"].isin(complete_days)]
    aggregations = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}

    def resample(rule: str) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for day, minute in raw.groupby("date", sort=True):
            bars = minute.set_index("dt").resample(
                rule,
                origin="start_day",
                offset="30min",
                label="left",
                closed="left",
            ).agg(aggregations).dropna().reset_index()
            bars["date"] = day
            frames.append(bars)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    return resample("15min"), resample("3min"), {
        "source_days": int(all_days),
        "complete_rth_days": len(complete_days),
        "excluded_incomplete_days": int(all_days - len(complete_days)),
        "source_start": raw["dt"].min().isoformat() if not raw.empty else None,
        "source_end": raw["dt"].max().isoformat() if not raw.empty else None,
    }


def context_events(context: pd.DataFrame) -> list[dict[str, Any]]:
    bars = context.copy()
    bars["bsl"] = bars["high"].shift(1).rolling(20, min_periods=20).max()
    bars["ssl"] = bars["low"].shift(1).rolling(20, min_periods=20).min()
    bars["ce"] = (bars["bsl"] + bars["ssl"]) / 2.0
    bull = (bars["low"] < bars["ssl"]) & (bars["close"] > bars["ssl"]) & (bars["close"] <= bars["ce"])
    bear = (bars["high"] > bars["bsl"]) & (bars["close"] < bars["bsl"]) & (bars["close"] >= bars["ce"])
    events: list[dict[str, Any]] = []
    for idx in bars.index[bull | bear]:
        row = bars.loc[idx]
        side = 1 if bool(bull.loc[idx]) else -1
        events.append({
            "context_timestamp": row["dt"],
            "context_complete_at": row["dt"] + timedelta(minutes=15),
            "date": row["date"],
            "side": side,
            "ce": float(row["ce"]),
            "stop": float(row["low"] if side > 0 else row["high"]),
        })
    return events


def _directional_cross(current: pd.Series, previous: pd.Series, ce: float, side: int) -> bool:
    return bool(
        (float(previous["close"]) <= ce and float(current["close"]) > ce)
        if side > 0
        else (float(previous["close"]) >= ce and float(current["close"]) < ce)
    )


def _failed_back(current: pd.Series, ce: float, side: int) -> bool:
    return float(current["close"]) <= ce if side > 0 else float(current["close"]) >= ce


def _strat2(current: pd.Series, previous: pd.Series, side: int) -> bool:
    if side > 0:
        return float(current["high"]) > float(previous["high"]) and float(current["low"]) >= float(previous["low"])
    return float(current["low"]) < float(previous["low"]) and float(current["high"]) <= float(previous["high"])


def signal_indices(execution: pd.DataFrame, event: dict[str, Any]) -> dict[str, int]:
    candidates = execution[
        (execution["date"] == event["date"])
        & (execution["dt"] >= event["context_complete_at"])
        & (execution["dt"] < event["context_complete_at"] + timedelta(minutes=60))
    ]
    crosses: list[int] = []
    failed_after_first = False
    for idx in candidates.index:
        if idx <= 0 or execution.loc[idx - 1, "date"] != event["date"]:
            continue
        current, previous = execution.loc[idx], execution.loc[idx - 1]
        if crosses and _failed_back(current, event["ce"], event["side"]):
            failed_after_first = True
        if _directional_cross(current, previous, event["ce"], event["side"]):
            crosses.append(idx)
            if len(crosses) == 1:
                continue
            if failed_after_first:
                return {
                    "first_ce_cross": crosses[0],
                    "second_ce_recross": idx,
                    **({"second_ce_recross_strat2": idx} if _strat2(current, previous, event["side"]) else {}),
                }
    return {"first_ce_cross": crosses[0]} if crosses else {}


def simulate(execution: pd.DataFrame, event: dict[str, Any], signal_idx: int, cost_bps: float) -> dict[str, Any] | None:
    entry_idx = signal_idx + 1
    if entry_idx >= len(execution) or execution.loc[entry_idx, "date"] != event["date"]:
        return None
    side = int(event["side"])
    entry = float(execution.loc[entry_idx, "open"])
    stop = float(event["stop"])
    risk = side * (entry - stop)
    if risk <= 0 or risk / entry > 0.02:
        return None
    target = entry + side * 2.0 * risk
    end_idx = min(entry_idx + 9, len(execution) - 1)
    same_day = execution.loc[entry_idx:end_idx]
    same_day = same_day[same_day["date"] == event["date"]]
    if same_day.empty:
        return None
    exit_price = float(same_day.iloc[-1]["close"])
    reason = "30m_time"
    for _, bar in same_day.iterrows():
        stop_hit = float(bar["low"]) <= stop if side > 0 else float(bar["high"]) >= stop
        target_hit = float(bar["high"]) >= target if side > 0 else float(bar["low"]) <= target
        if stop_hit:
            exit_price, reason = stop, "stop"
            break
        if target_hit:
            exit_price, reason = target, "target"
            break
    gross_r = side * (exit_price - entry) / risk
    cost_r = (entry * cost_bps / 10_000.0) / risk
    return {
        "timestamp": execution.loc[signal_idx, "dt"].isoformat(),
        "date": event["date"],
        "side": side,
        "entry": entry,
        "stop": stop,
        "target": target,
        "gross_r": gross_r,
        "net_r": gross_r - cost_r,
        "reason": reason,
    }


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["net_r"]) for row in rows]
    if not values:
        return {"trades": 0, "expectancy_r": None, "profit_factor": None, "win_rate": None, "one_sided_p_value": None}
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1)
    se = math.sqrt(variance / len(values)) if variance > 0 else 0.0
    z_score = mean / se if se else 0.0
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value <= 0]
    return {
        "trades": len(values),
        "expectancy_r": mean,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses and sum(losses) else None,
        "win_rate": len(wins) / len(values),
        "total_r": sum(values),
        "one_sided_p_value": 1.0 - NormalDist().cdf(z_score),
    }


def _fold_metrics(rows: list[dict[str, Any]], dates: list[str]) -> list[dict[str, Any]]:
    width = len(dates) // 3
    folds = (dates[:width], dates[width : 2 * width], dates[2 * width :])
    return [metrics([row for row in rows if row["date"] in set(fold)]) for fold in folds]


def _gates(aggregate: dict[str, Any], stress: dict[str, Any], folds: list[dict[str, Any]]) -> dict[str, bool]:
    return {
        "minimum_50_trades": aggregate["trades"] >= 50,
        "positive_expectancy": (aggregate["expectancy_r"] or 0) > 0,
        "profit_factor_above_1_10": (aggregate["profit_factor"] or 0) > 1.10,
        "positive_two_of_three_folds": sum((fold["expectancy_r"] or 0) > 0 for fold in folds) >= 2,
        "positive_double_friction": (stress["expectancy_r"] or 0) > 0,
        "cumulative_bonferroni_significant": (
            aggregate["one_sided_p_value"] is not None
            and aggregate["one_sided_p_value"] < BONFERRONI_ALPHA
        ),
        "cross_market_confirmation": False,
    }


def run(path: Path = SOURCE) -> dict[str, Any]:
    context, execution, coverage = load_complete_sessions(path)
    events = context_events(context)
    lane_rows: dict[str, list[dict[str, Any]]] = {lane: [] for lane in LANES}
    lane_stress: dict[str, list[dict[str, Any]]] = {lane: [] for lane in LANES}
    dedupe: set[tuple[str, str, int]] = set()
    for event in events:
        for lane, signal_idx in signal_indices(execution, event).items():
            key = (lane, execution.loc[signal_idx, "dt"].isoformat(), int(event["side"]))
            if key in dedupe:
                continue
            dedupe.add(key)
            base_row = simulate(execution, event, signal_idx, BASELINE_BPS)
            stress_row = simulate(execution, event, signal_idx, STRESS_BPS)
            if base_row and stress_row:
                lane_rows[lane].append(base_row)
                lane_stress[lane].append(stress_row)
    dates = sorted(execution["date"].unique())
    lanes: list[dict[str, Any]] = []
    for lane in LANES:
        aggregate = metrics(lane_rows[lane])
        stress = metrics(lane_stress[lane])
        folds = _fold_metrics(lane_rows[lane], dates)
        gates = _gates(aggregate, stress, folds)
        lanes.append({
            "lane": lane,
            "aggregate": aggregate,
            "double_friction": stress,
            "chronological_folds": folds,
            "gates": gates,
            "spy_statistical_gate_pass": all(value for key, value in gates.items() if key != "cross_market_confirmation"),
            "forward_shadow_candidate": False,
            "promotion_eligible": False,
            "rank_effect": "none",
        })
    return {
        "schema_version": 1,
        "experiment": "TRADER-BARBIE-3M-CE-2026-08-30",
        "mode": "historical_spy_research_only",
        "execution_enabled": False,
        "rank_effect": "none",
        "preregistration": PREREGISTRATION,
        "source": str(path),
        "source_resolution_minutes": 1,
        "context_timeframe_minutes": 15,
        "execution_timeframe_minutes": 3,
        "maximum_hold_minutes": 30,
        "context_event_count": len(events),
        "coverage": coverage,
        "effective_attempt_count": EFFECTIVE_ATTEMPTS,
        "bonferroni_alpha": BONFERRONI_ALPHA,
        "lanes": lanes,
        "verdict": "spy_shadow_hypothesis_only" if any(row["spy_statistical_gate_pass"] for row in lanes) else "no_spy_corrected_survivor",
        "promotion_blockers": ["qqq_1m_history_unavailable", "cross_market_confirmation_missing", "requires_new_forward_shadow_sample"],
        "warning": "Underlying SPY research only; no options-premium inference and no scanner rank, alert, sizing, or order authority.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = run(args.input)
    for path in (args.output, args.report):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps({"verdict": report["verdict"], "coverage": report["coverage"], "lanes": report["lanes"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

