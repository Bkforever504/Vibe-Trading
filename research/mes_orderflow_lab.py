#!/usr/bin/env python3
"""Preregistered MES quote-flow tests (H1 imbalance drift, H3 opening pressure).

Spec frozen in research/MES_ORDERFLOW_PREREGISTRATION_2026-07-19.md before
the data was opened. H2 diagnostic is deferred (documented in results).
Research only.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DBN = ROOT / "data" / "databento" / "mes_v0_bbo1s_2024-01-01_2026-07-19.dbn.zst"
PARQUET = ROOT / "data" / "databento" / "mes_v0_bbo1s_rth.parquet"
OHLC_MANIFEST = ROOT / "data" / "databento_futures_manifest.json"
OUT = ROOT / "data" / "mes_orderflow_results.json"
NY = "America/New_York"

TICK = 0.25
POINT_USD = 5.0
COMMISSION = 1.24
H1_WINDOW = 300
H1_THRESHOLDS = (0.35, 0.50)
H1_MAX_TRADES_DAY = 3
H3_MIN_IMBALANCE = 0.25
H3_STOP_TICKS = 40
H3_RRS = (1.5, 2.0)


def excluded_sessions() -> set[str]:
    manifest = json.loads(OHLC_MANIFEST.read_text(encoding="utf-8"))
    result = manifest["results"][0]
    excluded = set(result.get("roll_sessions_excluded", []))
    excluded.update(result.get("dataset_condition_dates_excluded", {}).keys())
    return excluded


def build_parquet() -> None:
    if PARQUET.exists():
        return
    import databento as db

    store = db.DBNStore.from_file(DBN)
    tmp = PARQUET.with_suffix(".tmp.parquet")
    if tmp.exists():
        tmp.unlink()
    store.to_parquet(tmp)
    tmp.rename(PARQUET)


def load_seconds() -> pd.DataFrame:
    import pyarrow.parquet as pq

    frames = []
    parquet = pq.ParquetFile(PARQUET)
    columns = None
    for batch in parquet.iter_batches(batch_size=2_000_000):
        chunk = batch.to_pandas()
        if columns is None:
            names = set(chunk.columns)
            def pick(*options):
                for option in options:
                    if option in names:
                        return option
                raise KeyError(options)
            columns = {
                "ts": pick("ts_recv", "ts_event"),
                "bid_px": pick("bid_px_00", "bid_px"),
                "ask_px": pick("ask_px_00", "ask_px"),
                "bid_sz": pick("bid_sz_00", "bid_sz"),
                "ask_sz": pick("ask_sz_00", "ask_sz"),
            }
        ts = pd.to_datetime(chunk[columns["ts"]], utc=True).dt.tz_convert(NY)
        keep = (ts.dt.hour * 60 + ts.dt.minute).between(9 * 60 + 30, 16 * 60 - 1) & (ts.dt.dayofweek < 5)
        if not keep.any():
            continue
        sub = pd.DataFrame({
            "ts": ts[keep].values,
            "bid": chunk.loc[keep.values, columns["bid_px"]].astype(float).values,
            "ask": chunk.loc[keep.values, columns["ask_px"]].astype(float).values,
            "bid_sz": chunk.loc[keep.values, columns["bid_sz"]].astype(float).values,
            "ask_sz": chunk.loc[keep.values, columns["ask_sz"]].astype(float).values,
        })
        frames.append(sub)
    data = pd.concat(frames, ignore_index=True)
    scale = 1e-9 if data["bid"].median() > 1e6 else 1.0
    data["bid"] *= scale
    data["ask"] *= scale
    data["date"] = data["ts"].dt.date.astype(str)
    data["imb"] = (data["bid_sz"] - data["ask_sz"]) / (data["bid_sz"] + data["ask_sz"]).replace(0, np.nan)
    data["imb"] = data["imb"].fillna(0.0)
    data["sec"] = data["ts"].dt.hour * 3600 + data["ts"].dt.minute * 60 + data["ts"].dt.second
    return data


def cost_usd(entry_spread_paid: bool, stress: bool) -> float:
    commission = 2 * COMMISSION * (2 if stress else 1)
    extra_slippage = 2 * TICK * POINT_USD if stress else 0.0
    return commission + extra_slippage


def h1_session(session: pd.DataFrame, threshold: float) -> list[float]:
    session = session.sort_values("sec")
    sec = session["sec"].to_numpy()
    bid = session["bid"].to_numpy()
    ask = session["ask"].to_numpy()
    imb = pd.Series(session["imb"].to_numpy()).rolling(H1_WINDOW, min_periods=H1_WINDOW).mean().to_numpy()
    trades = []
    i = H1_WINDOW
    busy_until = -1
    while i < len(sec) and len(trades) < H1_MAX_TRADES_DAY:
        t = sec[i]
        if t < 9 * 3600 + 35 * 60 or t >= 15 * 3600 + 30 * 60 or sec[i] < busy_until:
            i += 1
            continue
        direction = 1 if imb[i] >= threshold else (-1 if imb[i] <= -threshold else 0)
        if direction == 0:
            i += 1
            continue
        exit_target = t + H1_WINDOW
        j = np.searchsorted(sec, min(exit_target, 15 * 3600 + 55 * 60))
        j = min(j, len(sec) - 1)
        if direction > 0:
            pnl_points = bid[j] - ask[i]
        else:
            pnl_points = bid[i] - ask[j]
        trades.append(pnl_points * POINT_USD)
        busy_until = sec[j]
        i = j + 1
    return trades


def h3_session(session: pd.DataFrame, rr: float) -> float | None:
    session = session.sort_values("sec")
    sec = session["sec"].to_numpy()
    open_mask = (sec >= 9 * 3600 + 30 * 60) & (sec < 9 * 3600 + 35 * 60)
    if open_mask.sum() < 200:
        return None
    open_imb = float(session["imb"].to_numpy()[open_mask].mean())
    if abs(open_imb) < H3_MIN_IMBALANCE:
        return None
    direction = 1 if open_imb > 0 else -1
    start = np.searchsorted(sec, 9 * 3600 + 35 * 60)
    if start >= len(sec):
        return None
    bid = session["bid"].to_numpy()
    ask = session["ask"].to_numpy()
    mid = (bid + ask) / 2
    entry = ask[start] if direction > 0 else bid[start]
    stop_pts = H3_STOP_TICKS * TICK
    stop = entry - direction * stop_pts
    target = entry + direction * rr * stop_pts
    for j in range(start + 1, len(sec)):
        if sec[j] >= 15 * 3600 + 55 * 60:
            exit_px = bid[j] if direction > 0 else ask[j]
            return direction * (exit_px - entry) * POINT_USD
        if direction > 0:
            if mid[j] <= stop:
                return direction * (bid[j] - entry) * POINT_USD
            if mid[j] >= target:
                return direction * (bid[j] - entry) * POINT_USD
        else:
            if mid[j] >= stop or mid[j] <= target:
                return (entry - ask[j]) * POINT_USD
    exit_px = bid[-1] if direction > 0 else ask[-1]
    return direction * (exit_px - entry) * POINT_USD


def stats(trades: list[float], stress: bool) -> dict:
    cost = cost_usd(True, stress)
    pnl = [t - cost for t in trades]
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


def gated(trades_by_date: dict[str, list[float]], sessions: list[str]) -> dict:
    n = len(sessions)
    dev_end, sel_end = int(n * 0.70), int(n * 0.85)
    dev, sel, fin = sessions[:dev_end], sessions[dev_end:sel_end], sessions[sel_end:]
    third = len(dev) // 3
    regimes = [dev[:third], dev[third: 2 * third], dev[2 * third:]]
    def collect(dates):
        return [t for d in dates for t in trades_by_date.get(d, [])]
    entry = {"development_regimes": [stats(collect(r), False) for r in regimes],
             "development": stats(collect(dev), False)}
    dev_pass = all(r.get("trades", 0) > 0 and r.get("expectancy", 0) > 0 for r in entry["development_regimes"])
    entry["development_pass"] = dev_pass
    if dev_pass:
        entry["selection"] = stats(collect(sel), False)
        entry["selection_stressed"] = stats(collect(sel), True)
        sel_pass = (entry["selection"].get("expectancy", 0) > 0
                    and (entry["selection"].get("profit_factor") or 0) >= 1.20
                    and entry["selection_stressed"].get("expectancy", 0) > 0)
        entry["selection_pass"] = sel_pass
        if sel_pass:
            entry["final"] = stats(collect(fin), False)
            entry["final_stressed"] = stats(collect(fin), True)
            entry["final_pass"] = (entry["final"].get("trades", 0) >= 30
                                   and (entry["final"].get("profit_factor") or 0) >= 1.20
                                   and entry["final_stressed"].get("expectancy", 0) > 0
                                   and entry["final"].get("max_drawdown", 1e9) <= 200.0)
    return entry


def main() -> None:
    build_parquet()
    data = load_seconds()
    excluded = excluded_sessions()
    coverage = data.groupby("date")["sec"].count()
    complete = {d for d, c in coverage.items() if c >= 0.8 * 6.5 * 3600}
    sessions = sorted(d for d in complete if d not in excluded)
    data = data[data["date"].isin(sessions)]
    by_date = dict(tuple(data.groupby("date")))

    results = {
        "preregistration": "research/MES_ORDERFLOW_PREREGISTRATION_2026-07-19.md",
        "sessions": len(sessions),
        "sessions_excluded_roll_or_condition": len(excluded),
        "sessions_excluded_low_coverage": int(len(coverage) - len(complete)),
        "h2_diagnostic": "deferred - requires per-trade ORB export, queued separately",
        "configs": {},
    }
    for threshold in H1_THRESHOLDS:
        trades_by_date = {d: h1_session(s, threshold) for d, s in by_date.items()}
        results["configs"][f"h1_imbalance_{threshold}"] = gated(trades_by_date, sessions)
    for rr in H3_RRS:
        trades_by_date = {}
        for d, s in by_date.items():
            pnl = h3_session(s, rr)
            if pnl is not None:
                trades_by_date[d] = [pnl]
        results["configs"][f"h3_open_pressure_rr{rr}"] = gated(trades_by_date, sessions)

    OUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
