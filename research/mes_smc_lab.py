#!/usr/bin/env python3
"""Preregistered MES liquidity-sweep fade and FVG continuation test.

Spec frozen in research/MES_SMC_PREREGISTRATION_2026-07-19.md. Research only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "examples" / "mes_v0_1m_2022-01-01_2026-07-19_rth.csv"
OUT = ROOT / "data" / "mes_smc_results.json"

TICK = 0.25
POINT_USD = 5.0
STOP_PTS = 10.0
COST_PER_SIDE = 1.24 + 1 * TICK * POINT_USD
ENTRY_START = "09:35"
ENTRY_END = "12:00"
FLATTEN = "15:55"

CONFIGS = [
    {"name": "sweep_fade_rr1.5", "kind": "sweep", "rr": 1.5},
    {"name": "sweep_fade_rr2.0", "kind": "sweep", "rr": 2.0},
    {"name": "fvg_gap4_rr1.5", "kind": "fvg", "gap_ticks": 4, "rr": 1.5},
    {"name": "fvg_gap4_rr2.0", "kind": "fvg", "gap_ticks": 4, "rr": 2.0},
    {"name": "fvg_gap8_rr1.5", "kind": "fvg", "gap_ticks": 8, "rr": 1.5},
    {"name": "fvg_gap8_rr2.0", "kind": "fvg", "gap_ticks": 8, "rr": 2.0},
]


def manage_trade(bars: pd.DataFrame, entry_idx: int, entry: float, direction: int, rr: float) -> float:
    stop = entry - direction * STOP_PTS
    target = entry + direction * rr * STOP_PTS
    for _, bar in bars.iloc[entry_idx:].iterrows():
        if bar["time"] >= FLATTEN:
            return direction * (bar["close"] - entry)
        if direction > 0:
            if bar["low"] <= stop:
                return -STOP_PTS
            if bar["high"] >= target:
                return rr * STOP_PTS
        else:
            if bar["high"] >= stop:
                return -STOP_PTS
            if bar["low"] <= target:
                return rr * STOP_PTS
    return direction * (bars.iloc[-1]["close"] - entry)


def sweep_signal(bars: pd.DataFrame, pdh: float, pdl: float) -> tuple[int, float, int] | None:
    swept_high_at = swept_low_at = None
    for i, (_, bar) in enumerate(bars.iterrows()):
        time = bar["time"]
        if time < ENTRY_START or time >= ENTRY_END:
            if swept_high_at is None and bar["high"] >= pdh + 2 * TICK:
                swept_high_at = i
            if swept_low_at is None and bar["low"] <= pdl - 2 * TICK:
                swept_low_at = i
            continue
        if swept_high_at is not None and i - swept_high_at <= 15 and bar["close"] < pdh:
            return -1, bar["close"], i + 1
        if swept_low_at is not None and i - swept_low_at <= 15 and bar["close"] > pdl:
            return 1, bar["close"], i + 1
        if swept_high_at is None and bar["high"] >= pdh + 2 * TICK:
            swept_high_at = i
        if swept_low_at is None and bar["low"] <= pdl - 2 * TICK:
            swept_low_at = i
    return None


def fvg_signal(bars: pd.DataFrame, gap_ticks: int) -> tuple[int, float, int] | None:
    five = bars.set_index("dt").resample("5min", label="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()
    gaps: list[tuple[pd.Timestamp, int, float]] = []
    times = five.index
    for i in range(2, len(five)):
        formed = times[i] + pd.Timedelta(minutes=5)
        if formed.strftime("%H:%M") > ENTRY_END:
            break
        up_gap = five.iloc[i]["low"] - five.iloc[i - 2]["high"]
        down_gap = five.iloc[i - 2]["low"] - five.iloc[i]["high"]
        if up_gap >= gap_ticks * TICK:
            gaps.append((formed, 1, (five.iloc[i]["low"] + five.iloc[i - 2]["high"]) / 2))
        elif down_gap >= gap_ticks * TICK:
            gaps.append((formed, -1, (five.iloc[i - 2]["low"] + five.iloc[i]["high"]) / 2))
    for formed, direction, midpoint in gaps:
        after = bars[bars["dt"] >= formed]
        for i, (_, bar) in enumerate(after.iterrows()):
            if bar["time"] < ENTRY_START or bar["time"] >= ENTRY_END:
                continue
            if direction > 0 and bar["low"] <= midpoint:
                return 1, midpoint, bars.index.get_loc(after.index[i]) + 1
            if direction < 0 and bar["high"] >= midpoint:
                return -1, midpoint, bars.index.get_loc(after.index[i]) + 1
    return None


def stats(trades: list[float], cost_mult: float) -> dict:
    cost = 2 * COST_PER_SIDE * cost_mult
    pnl = [t * POINT_USD - cost for t in trades]
    if not pnl:
        return {"trades": 0}
    wins = sum(p for p in pnl if p > 0)
    losses = -sum(p for p in pnl if p <= 0)
    equity = pd.Series(pnl).cumsum()
    max_dd = float((equity.cummax() - equity).max())
    return {
        "trades": len(pnl),
        "total_pnl": round(sum(pnl), 2),
        "expectancy": round(sum(pnl) / len(pnl), 2),
        "win_rate": round(sum(1 for p in pnl if p > 0) / len(pnl), 4),
        "profit_factor": round(wins / losses, 4) if losses > 0 else None,
        "max_drawdown": round(max_dd, 2),
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
        "preregistration": "research/MES_SMC_PREREGISTRATION_2026-07-19.md",
        "dataset": str(CSV.name),
        "sessions": n,
        "development_sessions": len(dev),
        "selection_sessions": len(sel),
        "final_sessions": len(fin),
        "configs": {},
    }
    for config in CONFIGS:
        trades: dict[object, float] = {}
        prev_date = None
        for date in sessions:
            bars = by_date[date]
            if config["kind"] == "sweep":
                if prev_date is None:
                    prev_date = date
                    continue
                prev = by_date[prev_date]
                signal = sweep_signal(bars, prev["high"].max(), prev["low"].min())
            else:
                signal = fvg_signal(bars, config["gap_ticks"])
            prev_date = date
            if signal is None:
                continue
            direction, entry, next_idx = signal
            if next_idx >= len(bars):
                continue
            trades[date] = manage_trade(bars, next_idx, entry, direction, config["rr"])

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
