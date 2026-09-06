#!/usr/bin/env python3
"""Controlled multi-timeframe tournament for previously 5m-only families.

Historical results are research-only and can nominate forward-shadow candidates.
They never change scanner ranks, alerts, sizing, or execution state.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import time
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from research import global_social_sequence_tournament as base
except ModuleNotFoundError:
    import global_social_sequence_tournament as base


ROOT = Path(__file__).resolve().parents[1]
PREREGISTRATION = "research/MULTI_TIMEFRAME_EDGE_TOURNAMENT_PREREGISTRATION_2026-08-30.md"
INVENTORY = "research/multi_timeframe_strategy_inventory_2026-08-30.json"
DEFAULT_OUT = ROOT / "data" / "multi_timeframe_edge_tournament.json"
DEFAULT_REPORT = Path.home() / ".vibe-trading" / "reports" / "multi-timeframe-edge-tournament.json"
DEFAULT_SHADOW = ROOT / "data" / "multi_timeframe_forward_shadow_candidates.json"
PATHS = {
    "SPY": ROOT / "data" / "liquid_edge_lab" / "spy_5m.parquet",
    "QQQ": ROOT / "data" / "liquid_edge_lab" / "qqq_5m.parquet",
}
FAMILIES = tuple(base.INTRADAY_FAMILIES)
TIMEFRAMES = (5, 10, 15, 30, 60)
REWARD_RISK = 2.0
MAX_HOLD_MINUTES = 60
NOTIONAL = 10_000.0
BASELINE_COST = NOTIONAL * 0.0004
PRIOR_EFFECTIVE_ATTEMPTS = 909
NEW_ATTEMPTS = len(PATHS) * len(FAMILIES) * len(TIMEFRAMES)
EFFECTIVE_ATTEMPTS = PRIOR_EFFECTIVE_ATTEMPTS + NEW_ATTEMPTS
BONFERRONI_ALPHA = 0.05 / EFFECTIVE_ATTEMPTS


def _raw_rth(path: Path) -> pd.DataFrame:
    raw = pd.read_parquet(path)
    if isinstance(raw.index, pd.DatetimeIndex):
        raw = raw.reset_index()
    timestamp = "timestamp" if "timestamp" in raw.columns else raw.columns[0]
    raw["dt"] = pd.to_datetime(raw[timestamp], errors="raise")
    if raw["dt"].dt.tz is not None:
        raw["dt"] = raw["dt"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    raw = raw[(raw["dt"].dt.time >= time(9, 30)) & (raw["dt"].dt.time < time(16, 0))].copy()
    raw["date"] = raw["dt"].dt.date.astype(str)
    return raw


def load_sessions(path: Path, timeframe_minutes: int) -> tuple[list[str], dict[str, pd.DataFrame]]:
    """Load complete RTH sessions and causally resample from the 5m source."""
    raw = _raw_rth(path)
    sessions: dict[str, pd.DataFrame] = {}
    rule = f"{timeframe_minutes}min"
    for day, minute in raw.groupby("date", sort=True):
        # The source is nominally 5m. Requiring 78 distinct RTH buckets prevents
        # a partial day from masquerading as a valid higher-timeframe session.
        source = minute.set_index("dt").resample(
            "5min", origin="start_day", offset="30min", label="left", closed="left"
        ).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
        if len(source) < 78 or source.index[0].time() != time(9, 30) or source.index[-1].time() < time(15, 55):
            continue
        bars = source.resample(
            rule, origin="start_day", offset="30min", label="left", closed="left"
        ).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index()
        bars["time"] = bars["dt"].dt.strftime("%H:%M")
        sessions[day] = base._features(bars.reset_index(drop=True))
    return sorted(sessions), sessions


def simulate_fixed_horizon(
    bars: pd.DataFrame,
    signal: tuple[int, int, float],
    timeframe_minutes: int,
) -> float | None:
    signal_idx, side, stop = signal
    entry_idx = signal_idx + 1
    if entry_idx >= len(bars) or str(bars.iloc[entry_idx]["time"]) > "14:30":
        return None
    entry = float(bars.iloc[entry_idx]["open"])
    risk = side * (entry - float(stop))
    if risk < 0.02 or risk / entry > 0.02:
        return None
    target = entry + side * risk * REWARD_RISK
    hold_bars = max(1, math.ceil(MAX_HOLD_MINUTES / timeframe_minutes))
    end_idx = min(len(bars) - 1, entry_idx + hold_bars - 1)
    exit_price = float(bars.iloc[end_idx]["close"])
    for _, row in bars.iloc[entry_idx : end_idx + 1].iterrows():
        stop_hit = float(row["low"]) <= stop if side > 0 else float(row["high"]) >= stop
        target_hit = float(row["high"]) >= target if side > 0 else float(row["low"]) <= target
        if stop_hit:  # conservative same-bar ambiguity policy
            exit_price = float(stop)
            break
        if target_hit:
            exit_price = target
            break
    return side * (exit_price - entry) * (NOTIONAL / entry)


def _folds(dates: list[str]) -> list[list[str]]:
    width = len(dates) // 3
    return [dates[:width], dates[width : 2 * width], dates[2 * width :]]


def _passes(metrics: dict[str, Any], stress: dict[str, Any], folds: list[dict[str, Any]]) -> bool:
    positive_folds = sum((row.get("expectancy") or 0) > 0 for row in folds)
    return bool(
        metrics.get("trades", 0) >= 60
        and (metrics.get("expectancy") or 0) > 0
        and (metrics.get("profit_factor") or 0) > 1.10
        and (stress.get("expectancy") or 0) > 0
        and positive_folds >= 2
        and (metrics.get("p_value") if metrics.get("p_value") is not None else 1.0) < BONFERRONI_ALPHA
    )


def evaluate_market(market: str, path: Path, timeframe_minutes: int) -> list[dict[str, Any]]:
    dates, sessions = load_sessions(path, timeframe_minutes)
    date_position = {day: index for index, day in enumerate(dates)}
    fold_dates = _folds(dates)
    results: list[dict[str, Any]] = []
    for family in FAMILIES:
        realized: list[tuple[str, float]] = []
        for day in dates:
            pos = date_position[day]
            previous = sessions[dates[pos - 1]] if pos > 0 else None
            signal = base.DETECTORS[family](sessions[day], previous)
            if signal is None:
                continue
            gross = simulate_fixed_horizon(sessions[day], signal, timeframe_minutes)
            if gross is not None:
                realized.append((day, gross))
        metrics = base._metrics([value for _, value in realized], BASELINE_COST)
        stress = base._metrics([value for _, value in realized], BASELINE_COST * 2)
        fold_metrics = [
            base._metrics([value for day, value in realized if day in set(fold)], BASELINE_COST)
            for fold in fold_dates
        ]
        results.append({
            "trial_id": f"MTF-{market}-{family}-{timeframe_minutes}m",
            "market": market,
            "family": family,
            "timeframe_minutes": timeframe_minutes,
            "sessions": len(dates),
            "metrics": metrics,
            "double_friction": stress,
            "chronological_folds": fold_metrics,
            "market_gate_pass": _passes(metrics, stress, fold_metrics),
            "selection_contaminated": True,
            "promotion_eligible": False,
            "rank_effect": "none",
        })
    return results


def run_tournament() -> dict[str, Any]:
    trials: list[dict[str, Any]] = []
    for market, path in PATHS.items():
        for timeframe in TIMEFRAMES:
            trials.extend(evaluate_market(market, path, timeframe))
    pass_pairs = {(row["family"], row["timeframe_minutes"], row["market"]) for row in trials if row["market_gate_pass"]}
    robust_pairs = sorted({
        (family, timeframe)
        for family in FAMILIES
        for timeframe in TIMEFRAMES
        if (family, timeframe, "SPY") in pass_pairs and (family, timeframe, "QQQ") in pass_pairs
    })
    for row in trials:
        row["cross_market_robust"] = (row["family"], row["timeframe_minutes"]) in robust_pairs
        row["forward_shadow_candidate"] = row["cross_market_robust"]
    ranked = sorted(
        trials,
        key=lambda row: (
            row["cross_market_robust"],
            row["market_gate_pass"],
            row["metrics"].get("expectancy") if row["metrics"].get("expectancy") is not None else -math.inf,
        ),
        reverse=True,
    )
    return {
        "schema_version": 1,
        "experiment": "MULTI-TIMEFRAME-EDGE-2026-08-30",
        "mode": "historical_research_only",
        "execution_enabled": False,
        "rank_effect": "none",
        "preregistration": PREREGISTRATION,
        "inventory": INVENTORY,
        "markets": list(PATHS),
        "families": list(FAMILIES),
        "timeframes_minutes": list(TIMEFRAMES),
        "new_attempt_count": NEW_ATTEMPTS,
        "effective_attempt_count": EFFECTIVE_ATTEMPTS,
        "bonferroni_alpha": BONFERRONI_ALPHA,
        "cross_market_robust_pairs": [
            {"family": family, "timeframe_minutes": timeframe} for family, timeframe in robust_pairs
        ],
        "forward_shadow_candidate_count": len(robust_pairs),
        "top_20_research_results": ranked[:20],
        "trials": trials,
        "verdict": "forward_shadow_candidates_found" if robust_pairs else "no_cross_market_corrected_survivor",
        "warning": "Historical selection-contaminated research only. No scanner-rank, alert, sizing, options-profit, or order authority.",
    }


def shadow_payload(report: dict[str, Any]) -> dict[str, Any]:
    candidates = report.get("cross_market_robust_pairs", [])
    return {
        "schema_version": 1,
        "mode": "forward_shadow_only",
        "execution_enabled": False,
        "rank_effect": "none",
        "source_experiment": report.get("experiment"),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "promotion_requirements": {
            "minimum_completed_forward_trades": 50,
            "minimum_trading_days": 10,
            "minimum_out_of_sample_trades": 15,
            "requires_manual_review": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--shadow", type=Path, default=DEFAULT_SHADOW)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = run_tournament()
    for path, payload in ((args.output, report), (args.report, report), (args.shadow, shadow_payload(report))):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps({
            "verdict": report["verdict"],
            "forward_shadow_candidate_count": report["forward_shadow_candidate_count"],
            "cross_market_robust_pairs": report["cross_market_robust_pairs"],
            "top_20_research_results": report["top_20_research_results"],
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

