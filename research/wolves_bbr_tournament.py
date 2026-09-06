#!/usr/bin/env python3
"""Preregistered, shadow-only tournament for the Wolves/BBR hypothesis."""
from __future__ import annotations

import argparse, json, math
from pathlib import Path
from typing import Any
import pandas as pd

try:
    from research import global_social_sequence_tournament as base
    from research import multi_timeframe_edge_tournament as mtf
except ModuleNotFoundError:
    import global_social_sequence_tournament as base
    import multi_timeframe_edge_tournament as mtf

ROOT = Path(__file__).resolve().parents[1]
PATHS = {"SPY": ROOT / "data/liquid_edge_lab/spy_5m.parquet", "QQQ": ROOT / "data/liquid_edge_lab/qqq_5m.parquet"}
TIMEFRAMES = (5, 15)
BASELINE_COST = mtf.BASELINE_COST
NOTIONAL = mtf.NOTIONAL
REWARD_RISK = 2.0
MAX_HOLD_MINUTES = 60
PREREGISTRATION = "research/WOLVES_OF_WEALTH_BBR_PREREGISTRATION_2026-08-31.md"
DEFAULT_OUT = ROOT / "data/wolves_bbr_tournament.json"

def _prepare(bars: pd.DataFrame) -> pd.DataFrame:
    out = bars.copy().reset_index(drop=True)
    for span in (8, 13, 21, 48, 200):
        out[f"ema{span}"] = out["close"].ewm(span=span, adjust=False, min_periods=span).mean()
    return out

def _signal(bars: pd.DataFrame, levels: dict[str, float] | None, mode: str) -> tuple[int, int, float] | None:
    if levels is None:
        return None
    ydh, ydl, pmh, pml = (levels[key] for key in ("ydh", "ydl", "pmh", "pml"))
    for idx in range(1, len(bars) - 1):
        row, prior = bars.iloc[idx], bars.iloc[idx - 1]
        long_level = max(ydh, pmh); short_level = min(ydl, pml)
        ema_long = float(row["close"]) > float(row["ema200"]) and float(row["ema13"]) > float(row["ema48"])
        ema_short = float(row["close"]) < float(row["ema200"]) and float(row["ema13"]) < float(row["ema48"])
        broke_long = float(row["close"]) > long_level and float(prior["close"]) <= long_level
        broke_short = float(row["close"]) < short_level and float(prior["close"]) >= short_level
        if mode in ("levels", "full") and broke_long and (mode == "levels" or ema_long):
            return idx, 1, float(prior["low"])
        if mode in ("levels", "full") and broke_short and (mode == "levels" or ema_short):
            return idx, -1, float(prior["high"])
    return None

def _simulate(bars: pd.DataFrame, signal: tuple[int,int,float], timeframe: int) -> float | None:
    idx, side, stop = signal; entry_idx = idx + 1
    if entry_idx >= len(bars): return None
    entry = float(bars.iloc[entry_idx]["open"]); risk = side * (entry - stop)
    if risk <= 0 or risk / entry > .02: return None
    target = entry + side * risk * REWARD_RISK
    end = min(len(bars)-1, entry_idx + max(1, math.ceil(MAX_HOLD_MINUTES/timeframe))-1)
    exit_price = float(bars.iloc[end]["close"])
    for _, row in bars.iloc[entry_idx:end+1].iterrows():
        if (float(row["low"]) <= stop if side > 0 else float(row["high"]) >= stop): exit_price = stop; break
        if (float(row["high"]) >= target if side > 0 else float(row["low"]) <= target): exit_price = target; break
    return side * (exit_price-entry) * (NOTIONAL/entry)

def _resample_sessions(source: dict[str, pd.DataFrame], minutes: int) -> dict[str, pd.DataFrame]:
    """Derive 15m bars from already validated complete 5m RTH sessions."""
    result: dict[str, pd.DataFrame] = {}
    for day, bars in source.items():
        frame = bars.set_index("dt").resample(
            f"{minutes}min", origin="start_day", offset="30min", label="left", closed="left"
        ).agg({"open":"first", "high":"max", "low":"min", "close":"last", "volume":"sum"}).dropna().reset_index()
        frame["time"] = frame["dt"].dt.strftime("%H:%M")
        result[day] = frame
    return result

def run() -> dict[str, Any]:
    trials=[]
    for market,path in PATHS.items():
        dates, source_5m = mtf.load_sessions(path, 5)
        session_sets = {5: source_5m, 15: _resample_sessions(source_5m, 15)}
        for tf in TIMEFRAMES:
            sessions = session_sets[tf]
            # EMA state carries through completed prior bars/sessions; resetting it
            # each morning would make a 200 EMA impossible on an intraday session.
            joined = pd.concat([sessions[day].assign(date=day) for day in dates], ignore_index=True)
            joined = _prepare(joined)
            prepared_sessions = {day: chunk.reset_index(drop=True) for day, chunk in joined.groupby("date", sort=True)}
            context: dict[str, dict[str, float] | None] = {}
            parsed = {day: pd.Timestamp(day) for day in dates}
            month_levels: dict[object, dict[str, float]] = {}
            for month, month_days in pd.Series(dates, index=dates).groupby(lambda day: parsed[day].to_period("M")):
                month_bars = pd.concat([prepared_sessions[day] for day in month_days.tolist()], ignore_index=True)
                month_levels[month] = {"pmh": float(month_bars["high"].max()), "pml": float(month_bars["low"].min())}
            for i, day in enumerate(dates):
                if not i:
                    context[day] = None
                    continue
                prior = prepared_sessions[dates[i - 1]]
                current_month = parsed[day].to_period("M")
                prior_month = current_month - 1
                previous_month = month_levels.get(prior_month)
                if previous_month is None:
                    context[day] = None
                    continue
                context[day] = {"ydh": float(prior["high"].max()), "ydl": float(prior["low"].min()), **previous_month}
            for mode in ("levels", "full"):
                vals=[]
                for i,day in enumerate(dates):
                    sig=_signal(prepared_sessions[day], context[day], mode)
                    if sig:
                        v=_simulate(prepared_sessions[day], sig, tf)
                        if v is not None: vals.append(v)
                trials.append({"trial_id":f"BBR-{market}-{tf}m-{mode}","market":market,"timeframe_minutes":tf,"mode":mode,"sessions":len(dates),"metrics":base._metrics(vals,BASELINE_COST),"double_friction":base._metrics(vals,BASELINE_COST*2),"promotion_eligible":False,"rank_effect":"none"})
    return {"schema_version":1,"experiment":"WOLVES-BBR-2026-08-31","mode":"historical_research_only","execution_enabled":False,"preregistration":PREREGISTRATION,"trials":trials,"verdict":"no_promotion_without_forward_shadow","warning":"PMH/PML use completed prior calendar-month levels; exact retest, stop, and EMA-ladder exit semantics still require confirmation before promotion."}

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--print",action="store_true",dest="show"); p.add_argument("--output",type=Path,default=DEFAULT_OUT); a=p.parse_args(); report=run(); a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,indent=2)+"\n")
    if a.show: print(json.dumps(report,indent=2))
    return 0
if __name__ == "__main__": raise SystemExit(main())
