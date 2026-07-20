#!/usr/bin/env python3
"""Preregistered MES VWAP band-fade test on classified range days.

Spec frozen in research/MES_VWAP_FADE_PREREGISTRATION_2026-07-19.md.
Research only.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "examples" / "mes_v0_1m_2022-01-01_2026-07-19_rth.csv"
OUT = ROOT / "data" / "mes_vwap_fade_results.json"

TICK = 0.25
POINT_USD = 5.0
STOP_PTS = 8.0
COST_PER_SIDE = 1.24 + 1 * TICK * POINT_USD
ENTRY_START = "09:45"
ENTRY_END = "12:00"
FLATTEN = "15:55"
TIME_STOP_BARS = 60
ACCEPTANCE_BARS = 10

CONFIGS = [
    {"name": f"band{k}_wick{w}", "k": k, "wick_ticks": w}
    for k in (1.0, 1.5)
    for w in (0, 2)
]


def session_bands(bars: pd.DataFrame, k: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    tp = (bars["high"] + bars["low"] + bars["close"]).to_numpy() / 3.0
    vol = bars["volume"].to_numpy().astype(float)
    cum_vol = np.cumsum(vol)
    vwap = np.cumsum(tp * vol) / cum_vol
    var = np.cumsum(vol * (tp - vwap) ** 2) / cum_vol
    sigma = np.sqrt(np.maximum(var, 0.0))
    return vwap, vwap + k * sigma, vwap - k * sigma


def simulate_session(bars: pd.DataFrame, k: float, wick_ticks: int) -> float | None:
    vwap, upper, lower = session_bands(bars, k)
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    close = bars["close"].to_numpy()
    times = bars["time"].to_numpy()

    outside_run = 0
    for i in range(len(bars)):
        if close[i] > upper[i] or close[i] < lower[i]:
            outside_run += 1
            if outside_run >= ACCEPTANCE_BARS:
                return None
        else:
            outside_run = 0
        time = times[i]
        if time < ENTRY_START or time >= ENTRY_END:
            continue
        direction = 0
        if high[i] >= upper[i] + wick_ticks * TICK and close[i] < upper[i]:
            direction = -1
        elif low[i] <= lower[i] - wick_ticks * TICK and close[i] > lower[i]:
            direction = 1
        if direction == 0:
            continue
        entry = close[i]
        stop = entry - direction * STOP_PTS
        for j in range(i + 1, len(bars)):
            if times[j] >= FLATTEN or j - i > TIME_STOP_BARS:
                return direction * (close[j] - entry)
            if direction > 0:
                if low[j] <= stop:
                    return -STOP_PTS
                if high[j] >= vwap[j]:
                    return direction * (vwap[j] - entry)
            else:
                if high[j] >= stop:
                    return -STOP_PTS
                if low[j] <= vwap[j]:
                    return direction * (vwap[j] - entry)
        return direction * (close[-1] - entry)
    return None


def stats(trades: list[float], cost_mult: float) -> dict:
    cost = 2 * COST_PER_SIDE * cost_mult
    pnl = [t * POINT_USD - cost for t in trades]
    if not pnl:
        return {"trades": 0}
    wins = sum(p for p in pnl if p > 0)
    losses = -sum(p for p in pnl if p <= 0)
    equity = pd.Series(pnl).cumsum()
    return {
        "trades": len(pnl),
        "total_pnl": round(sum(pnl), 2),
        "expectancy": round(sum(pnl) / len(pnl), 2),
        "win_rate": round(sum(1 for p in pnl if p > 0) / len(pnl), 4),
        "profit_factor": round(wins / losses, 4) if losses > 0 else None,
        "max_drawdown": round(float((equity.cummax() - equity).max()), 2),
    }


def main() -> None:
    df = pd.read_csv(CSV)
    df["dt"] = pd.to_datetime(df["timestamp"])
    df["date"] = df["dt"].dt.date
    df["time"] = df["dt"].dt.strftime("%H:%M")
    sessions = sorted(df["date"].unique())
    n = len(sessions)
    dev_end, sel_end = int(n * 0.70), int(n * 0.85)
    dev, sel, fin = sessions[:dev_end], sessions[dev_end:sel_end], sessions[sel_end:]
    third = len(dev) // 3
    regimes = [set(dev[:third]), set(dev[third: 2 * third]), set(dev[2 * third:])]
    by_date = {date: group.reset_index(drop=True) for date, group in df.groupby("date")}

    results = {
        "preregistration": "research/MES_VWAP_FADE_PREREGISTRATION_2026-07-19.md",
        "dataset": str(CSV.name),
        "sessions": n,
        "development_sessions": len(dev),
        "selection_sessions": len(sel),
        "final_sessions": len(fin),
        "configs": {},
    }
    for config in CONFIGS:
        trades = {
            date: pnl
            for date in sessions
            if (pnl := simulate_session(by_date[date], config["k"], config["wick_ticks"])) is not None
        }
        entry = {"development_regimes": [stats([p for d, p in trades.items() if d in regime], 1.0) for regime in regimes]}
        entry["development"] = stats([p for d, p in trades.items() if d in set(dev)], 1.0)
        dev_pass = all(r.get("trades", 0) > 0 and r.get("expectancy", 0) > 0 for r in entry["development_regimes"])
        entry["development_pass"] = dev_pass
        if dev_pass:
            sel_trades = [p for d, p in trades.items() if d in set(sel)]
            entry["selection"] = stats(sel_trades, 1.0)
            entry["selection_2x"] = stats(sel_trades, 2.0)
            sel_pass = (
                entry["selection"].get("expectancy", 0) > 0
                and (entry["selection"].get("profit_factor") or 0) >= 1.20
                and entry["selection_2x"].get("expectancy", 0) > 0
            )
            entry["selection_pass"] = sel_pass
            if sel_pass:
                fin_trades = [p for d, p in trades.items() if d in set(fin)]
                entry["final"] = stats(fin_trades, 1.0)
                entry["final_2x"] = stats(fin_trades, 2.0)
                entry["final_pass"] = (
                    entry["final"].get("trades", 0) >= 30
                    and (entry["final"].get("profit_factor") or 0) >= 1.20
                    and entry["final_2x"].get("expectancy", 0) > 0
                    and entry["final"].get("max_drawdown", 1e9) <= 200.0
                )
        results["configs"][config["name"]] = entry

    OUT.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
