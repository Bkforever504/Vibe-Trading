#!/usr/bin/env python3
"""Preregistered swing risk-overlay comparison using cached daily bars."""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.higher_timeframe_volume_screen_lab import (
    CACHE_DIR,
    Variant,
    bootstrap,
    load_symbol,
    period_candidates,
)


SYMBOLS = ("SPY", "QQQ", "SMH", "XLK", "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD")
BASELINE = Variant("monthly_price_trend_baseline", "monthly", "none", hold_days=20)
DEV_END = "2022-12-31"
SELECTION_END = "2025-12-31"
DEFAULT_OUTPUT = ROOT / "data" / "swing_risk_overlay_results.json"


@dataclass(frozen=True)
class Overlay:
    name: str
    inverse_volatility: bool = False
    spy_regime: bool = False
    breadth_scaled: bool = False
    dual_daily_trend: bool = False
    drawdown_throttle: bool = False


OVERLAYS = (
    Overlay("equal_weight_baseline"),
    Overlay("inverse_volatility", inverse_volatility=True),
    Overlay("spy_200d_regime", spy_regime=True),
    Overlay("breadth_scaled", breadth_scaled=True),
    Overlay("dual_daily_trend", dual_daily_trend=True),
    Overlay(
        "combined_risk_overlay",
        inverse_volatility=True,
        breadth_scaled=True,
        drawdown_throttle=True,
    ),
)


def capped_inverse_vol_weights(volatilities: list[float], cap: float = 0.35) -> list[float]:
    if not volatilities or cap <= 0:
        raise ValueError("volatilities and a positive cap are required")
    inverse = np.asarray([1.0 / max(float(value), 1e-8) for value in volatilities], dtype=float)
    if cap * len(volatilities) < 1.0 - 1e-12:
        return [cap] * len(volatilities)
    weights = inverse / inverse.sum()
    free = np.ones(len(weights), dtype=bool)
    result = np.zeros(len(weights), dtype=float)
    remaining = 1.0
    while free.any():
        proposed = inverse[free] / inverse[free].sum() * remaining
        over = proposed > cap + 1e-12
        free_indices = np.flatnonzero(free)
        if not over.any():
            result[free_indices] = proposed
            break
        capped_indices = free_indices[over]
        result[capped_indices] = cap
        free[capped_indices] = False
        remaining = 1.0 - result.sum()
    return result.tolist()


def point_in_time_features(frame: pd.DataFrame, decision_pos: int) -> dict[str, float | bool]:
    history = frame.iloc[: decision_pos + 1]
    close = history["close"].astype(float)
    returns = close.pct_change().dropna()
    if len(close) < 200 or len(returns) < 20:
        return {"ready": False}
    sma50 = float(close.tail(50).mean())
    sma200 = float(close.tail(200).mean())
    vol20 = float(returns.tail(20).std(ddof=1) * math.sqrt(252))
    return {
        "ready": True,
        "close": float(close.iloc[-1]),
        "sma50": sma50,
        "sma200": sma200,
        "above_200": float(close.iloc[-1]) > sma200,
        "dual_daily_trend": float(close.iloc[-1]) > sma200 and sma50 > sma200,
        "vol20": vol20,
    }


def build_context(frames: dict[str, pd.DataFrame], decision_date: str) -> dict[str, Any]:
    stamp = pd.Timestamp(decision_date)
    features: dict[str, dict[str, Any]] = {}
    for symbol, frame in frames.items():
        eligible = frame.index[frame.index <= stamp]
        if eligible.empty:
            continue
        pos = int(frame.index.get_loc(eligible[-1]))
        features[symbol] = point_in_time_features(frame, pos)
    ready = [row for row in features.values() if row.get("ready")]
    breadth = sum(bool(row["above_200"]) for row in ready) / len(ready) if ready else 0.0
    spy = features.get("SPY", {})
    return {
        "features": features,
        "breadth": breadth,
        "spy_above_200": bool(spy.get("ready") and spy.get("above_200")),
    }


def exposure_for_overlay(overlay: Overlay, context: dict[str, Any], virtual_drawdown: float) -> float:
    exposure = 1.0
    if overlay.spy_regime and not context["spy_above_200"]:
        exposure = 0.0
    if overlay.breadth_scaled:
        breadth = float(context["breadth"])
        exposure *= 1.0 if breadth >= 0.60 else 0.5 if breadth >= 0.40 else 0.0
    if overlay.drawdown_throttle:
        exposure *= 0.0 if virtual_drawdown <= -0.15 else 0.5 if virtual_drawdown <= -0.08 else 1.0
    return exposure


def eligible_candidates(candidates: list[dict[str, Any]], overlay: Overlay, context: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [row for row in candidates if row["price_trend"] and row["period_return"] > 0]
    if overlay.dual_daily_trend:
        rows = [
            row
            for row in rows
            if context["features"].get(row["symbol"], {}).get("dual_daily_trend")
        ]
    return sorted(rows, key=lambda row: row["momentum"], reverse=True)[: BASELINE.top_n]


def gross_period_return(
    frames: dict[str, pd.DataFrame], selected: list[dict[str, Any]], overlay: Overlay
) -> tuple[float, list[str], list[float]]:
    asset_returns: list[float] = []
    volatilities: list[float] = []
    symbols: list[str] = []
    for row in selected:
        frame = frames[row["symbol"]]
        entry_pos = int(row["entry_pos"])
        exit_pos = entry_pos + BASELINE.hold_days - 1
        if exit_pos >= len(frame):
            continue
        features = point_in_time_features(frame, entry_pos - 1)
        if not features.get("ready"):
            continue
        entry = float(frame["open"].iloc[entry_pos])
        exit_price = float(frame["close"].iloc[exit_pos])
        asset_returns.append(exit_price / entry - 1.0)
        volatilities.append(float(features["vol20"]))
        symbols.append(row["symbol"])
    if not asset_returns:
        return 0.0, [], []
    weights = (
        capped_inverse_vol_weights(volatilities)
        if overlay.inverse_volatility
        else [1.0 / len(asset_returns)] * len(asset_returns)
    )
    return float(np.dot(asset_returns, weights)), symbols, weights


def replay(
    frames: dict[str, pd.DataFrame],
    candidates: list[dict[str, Any]],
    overlay: Overlay,
    *,
    cost_bps: float,
) -> list[dict[str, Any]]:
    by_date: dict[str, list[dict[str, Any]]] = {}
    for row in candidates:
        by_date.setdefault(row["decision_date"], []).append(row)

    rows: list[dict[str, Any]] = []
    virtual_equity = 1.0
    virtual_peak = 1.0
    for decision_date, date_candidates in sorted(by_date.items()):
        context = build_context(frames, decision_date)
        baseline_selected = eligible_candidates(date_candidates, OVERLAYS[0], context)
        baseline_gross, baseline_symbols, _ = gross_period_return(frames, baseline_selected, OVERLAYS[0])
        if not baseline_symbols:
            continue
        virtual_drawdown = virtual_equity / virtual_peak - 1.0
        selected = eligible_candidates(date_candidates, overlay, context)
        gross, symbols, weights = gross_period_return(frames, selected, overlay)
        exposure = exposure_for_overlay(overlay, context, virtual_drawdown)
        invested_fraction = sum(weights)
        net = (
            exposure * gross - exposure * invested_fraction * cost_bps / 10_000
            if symbols and exposure > 0
            else 0.0
        )
        rows.append(
            {
                "decision_date": decision_date,
                "return": net,
                "gross_return": exposure * gross,
                "exposure": exposure,
                "breadth": context["breadth"],
                "virtual_drawdown": virtual_drawdown,
                "symbol_count": len(symbols),
                "symbols": symbols,
                "weights": [round(value, 8) for value in weights],
                "max_weight": max(weights, default=0.0),
                "invested_fraction": invested_fraction,
            }
        )
        virtual_equity *= 1.0 + baseline_gross - (cost_bps / 10_000 if baseline_selected else 0.0)
        virtual_peak = max(virtual_peak, virtual_equity)
    return rows


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = np.asarray([float(row["return"]) for row in rows], dtype=float)
    if not len(values):
        return {"periods": 0}
    active = values[values != 0]
    equity = np.cumprod(1.0 + values)
    peak = np.maximum.accumulate(np.concatenate(([1.0], equity)))[1:]
    drawdowns = equity / peak - 1.0
    wins = active[active > 0]
    losses = active[active < 0]
    remove_count = max(1, math.ceil(len(values) * 0.01))
    trimmed = np.sort(values)[:-remove_count]
    max_dd = abs(float(drawdowns.min()))
    years = max(len(values) / 12.0, 1 / 12.0)
    ending_equity = float(equity[-1])
    cagr = ending_equity ** (1.0 / years) - 1.0 if ending_equity > 0 else -1.0
    return {
        "periods": len(values),
        "active_periods": int(len(active)),
        "ending_equity": round(ending_equity, 6),
        "total_return_pct": round((ending_equity - 1.0) * 100, 3),
        "cagr_pct": round(cagr * 100, 3),
        "expectancy_bps": round(float(values.mean()) * 10_000, 3),
        "active_win_rate": round(float((active > 0).mean()), 4) if len(active) else None,
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 3) if len(losses) else None,
        "max_drawdown_pct": round(-max_dd * 100, 3),
        "calmar": round(cagr / max_dd, 3) if max_dd else None,
        "top_one_pct_removed_expectancy_bps": round(float(trimmed.mean()) * 10_000, 3),
        "average_exposure": round(float(np.mean([row["exposure"] for row in rows])), 4),
        "maximum_position_weight": round(max((max(row["weights"], default=0.0) for row in rows), default=0.0), 4),
        "bootstrap": bootstrap(values.tolist()),
    }


def split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "development_2015_2022": metrics([row for row in rows if row["decision_date"] <= DEV_END]),
        "selection_2023_2025": metrics([row for row in rows if DEV_END < row["decision_date"] <= SELECTION_END]),
        "final_2026": metrics([row for row in rows if row["decision_date"] > SELECTION_END]),
    }


def drawdown_reduction(candidate: dict[str, Any], baseline: dict[str, Any], window: str) -> float | None:
    base = abs(float(baseline[window].get("max_drawdown_pct") or 0.0))
    current = abs(float(candidate[window].get("max_drawdown_pct") or 0.0))
    return (base - current) / base if base else None


def build_report() -> dict[str, Any]:
    frames = {symbol: load_symbol(symbol, "2015-01-01", "2026-07-21", False) for symbol in SYMBOLS}
    candidates = [row for symbol, frame in frames.items() for row in period_candidates(symbol, frame, "monthly")]
    results: list[dict[str, Any]] = []
    replay_cache: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for overlay in OVERLAYS:
        base_rows = replay(frames, candidates, overlay, cost_bps=10.0)
        stress_rows = replay(frames, candidates, overlay, cost_bps=30.0)
        replay_cache[overlay.name] = {"base": base_rows, "stress": stress_rows}
        result = {"variant": overlay.name, "rules": overlay.__dict__, **split(base_rows)}
        result["stress"] = split(stress_rows)
        results.append(result)

    baseline = results[0]
    for result in results:
        dev_reduction = drawdown_reduction(result, baseline, "development_2015_2022")
        selection_reduction = drawdown_reduction(result, baseline, "selection_2023_2025")
        result["comparison"] = {
            "development_drawdown_reduction_pct": None if dev_reduction is None else round(dev_reduction * 100, 3),
            "selection_drawdown_reduction_pct": None if selection_reduction is None else round(selection_reduction * 100, 3),
            "selection_ending_equity_uplift": round(
                float(result["selection_2023_2025"].get("ending_equity") or 0)
                - float(baseline["selection_2023_2025"].get("ending_equity") or 0),
                6,
            ),
        }
        gates = {
            "development_drawdown_reduced_20pct": dev_reduction is not None and dev_reduction >= 0.20,
            "selection_drawdown_reduced_20pct": selection_reduction is not None and selection_reduction >= 0.20,
            "selection_ending_equity_improved": result["comparison"]["selection_ending_equity_uplift"] > 0,
            "stress_positive_all_windows": all(
                (result["stress"][window].get("expectancy_bps") or 0) > 0
                for window in ("development_2015_2022", "selection_2023_2025", "final_2026")
            ),
            "positive_without_top_one_pct_all_windows": all(
                (result[window].get("top_one_pct_removed_expectancy_bps") or 0) > 0
                for window in ("development_2015_2022", "selection_2023_2025", "final_2026")
            ),
            "development_bootstrap_lower_bound_positive": (
                result["development_2015_2022"].get("bootstrap", {}).get("ci95_bps", [None])[0] or 0
            ) > 0,
            "position_cap_respected": (result["development_2015_2022"].get("maximum_position_weight") or 0) <= 0.35,
        }
        result["gates"] = {**gates, "all_pass": all(gates.values())}
        result["shadow_candidate"] = result["variant"] != "equal_weight_baseline" and all(gates.values())

    return {
        "schema_version": 1,
        "protocol": "SWING_RISK_OVERLAY_PREREGISTRATION_2026-08-13",
        "mode": "research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "symbols": list(SYMBOLS),
        "configuration_count": len(results),
        "results": results,
        "warnings": [
            "The universe has survivorship bias and cannot authorize capital.",
            "Adjusted daily bars are research marks rather than broker execution quotes.",
            "The 2026 comparison is sealed by variant but not a pristine independent holdout.",
            "No candidate may trade until forward shadow evidence passes a separate review.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        summary = [
            {
                "variant": row["variant"],
                "selection": row["selection_2023_2025"],
                "final": row["final_2026"],
                "comparison": row["comparison"],
                "shadow_candidate": row["shadow_candidate"],
            }
            for row in report["results"]
        ]
        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
