#!/usr/bin/env python3
"""Development-only 100-trial MES strategy tournament. No broker imports."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import NormalDist

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "examples" / "mes_v0_1m_2022-01-01_2026-07-19_rth.csv"
REGISTRY = ROOT / "research" / "edge_trials" / "profitability_discovery_100_registry_2026-08-04.json"
OUT = ROOT / "data" / "profitability_discovery_100_results.json"
LEDGER_IMPORT = ROOT / "research" / "edge_trials" / "profitability_discovery_100_ledger_import_2026-08-04.json"
PREREG = "research/PROFITABILITY_DISCOVERY_100_PREREGISTRATION_2026-08-04.md"

TICK = 0.25
POINT_VALUE = 5.0
COST_SIDE = 1.24 + TICK * POINT_VALUE
ENTRY_START = "09:45"
ENTRY_END = "14:30"
FLATTEN = "15:55"
MAX_HOLD_BARS = 12
EXISTING_ATTEMPTS = 415
NEW_ATTEMPTS = 100
EFFECTIVE_ATTEMPTS = EXISTING_ATTEMPTS + NEW_ATTEMPTS
BONFERRONI_ALPHA = 0.05 / EFFECTIVE_ATTEMPTS

FAMILY_LEVELS = {
    "orb_breakout": [0, 1, 2, 4, 6],
    "orb_failed_break": [1, 2, 4, 6, 8],
    "prior_day_breakout": [0, 1, 2, 4, 6],
    "prior_day_reclaim": [1, 2, 4, 6, 8],
    "vwap_trend_pullback": [0.00, 0.10, 0.20, 0.30, 0.50],
    "vwap_deviation_fade": [0.75, 1.00, 1.25, 1.50, 2.00],
    "opening_impulse_continuation": [0.0010, 0.0015, 0.0020, 0.0030, 0.0040],
    "opening_impulse_reversal": [0.0010, 0.0015, 0.0020, 0.0030, 0.0040],
    "compression_breakout": [0.50, 0.65, 0.80, 1.00, 1.20],
    "range_expansion_reversal": [1.20, 1.50, 1.80, 2.20, 2.80],
}
STOP_POINTS = [4.0, 6.0, 8.0, 10.0, 12.0]


def build_registry() -> dict:
    trials = []
    for family, levels in FAMILY_LEVELS.items():
        for variant in range(10):
            level_idx = variant % 5
            trials.append({
                "trial_id": f"DISC100-{len(trials) + 1:03d}",
                "family": family,
                "variant": variant,
                "threshold": levels[level_idx],
                "stop_points": STOP_POINTS[level_idx],
                "reward_risk": 1.5 if variant < 5 else 2.0,
                "require_volume_confirmation": variant >= 5,
                "entry_start_et": ENTRY_START,
                "entry_end_et": ENTRY_END,
                "max_hold_bars_5m": MAX_HOLD_BARS,
            })
    payload = {
        "experiment": "PROFITABILITY-DISCOVERY-100",
        "preregistration": PREREG,
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


def prepare(raw: pd.DataFrame) -> tuple[pd.DataFrame, list, dict]:
    frame = raw.copy()
    frame["dt"] = pd.to_datetime(frame["timestamp"])
    frame["date"] = frame["dt"].dt.date
    sessions = sorted(frame["date"].unique())
    by_date = {}
    for session, bars in frame.groupby("date"):
        fields = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        five = bars.set_index("dt").resample("5min", label="left", closed="left").agg(fields).dropna().reset_index()
        five["time"] = five["dt"].dt.strftime("%H:%M")
        prior_close = five["close"].shift(1)
        tr = pd.concat([
            five["high"] - five["low"],
            (five["high"] - prior_close).abs(),
            (five["low"] - prior_close).abs(),
        ], axis=1).max(axis=1)
        five["atr"] = tr.rolling(14).mean()
        five["volume_mean"] = five["volume"].shift(1).rolling(20).mean()
        typical = (five["high"] + five["low"] + five["close"]) / 3
        five["vwap"] = (typical * five["volume"]).cumsum() / five["volume"].cumsum()
        five["ema20"] = five["close"].ewm(span=20, adjust=False).mean()
        five["ema50"] = five["close"].ewm(span=50, adjust=False).mean()
        by_date[session] = five
    return frame, sessions, by_date


def _volume_ok(row: pd.Series, required: bool) -> bool:
    if not required:
        return True
    mean = float(row["volume_mean"] or 0)
    return mean > 0 and float(row["volume"]) >= 1.2 * mean


def find_signal(bars: pd.DataFrame, trial: dict, previous: pd.DataFrame | None) -> tuple[int, int] | None:
    family = trial["family"]
    threshold = float(trial["threshold"])
    required_volume = bool(trial["require_volume_confirmation"])
    orb = bars.iloc[:6]
    if len(orb) < 6:
        return None
    orb_high, orb_low = float(orb["high"].max()), float(orb["low"].min())
    pdh = float(previous["high"].max()) if previous is not None else None
    pdl = float(previous["low"].min()) if previous is not None else None
    session_open = float(bars.iloc[0]["open"])

    for i in range(20, len(bars) - 1):
        row = bars.iloc[i]
        if row["time"] < ENTRY_START or row["time"] >= ENTRY_END or not _volume_ok(row, required_volume):
            continue
        close, open_, high, low = map(float, (row["close"], row["open"], row["high"], row["low"]))
        atr, vwap = float(row["atr"]), float(row["vwap"])
        if not math.isfinite(atr) or atr <= 0:
            continue
        side = 0
        if family == "orb_breakout":
            buffer = threshold * TICK
            side = 1 if close > orb_high + buffer else -1 if close < orb_low - buffer else 0
        elif family == "orb_failed_break":
            extension = threshold * TICK
            side = -1 if high >= orb_high + extension and close < orb_high else 1 if low <= orb_low - extension and close > orb_low else 0
        elif family == "prior_day_breakout" and pdh is not None:
            buffer = threshold * TICK
            side = 1 if close > pdh + buffer else -1 if close < pdl - buffer else 0
        elif family == "prior_day_reclaim" and pdh is not None:
            extension = threshold * TICK
            side = -1 if high >= pdh + extension and close < pdh else 1 if low <= pdl - extension and close > pdl else 0
        elif family == "vwap_trend_pullback":
            tolerance = threshold * atr
            bull = float(row["ema20"]) > float(row["ema50"]) and low <= vwap + tolerance and close > vwap and close > open_
            bear = float(row["ema20"]) < float(row["ema50"]) and high >= vwap - tolerance and close < vwap and close < open_
            side = 1 if bull else -1 if bear else 0
        elif family == "vwap_deviation_fade":
            distance = (close - vwap) / atr
            side = -1 if distance >= threshold and close < open_ else 1 if distance <= -threshold and close > open_ else 0
        elif family in {"opening_impulse_continuation", "opening_impulse_reversal"}:
            if row["time"] < "10:00":
                continue
            impulse = close / session_open - 1
            if abs(impulse) >= threshold:
                side = 1 if impulse > 0 else -1
                if family.endswith("reversal"):
                    side *= -1
        elif family == "compression_breakout":
            prior = bars.iloc[i - 6:i]
            compressed = float(prior["high"].max() - prior["low"].min()) <= threshold * atr
            if compressed:
                side = 1 if close > float(prior["high"].max()) else -1 if close < float(prior["low"].min()) else 0
        elif family == "range_expansion_reversal":
            candle_range = high - low
            if candle_range >= threshold * atr and candle_range > 0:
                upper_wick = high - max(open_, close)
                lower_wick = min(open_, close) - low
                side = -1 if upper_wick / candle_range >= 0.45 else 1 if lower_wick / candle_range >= 0.45 else 0
        if side:
            return i, side
    return None


def manage(bars: pd.DataFrame, signal_idx: int, side: int, trial: dict) -> float:
    entry = float(bars.iloc[signal_idx]["close"])
    stop_points = float(trial["stop_points"])
    rr = float(trial["reward_risk"])
    stop = entry - side * stop_points
    target = entry + side * stop_points * rr
    end = min(len(bars), signal_idx + 1 + MAX_HOLD_BARS)
    for _, row in bars.iloc[signal_idx + 1:end].iterrows():
        if row["time"] >= FLATTEN:
            return side * (float(row["close"]) - entry)
        if side > 0:
            if float(row["low"]) <= stop:
                return -stop_points
            if float(row["high"]) >= target:
                return stop_points * rr
        else:
            if float(row["high"]) >= stop:
                return -stop_points
            if float(row["low"]) <= target:
                return stop_points * rr
    exit_close = float(bars.iloc[end - 1]["close"])
    return side * (exit_close - entry)


def metrics(points: list[float], cost_mult: float = 1.0) -> dict:
    cost = 2 * COST_SIDE * cost_mult
    pnl = [value * POINT_VALUE - cost for value in points]
    if not pnl:
        return {"trades": 0, "expectancy": None, "profit_factor": None, "p_value": None}
    wins = sum(value for value in pnl if value > 0)
    losses = -sum(value for value in pnl if value <= 0)
    mean = sum(pnl) / len(pnl)
    variance = sum((value - mean) ** 2 for value in pnl) / max(1, len(pnl) - 1)
    se = math.sqrt(variance / len(pnl)) if variance > 0 else 0.0
    t_stat = mean / se if se > 0 else (float("inf") if mean > 0 else 0.0)
    p_value = 1 - NormalDist().cdf(t_stat) if math.isfinite(t_stat) else 0.0
    equity = pd.Series([0.0, *pnl]).cumsum()
    return {
        "trades": len(pnl),
        "total_pnl": round(sum(pnl), 2),
        "expectancy": round(mean, 4),
        "win_rate": round(sum(value > 0 for value in pnl) / len(pnl), 4),
        "profit_factor": round(wins / losses, 4) if losses else None,
        "max_drawdown": round(float((equity.cummax() - equity).max()), 2),
        "t_stat": round(t_stat, 4) if math.isfinite(t_stat) else None,
        "p_value": round(p_value, 8),
    }


def run(raw: pd.DataFrame, registry: dict) -> dict:
    _, sessions, by_date = prepare(raw)
    dev_end = int(len(sessions) * 0.70)
    selection_end = int(len(sessions) * 0.85)
    development = sessions[:dev_end]
    third = len(development) // 3
    regimes = [set(development[:third]), set(development[third:2 * third]), set(development[2 * third:])]
    results = []
    for trial in registry["trials"]:
        points_by_date = {}
        for idx, session in enumerate(development):
            previous = by_date.get(sessions[sessions.index(session) - 1]) if sessions.index(session) > 0 else None
            signal = find_signal(by_date[session], trial, previous)
            if signal is not None:
                points_by_date[session] = manage(by_date[session], signal[0], signal[1], trial)
        regime_metrics = [metrics([value for date, value in points_by_date.items() if date in regime]) for regime in regimes]
        aggregate = metrics(list(points_by_date.values()))
        stress = metrics(list(points_by_date.values()), cost_mult=2.0)
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
        results.append({**trial, "development_regimes": regime_metrics, "development": aggregate, "development_2x_cost": stress, "discovery_survivor": survives})
    survivors = [row for row in results if row["discovery_survivor"]]
    family_best = []
    for family in FAMILY_LEVELS:
        rows = [row for row in results if row["family"] == family]
        rows.sort(key=lambda row: (row["development_2x_cost"].get("expectancy") or -1e9), reverse=True)
        family_best.append(rows[0])
    return {
        "experiment": registry["experiment"],
        "registry_sha256": registry["registry_sha256"],
        "mode": "development_only_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "dataset_sessions": len(sessions),
        "development_sessions": len(development),
        "sealed_selection_sessions": selection_end - dev_end,
        "sealed_final_sessions": len(sessions) - selection_end,
        "trial_count": len(results),
        "effective_attempt_count": EFFECTIVE_ATTEMPTS,
        "bonferroni_alpha": BONFERRONI_ALPHA,
        "survivor_count": len(survivors),
        "survivors": survivors,
        "family_best_development_only": family_best,
        "trials": results,
        "warning": "Development rankings are not execution evidence. Selection and final slices remain sealed.",
    }


def build_ledger_import(report: dict, raw: pd.DataFrame) -> list[dict]:
    frame = raw.copy()
    frame["dt"] = pd.to_datetime(frame["timestamp"])
    sessions = sorted(frame["dt"].dt.date.unique())
    development = sessions[:int(len(sessions) * 0.70)]
    records = []
    for trial in report["trials"]:
        result = trial["development"]
        records.append({
            "edge_id": f"discovery100_{trial['family']}",
            "hypothesis": f"{trial['family']} variant {trial['variant']} has stable positive MES expectancy after costs.",
            "variant": trial["trial_id"],
            "stage": "in_sample",
            "dataset_start": str(development[0]),
            "dataset_end": str(development[-1]),
            "cost_model": "MES one contract; $1.24 commission plus one tick slippage per side; doubled-cost stress also evaluated",
            "metrics": {
                "trade_count": result.get("trades"),
                "expectancy": result.get("expectancy"),
                "profit_factor": result.get("profit_factor"),
                "max_drawdown": result.get("max_drawdown"),
                "t_stat": result.get("t_stat"),
                "p_value": result.get("p_value"),
                "development_survivor": trial.get("discovery_survivor", False),
                "double_cost_expectancy": trial["development_2x_cost"].get("expectancy"),
            },
            "parameters": {
                key: trial[key]
                for key in ("threshold", "stop_points", "reward_risk", "require_volume_confirmation", "max_hold_bars_5m")
            },
            "source": "data/profitability_discovery_100_results.json",
            "code_version": report["registry_sha256"],
        })
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-registry-only", action="store_true")
    parser.add_argument("--write-ledger-import-only", action="store_true")
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    registry = build_registry()
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    if args.write_registry_only:
        print(json.dumps({"trial_count": registry["trial_count"], "registry_sha256": registry["registry_sha256"]}, indent=2))
        return
    if args.write_ledger_import_only:
        report = json.loads(OUT.read_text(encoding="utf-8"))
        records = build_ledger_import(report, pd.read_csv(CSV))
        LEDGER_IMPORT.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ledger_records": len(records), "path": str(LEDGER_IMPORT)}, indent=2))
        return
    report = run(pd.read_csv(CSV), registry)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.print_report:
        summary = {key: value for key, value in report.items() if key not in {"trials", "family_best_development_only", "survivors"}}
        summary["family_best"] = [{"family": row["family"], "trial_id": row["trial_id"], "metrics": row["development_2x_cost"]} for row in report["family_best_development_only"]]
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
