#!/usr/bin/env python3
"""Tournament for data-ready concepts that lacked isolated validation."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Callable

import pandas as pd

try:
    from research import global_social_sequence_tournament as metrics_base
    from research import multi_timeframe_edge_tournament as mtf
    from research import trader_barbie_3m_ce_lab as barbie3m
except ModuleNotFoundError:
    import global_social_sequence_tournament as metrics_base
    import multi_timeframe_edge_tournament as mtf
    import trader_barbie_3m_ce_lab as barbie3m


ROOT = Path(__file__).resolve().parents[1]
PREREGISTRATION = "research/UNCOVERED_CONCEPT_TOURNAMENT_PREREGISTRATION_2026-08-30.md"
DEFAULT_OUT = ROOT / "data" / "uncovered_concept_tournament.json"
DEFAULT_REPORT = Path.home() / ".vibe-trading" / "reports" / "uncovered-concept-tournament.json"
FAMILIES = (
    "cbc_strong_flip",
    "session_liquidity_sweep_reclaim",
    "engulfing_context_gated",
    "fvg_retest_trend_proxy",
)
STANDARD_TIMEFRAMES = (5, 15)
EXPLORATORY_TIMEFRAMES = (3,)
MARKETS = ("SPY", "QQQ")
PATHS = mtf.PATHS
BASELINE_COST = mtf.BASELINE_COST
PRIOR_EFFECTIVE_ATTEMPTS = 992
NEW_ATTEMPTS = len(FAMILIES) * (len(MARKETS) * len(STANDARD_TIMEFRAMES) + len(EXPLORATORY_TIMEFRAMES))
EFFECTIVE_ATTEMPTS = PRIOR_EFFECTIVE_ATTEMPTS + NEW_ATTEMPTS
BONFERRONI_ALPHA = 0.05 / EFFECTIVE_ATTEMPTS


def _cbc(bars: pd.DataFrame, previous: pd.DataFrame | None) -> tuple[int, int, float] | None:
    for idx in range(1, len(bars) - 1):
        prior, row = bars.iloc[idx - 1], bars.iloc[idx]
        if not (float(row["high"]) > float(prior["high"]) and float(row["low"]) < float(prior["low"])):
            continue
        if float(row["close"]) > float(prior["high"]):
            return idx, 1, float(row["low"])
        if float(row["close"]) < float(prior["low"]):
            return idx, -1, float(row["high"])
    return None


def _session_sweep(bars: pd.DataFrame, previous: pd.DataFrame | None) -> tuple[int, int, float] | None:
    if previous is None:
        return None
    timeframe = int((bars.iloc[1]["dt"] - bars.iloc[0]["dt"]).total_seconds() // 60)
    opening_count = max(1, math.ceil(30 / timeframe))
    opening = bars.iloc[:opening_count]
    levels = {
        "high": (float(previous["high"].max()), float(opening["high"].max())),
        "low": (float(previous["low"].min()), float(opening["low"].min())),
    }
    for idx in range(opening_count, len(bars) - 1):
        row = bars.iloc[idx]
        bearish = any(float(row["high"]) > level and float(row["close"]) < level for level in levels["high"])
        bullish = any(float(row["low"]) < level and float(row["close"]) > level for level in levels["low"])
        if bearish == bullish:
            continue
        return (idx, -1, float(row["high"])) if bearish else (idx, 1, float(row["low"]))
    return None


def _engulfing(bars: pd.DataFrame, previous: pd.DataFrame | None) -> tuple[int, int, float] | None:
    prior_volume_mean = bars["volume"].shift(1).rolling(20, min_periods=20).mean()
    for idx in range(20, len(bars) - 2):
        before, row, confirm = bars.iloc[idx - 1], bars.iloc[idx], bars.iloc[idx + 1]
        trend = float(before["close"]) - float(bars.iloc[idx - 5]["close"])
        volume_ok = float(row["volume"]) >= 1.2 * float(prior_volume_mean.iloc[idx])
        bull_body = float(row["open"]) <= float(before["close"]) and float(row["close"]) >= float(before["open"]) and float(row["close"]) > float(row["open"])
        bear_body = float(row["open"]) >= float(before["close"]) and float(row["close"]) <= float(before["open"]) and float(row["close"]) < float(row["open"])
        if volume_ok and trend < 0 and bull_body and float(confirm["close"]) > float(row["high"]):
            return idx + 1, 1, float(row["low"])
        if volume_ok and trend > 0 and bear_body and float(confirm["close"]) < float(row["low"]):
            return idx + 1, -1, float(row["high"])
    return None


def _fvg_proxy(bars: pd.DataFrame, previous: pd.DataFrame | None) -> tuple[int, int, float] | None:
    for idx in range(2, len(bars) - 2):
        old, row = bars.iloc[idx - 2], bars.iloc[idx]
        atr = float(row.get("atr6", math.nan))
        if not math.isfinite(atr) or atr <= 0:
            continue
        body = abs(float(row["close"]) - float(row["open"]))
        bull = float(row["low"]) > float(old["high"]) and body >= 0.7 * atr and float(row["ema8"]) > float(row["ema21"])
        bear = float(row["high"]) < float(old["low"]) and body >= 0.7 * atr and float(row["ema8"]) < float(row["ema21"])
        if not bull and not bear:
            continue
        side = 1 if bull else -1
        near = float(old["high"]) if bull else float(row["high"])
        far = float(row["low"]) if bull else float(old["low"])
        midpoint = (near + far) / 2.0
        stop = near if bull else far
        for retest in range(idx + 1, min(len(bars) - 1, idx + 7)):
            candidate = bars.iloc[retest]
            touched = float(candidate["low"]) <= midpoint if bull else float(candidate["high"]) >= midpoint
            held = float(candidate["close"]) > midpoint if bull else float(candidate["close"]) < midpoint
            if touched and held:
                return retest, side, stop
    return None


DETECTORS: dict[str, Callable[[pd.DataFrame, pd.DataFrame | None], tuple[int, int, float] | None]] = {
    "cbc_strong_flip": _cbc,
    "session_liquidity_sweep_reclaim": _session_sweep,
    "engulfing_context_gated": _engulfing,
    "fvg_retest_trend_proxy": _fvg_proxy,
}


def _spy_3m_sessions() -> tuple[list[str], dict[str, pd.DataFrame]]:
    _, execution, _ = barbie3m.load_complete_sessions()
    sessions: dict[str, pd.DataFrame] = {}
    for day, bars in execution.groupby("date", sort=True):
        prepared = metrics_base._features(bars.reset_index(drop=True))
        prepared["time"] = prepared["dt"].dt.strftime("%H:%M")
        sessions[str(day)] = prepared
    return sorted(sessions), sessions


def _folds(dates: list[str]) -> list[list[str]]:
    width = len(dates) // 3
    return [dates[:width], dates[width : 2 * width], dates[2 * width :]]


def _passes(aggregate: dict[str, Any], stress: dict[str, Any], folds: list[dict[str, Any]]) -> bool:
    return bool(
        aggregate.get("trades", 0) >= 60
        and (aggregate.get("expectancy") or 0) > 0
        and (aggregate.get("profit_factor") or 0) > 1.10
        and (stress.get("expectancy") or 0) > 0
        and sum((fold.get("expectancy") or 0) > 0 for fold in folds) >= 2
        and (aggregate.get("p_value") if aggregate.get("p_value") is not None else 1.0) < BONFERRONI_ALPHA
    )


def evaluate(market: str, timeframe: int, dates: list[str], sessions: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    positions = {day: idx for idx, day in enumerate(dates)}
    fold_dates = _folds(dates)
    output: list[dict[str, Any]] = []
    for family, detector in DETECTORS.items():
        realized: list[tuple[str, float]] = []
        for day in dates:
            pos = positions[day]
            previous = sessions[dates[pos - 1]] if pos > 0 else None
            signal = detector(sessions[day], previous)
            if signal is None:
                continue
            gross = mtf.simulate_fixed_horizon(sessions[day], signal, timeframe)
            if gross is not None:
                realized.append((day, gross))
        aggregate = metrics_base._metrics([value for _, value in realized], BASELINE_COST)
        stress = metrics_base._metrics([value for _, value in realized], BASELINE_COST * 2)
        folds = [metrics_base._metrics([value for day, value in realized if day in set(period)], BASELINE_COST) for period in fold_dates]
        output.append({
            "trial_id": f"UCT-{market}-{timeframe}m-{family}",
            "market": market,
            "timeframe_minutes": timeframe,
            "family": family,
            "sessions": len(dates),
            "aggregate": aggregate,
            "double_friction": stress,
            "chronological_folds": folds,
            "market_gate_pass": _passes(aggregate, stress, folds),
            "selection_contaminated": True,
            "promotion_eligible": False,
            "rank_effect": "none",
        })
    return output


def run() -> dict[str, Any]:
    trials: list[dict[str, Any]] = []
    for market in MARKETS:
        for timeframe in STANDARD_TIMEFRAMES:
            dates, sessions = mtf.load_sessions(PATHS[market], timeframe)
            trials.extend(evaluate(market, timeframe, dates, sessions))
    dates3, sessions3 = _spy_3m_sessions()
    trials.extend(evaluate("SPY", 3, dates3, sessions3))
    passed = {(row["family"], row["timeframe_minutes"], row["market"]) for row in trials if row["market_gate_pass"]}
    robust = sorted({
        (family, timeframe)
        for family in FAMILIES
        for timeframe in STANDARD_TIMEFRAMES
        if (family, timeframe, "SPY") in passed and (family, timeframe, "QQQ") in passed
    })
    for row in trials:
        row["cross_market_robust"] = (row["family"], row["timeframe_minutes"]) in robust
        row["forward_shadow_candidate"] = row["cross_market_robust"]
    ranked = sorted(trials, key=lambda row: (
        row["cross_market_robust"],
        row["market_gate_pass"],
        row["aggregate"].get("expectancy") if row["aggregate"].get("expectancy") is not None else -math.inf,
    ), reverse=True)
    return {
        "schema_version": 1,
        "experiment": "UNCOVERED-CONCEPTS-2026-08-30",
        "mode": "historical_research_only",
        "execution_enabled": False,
        "rank_effect": "none",
        "preregistration": PREREGISTRATION,
        "families": list(FAMILIES),
        "standard_timeframes_minutes": list(STANDARD_TIMEFRAMES),
        "exploratory_timeframes_minutes": list(EXPLORATORY_TIMEFRAMES),
        "new_attempt_count": NEW_ATTEMPTS,
        "effective_attempt_count": EFFECTIVE_ATTEMPTS,
        "bonferroni_alpha": BONFERRONI_ALPHA,
        "cross_market_robust_pairs": [{"family": family, "timeframe_minutes": timeframe} for family, timeframe in robust],
        "forward_shadow_candidate_count": len(robust),
        "top_research_results": ranked[:12],
        "trials": trials,
        "verdict": "forward_shadow_candidates_found" if robust else "no_cross_market_corrected_survivor",
        "warning": "Historical underlying research only. No options-return, scanner-rank, alert, sizing, or execution authority.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = run()
    for path in (args.output, args.report):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps({
            "verdict": report["verdict"],
            "forward_shadow_candidate_count": report["forward_shadow_candidate_count"],
            "cross_market_robust_pairs": report["cross_market_robust_pairs"],
            "top_research_results": report["top_research_results"],
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

