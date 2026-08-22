#!/usr/bin/env python3
"""Preregistered development-only QQQ mean-reversion challenger lab."""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "htf_volume_screen_lab" / "qqq_2015-01-01_2026-07-21.parquet"
DEFAULT_OUTPUT = ROOT / "data" / "qqq_mean_reversion_challenger_results.json"
SPEC = "research/QQQ_MEAN_REVERSION_CHALLENGER_SPEC_2026-08-19.md"
DEVELOPMENT_END = "2023-01-26"
SEALED_SELECTION_START = "2023-01-27"
SEALED_FINAL_START = "2024-10-21"
NOTIONAL = 10_000.0
BASE_COST = NOTIONAL * 0.0004
STRESS_COST = NOTIONAL * 0.0008
PRIOR_EFFECTIVE_ATTEMPTS = 909


@dataclass(frozen=True)
class Variant:
    name: str
    family: str
    rising_sma200: bool = False
    gap_guard_atr: float | None = None
    volatility_scaled: bool = False
    exit_mode: str | None = None
    turn_of_month_only: bool = False
    hybrid: bool = False


VARIANTS = (
    Variant("double7_baseline", "double7"),
    Variant("double7_sma200_rising20", "double7", rising_sma200=True),
    Variant("double7_gap_guard_1atr", "double7", gap_guard_atr=1.0),
    Variant("double7_vol_scaled", "double7", volatility_scaled=True),
    Variant("double7_exit_sma5", "double7", exit_mode="sma5"),
    Variant("double7_turn_of_month", "double7", turn_of_month_only=True),
    Variant("rsi2_baseline", "rsi2"),
    Variant("rsi2_sma200_rising20", "rsi2", rising_sma200=True),
    Variant("rsi2_gap_guard_1atr", "rsi2", gap_guard_atr=1.0),
    Variant("rsi2_vol_scaled", "rsi2", volatility_scaled=True),
    Variant("rsi2_exit_prior_high", "rsi2", exit_mode="prior_high"),
    Variant("double7_rsi2_hybrid", "hybrid", hybrid=True),
)
EFFECTIVE_ATTEMPTS = PRIOR_EFFECTIVE_ATTEMPTS + len(VARIANTS)
BONFERRONI_ALPHA = 0.05 / EFFECTIVE_ATTEMPTS


def rsi(close: pd.Series, period: int = 2) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    relative = gain / loss.replace(0, math.nan)
    return 100.0 - 100.0 / (1.0 + relative)


def true_range(frame: pd.DataFrame) -> pd.Series:
    prior = frame["close"].shift(1)
    return pd.concat(
        [frame["high"] - frame["low"], (frame["high"] - prior).abs(), (frame["low"] - prior).abs()],
        axis=1,
    ).max(axis=1)


def prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    bars = frame.copy().sort_index()
    bars.columns = [str(column).lower() for column in bars.columns]
    close = bars["close"]
    returns = close.pct_change()
    bars["rsi2"] = rsi(close)
    bars["sma5"] = close.rolling(5).mean()
    bars["sma200"] = close.rolling(200).mean()
    bars["sma200_rising20"] = bars["sma200"] > bars["sma200"].shift(20)
    bars["low7"] = close.rolling(7).min()
    bars["high7"] = close.rolling(7).max()
    bars["atr20"] = true_range(bars).rolling(20).mean()
    bars["vol20"] = returns.rolling(20).std(ddof=1) * math.sqrt(252)
    bars["drawdown20"] = close / close.rolling(20).max() - 1.0
    bars["prior_high"] = bars["high"].shift(1)
    return bars


def _turn_of_month(index: pd.DatetimeIndex) -> pd.Series:
    positions = pd.Series(False, index=index)
    periods = index.to_period("M")
    for period in periods.unique():
        locations = np.flatnonzero(periods == period)
        if len(locations):
            chosen = list(locations[:3]) + list(locations[-4:])
            positions.iloc[chosen] = True
    return positions


def signal_columns(frame: pd.DataFrame, variant: Variant) -> tuple[pd.Series, pd.Series]:
    close = frame["close"]
    trend = close > frame["sma200"]
    double7_entry = trend & (close <= frame["low7"])
    rsi2_entry = trend & (frame["rsi2"] < 10)
    if variant.hybrid:
        enter = double7_entry & rsi2_entry
        exit_signal = (close >= frame["high7"]) | (frame["rsi2"] > 70)
    elif variant.family == "double7":
        enter = double7_entry
        exit_signal = close > frame["sma5"] if variant.exit_mode == "sma5" else close >= frame["high7"]
    elif variant.family == "rsi2":
        enter = rsi2_entry
        exit_signal = close > frame["prior_high"] if variant.exit_mode == "prior_high" else frame["rsi2"] > 70
    else:
        raise ValueError(f"unknown family: {variant.family}")
    if variant.rising_sma200:
        enter &= frame["sma200_rising20"]
    if variant.turn_of_month_only:
        enter &= _turn_of_month(pd.DatetimeIndex(frame.index))
    return enter.fillna(False), exit_signal.fillna(False)


def _exposure(frame: pd.DataFrame, signal_pos: int, variant: Variant) -> float:
    if not variant.volatility_scaled:
        return 1.0
    vol = float(frame["vol20"].iloc[signal_pos])
    if not math.isfinite(vol) or vol <= 0:
        return 0.35
    return min(1.0, max(0.35, 0.15 / vol))


def _gap_allowed(frame: pd.DataFrame, signal_pos: int, entry_pos: int, variant: Variant) -> bool:
    if variant.gap_guard_atr is None:
        return True
    atr = float(frame["atr20"].iloc[signal_pos])
    if not math.isfinite(atr) or atr <= 0:
        return False
    gap_atr = (float(frame["open"].iloc[entry_pos]) - float(frame["close"].iloc[signal_pos])) / atr
    return gap_atr >= -variant.gap_guard_atr


def simulate(frame: pd.DataFrame, variant: Variant) -> list[dict[str, Any]]:
    enter, exit_signal = signal_columns(frame, variant)
    turn_of_month = _turn_of_month(pd.DatetimeIndex(frame.index))
    trades: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    for pos in range(201, len(frame)):
        signal_pos = pos - 1
        if position is None and bool(enter.iloc[signal_pos]):
            if not _gap_allowed(frame, signal_pos, pos, variant):
                continue
            entry = float(frame["open"].iloc[pos])
            atr = float(frame["atr20"].iloc[signal_pos])
            position = {
                "entry_pos": pos,
                "entry_date": frame.index[pos].date().isoformat(),
                "entry": entry,
                "exposure": _exposure(frame, signal_pos, variant),
                "gap_atr": (entry - float(frame["close"].iloc[signal_pos])) / atr if atr > 0 else None,
                "vol20": float(frame["vol20"].iloc[signal_pos]),
                "sma200_slope20": float(frame["sma200"].iloc[signal_pos] / frame["sma200"].iloc[signal_pos - 20] - 1.0),
                "drawdown20": float(frame["drawdown20"].iloc[signal_pos]),
                "weekday": frame.index[pos].day_name(),
                "turn_of_month": bool(turn_of_month.iloc[signal_pos]),
                "minimum_low": float(frame["low"].iloc[pos]),
                "maximum_high": float(frame["high"].iloc[pos]),
            }
            continue
        if position is None:
            continue
        position["minimum_low"] = min(position["minimum_low"], float(frame["low"].iloc[pos]))
        position["maximum_high"] = max(position["maximum_high"], float(frame["high"].iloc[pos]))
        if not bool(exit_signal.iloc[signal_pos]):
            continue
        exit_price = float(frame["open"].iloc[pos])
        exposure = float(position["exposure"])
        gross = NOTIONAL * exposure * (exit_price / float(position["entry"]) - 1.0)
        trades.append({
            **position,
            "exit_date": frame.index[pos].date().isoformat(),
            "exit": exit_price,
            "gross_pnl": gross,
            "holding_sessions": pos - int(position["entry_pos"]) + 1,
            "mae_pct": float(position["minimum_low"] / position["entry"] - 1.0),
            "mfe_pct": float(position["maximum_high"] / position["entry"] - 1.0),
        })
        position = None
    return trades


def moving_block_bootstrap(values: list[float], samples: int = 4000, block: int = 5) -> dict[str, Any]:
    if len(values) < 10:
        return {"samples": samples, "block": block, "ci95": [None, None]}
    array = np.asarray(values, dtype=float)
    rng = np.random.default_rng(20260819)
    means = np.empty(samples, dtype=float)
    for sample in range(samples):
        drawn: list[float] = []
        while len(drawn) < len(array):
            start = int(rng.integers(0, len(array)))
            drawn.extend(array[(start + offset) % len(array)] for offset in range(block))
        means[sample] = float(np.mean(drawn[: len(array)]))
    low, high = np.quantile(means, [0.025, 0.975])
    return {"samples": samples, "block": block, "ci95": [round(float(low), 4), round(float(high), 4)]}


def metrics(trades: list[dict[str, Any]], cost: float) -> dict[str, Any]:
    values = [float(trade["gross_pnl"]) - cost * float(trade["exposure"]) for trade in trades]
    if not values:
        return {"trades": 0, "expectancy": None, "profit_factor": None, "p_value": None}
    array = np.asarray(values, dtype=float)
    mean = float(array.mean())
    std = float(array.std(ddof=1)) if len(array) > 1 else 0.0
    t_stat = mean / (std / math.sqrt(len(array))) if std > 0 else (math.inf if mean > 0 else 0.0)
    p_value = 1.0 - NormalDist().cdf(t_stat) if math.isfinite(t_stat) else 0.0
    wins, losses = array[array > 0], array[array <= 0]
    equity = pd.Series([0.0, *array.tolist()]).cumsum()
    remove = max(1, math.ceil(len(array) * 0.01))
    without_best = np.sort(array)[:-remove]
    return {
        "trades": len(array),
        "total_pnl": round(float(array.sum()), 2),
        "expectancy": round(mean, 4),
        "win_rate": round(float((array > 0).mean()), 4),
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 4) if len(losses) else None,
        "max_drawdown": round(float((equity.cummax() - equity).max()), 2),
        "p_value": round(p_value, 8),
        "top_one_pct_removed_expectancy": round(float(without_best.mean()), 4) if len(without_best) else None,
        "average_holding_sessions": round(float(np.mean([trade["holding_sessions"] for trade in trades])), 3),
        "average_mae_pct": round(float(np.mean([trade["mae_pct"] for trade in trades])) * 100, 3),
        "worst_mae_pct": round(float(min(trade["mae_pct"] for trade in trades)) * 100, 3),
        "average_mfe_pct": round(float(np.mean([trade["mfe_pct"] for trade in trades])) * 100, 3),
        "bootstrap": moving_block_bootstrap(values),
    }


def chronological_regimes(trades: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    width = len(trades) // 3
    return [trades[:width], trades[width : 2 * width], trades[2 * width :]]


def conditional_attribution(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {}
    rows = pd.DataFrame(trades)
    rows["net"] = rows["gross_pnl"] - BASE_COST * rows["exposure"]
    rows["vol_bucket"] = pd.qcut(rows["vol20"], 3, labels=["low", "middle", "high"], duplicates="drop")
    rows["drawdown_bucket"] = pd.cut(rows["drawdown20"], [-math.inf, -0.05, -0.025, math.inf], labels=["deep", "medium", "shallow"])
    groups: dict[str, Any] = {}
    for column in ("vol_bucket", "drawdown_bucket", "weekday", "turn_of_month"):
        groups[column] = {
            str(key): {"trades": len(group), "expectancy": round(float(group["net"].mean()), 4)}
            for key, group in rows.groupby(column, observed=True)
        }
    return groups


def build_report(data_path: Path = DATA_PATH) -> dict[str, Any]:
    full = pd.read_parquet(data_path).sort_index()
    full.index = pd.to_datetime(full.index)
    # Read only the frozen development segment. The sealed rows never reach the simulator.
    frame = prepare_frame(full.loc[:DEVELOPMENT_END])
    results: list[dict[str, Any]] = []
    for variant in VARIANTS:
        trades = simulate(frame, variant)
        aggregate = metrics(trades, BASE_COST)
        stress = metrics(trades, STRESS_COST)
        regimes = [metrics(rows, BASE_COST) for rows in chronological_regimes(trades)]
        gates = {
            "twenty_trades_each_regime": all(row.get("trades", 0) >= 20 for row in regimes),
            "positive_each_regime": all((row.get("expectancy") or 0) > 0 and (row.get("profit_factor") or 0) > 1 for row in regimes),
            "positive_at_2x_friction": (stress.get("expectancy") or 0) > 0,
            "positive_without_best_one_pct": (aggregate.get("top_one_pct_removed_expectancy") or 0) > 0,
            "bootstrap_lower_bound_positive": (aggregate.get("bootstrap", {}).get("ci95", [None])[0] or 0) > 0,
            "multiple_test_corrected": (aggregate.get("p_value") if aggregate.get("p_value") is not None else 1) < BONFERRONI_ALPHA,
        }
        results.append({
            "variant": variant.name,
            "rules": asdict(variant),
            "development": aggregate,
            "development_2x_friction": stress,
            "development_regimes": regimes,
            "diagnostic_attribution": conditional_attribution(trades),
            "gates": {**gates, "all_pass": all(gates.values())},
        })
    ranked = sorted(results, key=lambda row: row["development"].get("expectancy") or -math.inf, reverse=True)
    return {
        "schema_version": 1,
        "experiment": "QQQ-MEAN-REVERSION-CHALLENGER-2026-08-19",
        "specification": SPEC,
        "mode": "development_only_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "development_end": DEVELOPMENT_END,
        "sealed_holdouts": {
            "selection": {"start": SEALED_SELECTION_START, "opened": False},
            "final": {"start": SEALED_FINAL_START, "opened": False},
        },
        "trial_count": len(VARIANTS),
        "prior_effective_attempts": PRIOR_EFFECTIVE_ATTEMPTS,
        "effective_attempt_count": EFFECTIVE_ATTEMPTS,
        "bonferroni_alpha": BONFERRONI_ALPHA,
        "survivors": [row["variant"] for row in results if row["gates"]["all_pass"]],
        "ranked": ranked,
        "results": results,
        "warning": "Exploratory attribution cannot promote a rule. Forward shadow evidence and explicit approval remain mandatory.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(args.data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps({
            "survivors": report["survivors"],
            "ranked": [{"variant": row["variant"], **row["development"], "gates": row["gates"]} for row in report["ranked"]],
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
